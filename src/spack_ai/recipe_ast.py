"""Static introspection of package.py files (no Spack import required).

Used by validation, the evals, and the ML data collectors to compare recipes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

DIRECTIVES = {
    "version", "variant", "depends_on", "conflicts", "provides", "patch",
    "maintainers", "license", "requires", "extends", "resource",
}


@dataclass
class DirectiveCall:
    name: str
    args: list[str]
    kwargs: dict[str, str]
    line: int


@dataclass
class RecipeSummary:
    class_name: str | None = None
    base_classes: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    directives: list[DirectiveCall] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    fixmes: list[int] = field(default_factory=list)
    syntax_error: str | None = None

    def calls(self, name: str) -> list[DirectiveCall]:
        return [d for d in self.directives if d.name == name]

    @property
    def versions(self) -> list[str]:
        return [d.args[0] for d in self.calls("version") if d.args]

    @property
    def variants(self) -> list[str]:
        return [d.args[0] for d in self.calls("variant") if d.args]

    @property
    def dependency_names(self) -> set[str]:
        """Bare package names from depends_on(), e.g. 'hdf5+mpi@1.10:' -> 'hdf5'."""
        names = set()
        for call in self.calls("depends_on"):
            if call.args:
                names.add(spec_name(call.args[0]))
        return names


def spec_name(spec: str) -> str:
    for i, ch in enumerate(spec):
        if ch in "@+~%^ =":
            return spec[:i]
    return spec


def _literal(node: ast.AST) -> str:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return ast.unparse(node)
    if isinstance(value, (tuple, list)):
        return ",".join(str(v) for v in value)
    return str(value)


def summarize(source: str) -> RecipeSummary:
    summary = RecipeSummary(
        fixmes=[i for i, line in enumerate(source.splitlines(), 1) if "FIXME" in line]
    )
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        summary.syntax_error = f"line {exc.lineno}: {exc.msg}"
        return summary

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if not classes:
        return summary
    cls = classes[-1]
    summary.class_name = cls.name
    summary.base_classes = [ast.unparse(b) for b in cls.bases]

    for node in cls.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                summary.attributes[target.id] = _literal(node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            summary.methods.append(node.name)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            _collect_directive(node.value, summary)
        elif isinstance(node, (ast.With, ast.If)):
            # `with when("+mpi"):` blocks and conditional directives.
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    _collect_directive(inner, summary)
    return summary


def _collect_directive(call: ast.Call, summary: RecipeSummary) -> None:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else None
    if name not in DIRECTIVES:
        return
    summary.directives.append(
        DirectiveCall(
            name=name,
            args=[_literal(a) for a in call.args],
            kwargs={kw.arg: _literal(kw.value) for kw in call.keywords if kw.arg},
            line=call.lineno,
        )
    )
