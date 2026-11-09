"""Thin, policy-aware wrapper around the `spack` executable.

Every Spack invocation in the project goes through here so that one place decides
which commands are safe to run unattended. Commands are passed as argument lists
and never through a shell.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Subcommands that only inspect state (they may hit the network to list versions).
READ_ONLY = {
    "arch", "audit", "blame", "checksum", "dependencies", "dependents", "find", "graph",
    "help", "info", "list", "location", "maintainers", "providers", "resource", "spec",
    "style", "url", "versions", "--version",
}
# Subcommands whose read-only-ness depends on the next word.
READ_ONLY_PAIRS = {
    ("compiler", "list"), ("compiler", "info"), ("compilers", None),
    ("config", "get"), ("config", "blame"), ("env", "list"), ("env", "status"),
    ("external", "list"), ("mirror", "list"), ("repo", "list"), ("module", "list"),
    ("debug", "report"),
}
# Global flags that take a value and come before the subcommand.
_GLOBAL_FLAGS_WITH_VALUE = {"-e", "--env", "-D", "--env-dir", "-C", "--config-scope", "-c"}


@dataclass
class SpackResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SpackUnavailable(RuntimeError):
    pass


def subcommand(args: list[str]) -> tuple[str | None, str | None]:
    """Return (subcommand, next word) after skipping Spack's global flags."""
    words: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in _GLOBAL_FLAGS_WITH_VALUE:
            skip = True
            continue
        if arg.startswith("-") and arg != "--version":
            continue
        words.append(arg)
        if len(words) == 2:
            break
    if not words:
        return None, None
    return words[0], (words[1] if len(words) > 1 else None)


def is_read_only(args: list[str]) -> bool:
    cmd, sub = subcommand(args)
    if cmd is None:
        return False
    return cmd in READ_ONLY or (cmd, sub) in READ_ONLY_PAIRS or (cmd, None) in READ_ONLY_PAIRS


class SpackRunner:
    def __init__(self, executable: str | None = None, timeout: int = 900):
        self.executable = executable or shutil.which("spack")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable) and Path(self.executable).exists()

    def run(self, args: list[str], cwd: Path | None = None) -> SpackResult:
        if not self.available:
            raise SpackUnavailable(
                "spack executable not found. Set spack.executable in the config or $SPACK_ROOT."
            )
        proc = subprocess.run(
            [self.executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return SpackResult(args, proc.returncode, proc.stdout, proc.stderr)
