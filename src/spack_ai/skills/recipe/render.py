"""PackageRecipe -> package.py source, and the on-disk Spack repository layout."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spack_ai.naming import package_dir_name
from spack_ai.schemas import BuildSystem, DependsOn, PackageRecipe, Variant

_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)
_DEFAULT_TYPES = ["build", "link"]


def render_recipe(recipe: PackageRecipe, v1_imports: bool = True) -> str:
    template = _TEMPLATES.get_template("package.py.j2")
    return template.render(
        v1_imports=v1_imports,
        build_module=recipe.build_system.spack_module,
        base_class=recipe.base_class,
        class_name=recipe.class_name,
        description=recipe.description.replace('"""', "'''")
        or "FIXME: Put a proper description of your package here.",
        header=_header(recipe),
        notes=recipe.notes,
        directive_blocks=[
            [f'maintainers({", ".join(_q(m) for m in recipe.maintainers)})']
            if recipe.maintainers else [],
            [f"license({_q(recipe.license)})"] if recipe.license else [],
            _version_lines(recipe),
            _variant_lines(recipe.variants),
            _depends_lines(recipe.dependencies),
        ],
        methods=_methods(recipe),
    ).rstrip() + "\n"


# -------------------------------------------------------------------------- directives


def _q(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _header(recipe: PackageRecipe) -> list[str]:
    lines = [f"homepage = {_q(recipe.homepage)}" if recipe.homepage
             else 'homepage = "https://www.example.com"  # FIXME']
    if recipe.url:
        lines.append(f"url = {_q(recipe.url)}")
    if recipe.git:
        lines.append(f"git = {_q(recipe.git)}")
    if not recipe.url and not recipe.git:
        lines.append('url = "https://www.example.com/example-1.0.tar.gz"  # FIXME')
    return lines


def _version_lines(recipe: PackageRecipe) -> list[str]:
    lines: list[str] = []
    for v in recipe.versions:
        kwargs = []
        for key in ("sha256", "url", "tag", "commit", "branch"):
            value = getattr(v, key)
            if value:
                kwargs.append(f"{key}={_q(value)}")
        if v.preferred:
            kwargs.append("preferred=True")
        if not (v.sha256 or v.tag or v.commit or v.branch):
            lines.append(
                f"# FIXME: version({_q(v.version)}, sha256=...)  "
                f"<- run `spack checksum {recipe.name} {v.version}`"
            )
            continue
        lines.append(f"version({', '.join([_q(v.version), *kwargs])})")
    if not lines:
        lines.append(f"# FIXME: add versions, e.g. via `spack checksum {recipe.name}`")
    return lines


def _variant_lines(variants: list[Variant]) -> list[str]:
    lines = []
    for v in variants:
        if v.comment:
            lines.append(f"# {v.comment}")
        args = [_q(v.name), f"default={v.default!r}" if isinstance(v.default, bool)
                else f"default={_q(v.default)}"]
        if v.values:
            values = ", ".join(_q(x) for x in v.values) + ("," if len(v.values) == 1 else "")
            args.append(f"values=({values})")
            if v.multi:
                args.append("multi=True")
        args.append(f"description={_q(v.description)}")
        lines.append(f"variant({', '.join(args)})")
    return lines


def _depends_lines(deps: list[DependsOn]) -> list[str]:
    lines = []
    for d in deps:
        args = [_q(d.spec)]
        if d.type != _DEFAULT_TYPES:
            if len(d.type) == 1:
                args.append(f"type={_q(d.type[0])}")
            else:
                args.append(f"type=({', '.join(_q(t) for t in d.type)})")
        if d.when:
            args.append(f"when={_q(d.when)}")
        line = f"depends_on({', '.join(args)})"
        if d.comment:
            line += f"  # {d.comment}"
        lines.append(line)
    return lines


# -------------------------------------------------------------------------- methods


def _method(signature: str, body: list[str], decorator: str | None = None) -> str:
    """A method at class indentation; body lines may carry their own extra indent."""
    lines = [f"    {decorator}"] if decorator else []
    lines.append(f"    def {signature}:")
    lines += [f"        {line}" if line else "" for line in body]
    return "\n".join(lines)


def _methods(recipe: PackageRecipe) -> list[str]:
    system = recipe.build_system
    if system == BuildSystem.CMAKE:
        return [_cmake_args(recipe)]
    if system == BuildSystem.AUTOTOOLS:
        return [_configure_args(recipe)]
    if system == BuildSystem.MESON:
        return [_meson_args(recipe)]
    if system == BuildSystem.MAKEFILE:
        return _makefile_methods(recipe)
    if system == BuildSystem.UNKNOWN:
        return [_method("install(self, spec, prefix)", [
            "# FIXME: Unknown build system. Replace with the real build and install steps.",
            "make()",
            'make("install")',
        ])]
    return []


def _arg_block(name: str, lines: list[str]) -> str:
    return _method(f"{name}(self)", ["args = []", *(lines or ["# FIXME: add args"]), "return args"])


def _cmake_args(recipe: PackageRecipe) -> str:
    lines = [
        f"args.append(self.define_from_variant({_q(v.build_flag)}, {_q(v.name)}))"
        for v in recipe.variants if v.flag_kind == "cmake" and v.build_flag
    ]
    lines += [f"args.append({expr})" for expr in recipe.extra_build_args]
    return _arg_block("cmake_args", lines)


def _configure_args(recipe: PackageRecipe) -> str:
    gated = {d.when.lstrip("+") for d in recipe.dependencies if d.when and d.when.startswith("+")}
    lines = []
    for v in recipe.variants:
        if v.flag_kind not in ("enable", "with") or not v.build_flag:
            continue
        flag = v.build_flag
        if flag == v.name:
            if v.flag_kind == "with" and v.name in gated:
                lines.append(
                    f'args.extend(self.with_or_without({_q(v.name)}, activation_value="prefix"))'
                )
            else:
                helper = "enable_or_disable" if v.flag_kind == "enable" else "with_or_without"
                lines.append(f"args.extend(self.{helper}({_q(v.name)}))")
        else:
            on, off = ("enable", "disable") if v.flag_kind == "enable" else ("with", "without")
            lines.append(
                f'args.append("--{on}-{flag}" if self.spec.satisfies({_q("+" + v.name)}) '
                f'else "--{off}-{flag}")'
            )
    lines += [f"args.append({expr})" for expr in recipe.extra_build_args]
    return _arg_block("configure_args", lines)


def _meson_args(recipe: PackageRecipe) -> str:
    lines = []
    for v in recipe.variants:
        if not v.build_flag or v.flag_kind not in ("meson", "meson_feature"):
            continue
        on, off = ("enabled", "disabled") if v.flag_kind == "meson_feature" else ("true", "false")
        lines.append(
            f'args.append("-D{v.build_flag}=" + ("{on}" if self.spec.satisfies({_q("+" + v.name)}) '
            f'else "{off}"))'
        )
    lines += [f"args.append({expr})" for expr in recipe.extra_build_args]
    return _arg_block("meson_args", lines)


def _makefile_methods(recipe: PackageRecipe) -> list[str]:
    methods = []
    if recipe.make_variables:
        filters = [
            f'makefile.filter(r"^\\s*{var}\\s*[:?]?=.*", f"{var} = {{{expr}}}")'
            for var, expr in recipe.make_variables.items()
        ]
        methods.append(_method("edit(self, spec, prefix)",
                               ['makefile = FileFilter("Makefile")', *filters]))
    else:
        methods.append(_method("edit(self, spec, prefix)", [
            "# FIXME: inject Spack's compilers and the install prefix into the Makefile.",
            'makefile = FileFilter("Makefile")',
            'makefile.filter(r"^\\s*CC\\s*[:?]?=.*", f"CC = {spack_cc}")',
        ]))

    flags = [v for v in recipe.variants if v.flag_kind == "make_var" and v.build_flag]
    if flags:
        body = ["targets = []"]
        for v in flags:
            body += [f"if self.spec.satisfies({_q('+' + v.name)}):",
                     f'    targets.append("{v.build_flag}=1")']
        body.append("return targets")
        methods.append(_method("build_targets(self)", body, decorator="@property"))

    if recipe.has_install_target is False:
        methods.append(_method("install(self, spec, prefix)", [
            "# FIXME: no install target upstream; copy the build products into prefix.",
            "mkdirp(prefix.bin)",
            'install("FIXME-executable", prefix.bin)',
        ]))
    elif "prefix" not in recipe.make_variables.values():
        methods.append(_method("install(self, spec, prefix)", [
            "# FIXME: confirm how the Makefile chooses its install location.",
            'make("install", f"PREFIX={prefix}")',
        ]))
    return methods


# -------------------------------------------------------------------------- repository


def repo_root(workspace: Path, namespace: str, repo_api_v2: bool) -> Path:
    """Directory holding repo.yaml for the session's local package repository."""
    base = workspace / "repo"
    return base / "spack_repo" / namespace if repo_api_v2 else base


def write_recipe(
    source: str, package: str, workspace: Path, namespace: str, repo_api_v2: bool
) -> Path:
    root = repo_root(workspace, namespace, repo_api_v2)
    package_dir = root / "packages" / package_dir_name(package, repo_api_v2)
    package_dir.mkdir(parents=True, exist_ok=True)
    repo_yaml = root / "repo.yaml"
    if not repo_yaml.exists():
        repo = {"namespace": namespace, **({"api": "v2.0"} if repo_api_v2 else {})}
        repo_yaml.write_text(yaml.safe_dump({"repo": repo}, sort_keys=False))
    path = package_dir / "package.py"
    path.write_text(source)
    return path
