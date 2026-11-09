"""Let the agent look at (and fetch) the source it is packaging."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillError
from spack_ai.skills.build_analysis.base import SKIP_DIRS

MAX_READ_BYTES = 400_000


class TreeInput(BaseModel):
    path: str | None = Field(default=None, description="Directory; defaults to the source root.")
    depth: int = Field(default=3, ge=1, le=8)
    max_entries: int = Field(default=300, ge=10, le=2000)


@register
class ListSourceTree(Skill):
    name = "list_source_tree"
    category = "inspection"
    description = (
        "List a source directory as a tree (vendored and build directories are shown but not "
        "expanded). Use it to find build files, bundled dependencies, and docs."
    )
    Input = TreeInput

    def run(self, params: TreeInput) -> SkillResult:
        root = self.ctx.resolve_source(params.path or self.ctx.state.get("source_root") or ".")
        if not root.is_dir():
            raise SkillError(f"{root} is not a directory")
        lines: list[str] = [f"{root}/"]
        truncated = False

        def walk(directory: Path, prefix: str, depth: int) -> None:
            nonlocal truncated
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if len(lines) >= params.max_entries:
                    truncated = True
                    return
                if entry.name.startswith(".") and entry.name not in (".gitmodules",):
                    continue
                if entry.is_dir():
                    skipped = entry.name in SKIP_DIRS
                    lines.append(f"{prefix}{entry.name}/" + ("  [not expanded]" if skipped else ""))
                    if not skipped and depth < params.depth:
                        walk(entry, prefix + "  ", depth + 1)
                else:
                    lines.append(f"{prefix}{entry.name}")

        walk(root, "  ", 1)
        if truncated:
            lines.append(f"... truncated at {params.max_entries} entries")
        return SkillResult(summary=f"{len(lines) - 1} entries under {root}", data="\n".join(lines))


class ReadInput(BaseModel):
    path: str = Field(description="File to read, absolute or relative to the source root.")
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=400, ge=1, le=4000)


@register
class ReadSourceFile(Skill):
    name = "read_source_file"
    category = "inspection"
    description = (
        "Read a text file from the source tree (or the session workspace) with line numbers. "
        "Page through long files with start_line."
    )
    Input = ReadInput

    def run(self, params: ReadInput) -> SkillResult:
        path = self.ctx.resolve_source(params.path)
        if not path.is_file():
            raise SkillError(f"{path} is not a file")
        raw = path.read_bytes()[:MAX_READ_BYTES]
        if b"\0" in raw[:8192]:
            raise SkillError(f"{path} looks binary")
        lines = raw.decode(errors="replace").splitlines()
        start = params.start_line - 1
        window = lines[start : start + params.max_lines]
        body = "\n".join(f"{i:>6}  {line}" for i, line in enumerate(window, params.start_line))
        end = start + len(window)
        more = f" (file has {len(lines)} lines; continue at {end + 1})" if end < len(lines) else ""
        return SkillResult(summary=f"{path.name} lines {params.start_line}-{end}{more}", data=body)


class FetchInput(BaseModel):
    url: str = Field(description="Release tarball/zip URL, or a git repository URL.")
    ref: str | None = Field(default=None, description="Git branch or tag to check out.")


@register
class FetchSource(Skill):
    name = "fetch_source"
    category = "inspection"
    requires_confirmation = True
    description = (
        "Download a release archive (computing its sha256 for version()) or shallow-clone a "
        "git repository into the session workspace so it can be analyzed. Needs network access."
    )
    Input = FetchInput

    def confirmation_prompt(self, params: FetchInput) -> str:
        ref = f" @ {params.ref}" if params.ref else ""
        return f"Download {params.url}{ref} into the workspace?"

    def run(self, params: FetchInput) -> SkillResult:
        sources = self.ctx.resolve_output("sources")
        sources.mkdir(exist_ok=True)
        if _is_git(params.url):
            name = re.sub(r"\.git$", "", params.url.rstrip("/").rsplit("/", 1)[-1])
            dest = sources / name
            if dest.exists():
                shutil.rmtree(dest)
            branch = ["--branch", params.ref] if params.ref else []
            cmd = ["git", "clone", "--depth", "1", *branch, params.url, str(dest)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode:
                raise SkillError(f"git clone failed: {proc.stderr[-2000:]}")
            commit = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
            self._register(dest)
            return SkillResult(
                summary=f"Cloned into {self.ctx.relative(dest)} at {commit[:12]}.",
                data={"source_root": str(dest), "commit": commit, "git": params.url},
            )

        filename = Path(urllib.parse.urlparse(params.url).path).name or "download"
        archive = self.ctx.resolve_output(f"downloads/{filename}")
        with urllib.request.urlopen(params.url, timeout=300) as response, archive.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        dest = sources / re.sub(r"(\.tar)?\.(gz|bz2|xz|tgz|zip|zst)$", "", filename)
        if dest.exists():
            shutil.rmtree(dest)
        _extract(archive, dest)
        children = [p for p in dest.iterdir() if not p.name.startswith(".")]
        root = children[0] if len(children) == 1 and children[0].is_dir() else dest
        self._register(root)
        version = re.search(r"(\d+(?:\.\d+)+)", filename)
        return SkillResult(
            summary=f"Downloaded {filename} (sha256 {sha256[:12]}...) and extracted to "
            f"{self.ctx.relative(root)}.",
            data={
                "source_root": str(root),
                "sha256": sha256,
                "url": params.url,
                "suggested_version": (
                    f'version("{version.group(1)}", sha256="{sha256}")' if version else None
                ),
            },
        )

    def _register(self, root: Path) -> None:
        self.ctx.allow_root(root)
        self.ctx.state["source_root"] = str(root)


def _is_git(url: str) -> bool:
    return url.endswith(".git") or url.startswith("git@") or (
        re.match(r"https?://(github\.com|gitlab\.com|bitbucket\.org)/[^/]+/[^/]+/?$", url)
        is not None
    )


def _extract(archive: Path, dest: Path) -> None:
    """Extract without letting members escape `dest` (absolute paths, '..', links)."""
    dest.mkdir(parents=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                target = (dest / member).resolve()
                if dest.resolve() not in target.parents and target != dest.resolve():
                    raise SkillError(f"unsafe path in archive: {member}")
            zf.extractall(dest)
        return
    if not hasattr(tarfile, "data_filter"):
        raise SkillError("Safe tar extraction needs Python 3.11.4 or newer.")
    with tarfile.open(archive) as tf:
        tf.extractall(dest, filter="data")
