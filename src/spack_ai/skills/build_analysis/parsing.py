"""Small, dependency-free scanners for build-system languages (CMake, m4, Meson).

These are deliberately approximate: they find function calls and split their
arguments well enough to recover dependencies, options, and project metadata.
Anything they cannot interpret is left for the model to read directly.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_OPEN = "([{"
_CLOSE = ")]}"


def find_call_end(text: str, start: int, string_quotes: str = '"') -> int:
    """Index just past the ')' that closes a call whose '(' ends at `start`.

    Quotes listed in `string_quotes` delimit strings (parens inside are ignored);
    (), [] and {} nest. Returns len(text) if the call is unterminated.
    """
    depth = 1
    quote: str | None = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in string_quotes:
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def iter_calls(
    text: str, pattern: re.Pattern[str], string_quotes: str = '"', nested: bool = False
) -> Iterator[tuple[str, str, int]]:
    """Yield (name, argument text, 1-based line) for each call matching `pattern`.

    `pattern` must match the name followed by '(' and capture the name in group 1.
    With `nested`, calls inside another call's arguments are yielded too (m4 macros
    inside AS_IF, Meson dependency() inside executable()).
    """
    pos = 0
    while (match := pattern.search(text, pos)) is not None:
        end = find_call_end(text, match.end(), string_quotes)
        line = text.count("\n", 0, match.start()) + 1
        yield match.group(1), text[match.end() : end - 1], line
        pos = match.end() if nested else end


def split_top_level(body: str, sep: str = ",", string_quotes: str = "'\"") -> list[str]:
    """Split on `sep` where not nested in brackets or strings."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\" and i + 1 < len(body):
                current.append(ch)
                i += 1
                ch = body[i]
            elif ch == quote:
                quote = None
        elif ch in string_quotes:
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail or parts:
        parts.append(tail)
    return parts


# ----------------------------------------------------------------------------- CMake

_CMAKE_CALL = re.compile(r"(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CMAKE_ARG = re.compile(r'"((?:[^"\\]|\\.)*)"|(\[=*\[.*?\]=*\])|([^\s()]+|[()])', re.S)


def strip_cmake_comments(text: str) -> str:
    text = re.sub(r"#\[(=*)\[.*?\]\1\]", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        in_quote = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_quote = not in_quote
            elif ch == "#" and not in_quote:
                line = line[:i]
                break
        lines.append(line)
    return "\n".join(lines)


def iter_cmake_commands(text: str) -> Iterator[tuple[str, list[str], int]]:
    """Yield (lower-cased command, arguments, line) for each CMake command."""
    text = strip_cmake_comments(text)
    for name, body, line in iter_calls(text, _CMAKE_CALL, '"'):
        args = []
        for quoted, bracket, bare in _CMAKE_ARG.findall(body):
            args.append(quoted if quoted or not (bracket or bare) else (bracket or bare))
        yield name.lower(), args, line


# ----------------------------------------------------------------------------- m4 / Autoconf

_M4_CALL = re.compile(r"\b((?:AC|AM|AX|ACX|LT|PKG|AS|MPI)_[A-Z0-9_]+)\s*\(")


def strip_m4_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("dnl", "#")):
            continue
        lines.append(re.sub(r"\s+dnl\s.*$", "", line))
    return "\n".join(lines)


def unquote_m4(arg: str) -> str:
    arg = arg.strip()
    while len(arg) >= 2 and arg[0] == "[" and arg[-1] == "]":
        arg = arg[1:-1].strip()
    return arg


_M4_BARE = re.compile(r"\b((?:AC|AM|AX|ACX|LT)_[A-Z0-9_]+)\b(?!\s*\()")


def iter_m4_macros(text: str) -> Iterator[tuple[str, list[str], int]]:
    """Yield (macro, arguments, line), including nested and argument-less macros
    (AC_PROG_CXX and LT_INIT are usually written without parentheses)."""
    text = strip_m4_comments(text)
    found = []
    for name, body, line in iter_calls(text, _M4_CALL, "", nested=True):
        found.append((line, name, [unquote_m4(a) for a in split_top_level(body, ",", "")]))
    for match in _M4_BARE.finditer(text):
        found.append((text.count("\n", 0, match.start()) + 1, match.group(1), []))
    for line, name, args in sorted(found, key=lambda item: item[0]):
        yield name, args, line


# ----------------------------------------------------------------------------- Meson

_MESON_CALL = re.compile(r"(?<![\w.])([a-z_][a-z0-9_]*)\s*\(")


def strip_meson_comments(text: str) -> str:
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def iter_meson_calls(text: str) -> Iterator[tuple[str, list[str], dict[str, str], int]]:
    """Yield (name, positional args, keyword args, line) for Meson function calls."""
    text = strip_meson_comments(text)
    for name, body, line in iter_calls(text, _MESON_CALL, "'", nested=True):
        positional: list[str] = []
        keywords: dict[str, str] = {}
        for part in split_top_level(body, ",", "'"):
            if not part:
                continue
            kw = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*(.*)$", part, re.S)
            if kw:
                keywords[kw.group(1)] = kw.group(2).strip()
            else:
                positional.append(part)
        yield name, positional, keywords, line


def meson_string(value: str) -> str | None:
    match = re.fullmatch(r"\s*'((?:[^'\\]|\\.)*)'\s*", value)
    return match.group(1) if match else None


def meson_strings(value: str) -> list[str]:
    """All string literals in a value: 'c' -> ['c'], ['c', 'cpp'] -> ['c', 'cpp']."""
    return re.findall(r"'((?:[^'\\]|\\.)*)'", value)
