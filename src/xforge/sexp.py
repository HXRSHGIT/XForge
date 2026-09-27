"""Minimal S-expression reader for KiCad text formats.

Deliberately dependency-free. KiCad's netlist/board grammar is small: atoms,
double-quoted strings with backslash escapes, and parenthesised lists. Keeping
our own reader means the parse never breaks because an upstream library chased
a different KiCad version.
"""

from __future__ import annotations

from typing import Union

SExp = Union[str, list["SExp"]]

_WS = " \t\r\n"


class SExpError(ValueError):
    """Raised when the input is not well-formed."""

    def __init__(self, message: str, pos: int, text: str) -> None:
        line = text.count("\n", 0, pos) + 1
        col = pos - (text.rfind("\n", 0, pos) + 1) + 1
        super().__init__(f"{message} at line {line}, column {col}")
        self.pos = pos
        self.line = line
        self.column = col


def loads(text: str) -> SExp:
    """Parse the first complete S-expression in *text*."""
    value, pos = _parse(text, _skip(text, 0))
    trailing = _skip(text, pos)
    if trailing != len(text):
        raise SExpError("unexpected trailing content", trailing, text)
    return value


def load(path) -> SExp:
    """Parse the S-expression held in the file at *path*."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return loads(handle.read())


def _skip(text: str, pos: int) -> int:
    """Advance past whitespace and ``#`` comments."""
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch in _WS:
            pos += 1
        elif ch == "#":
            newline = text.find("\n", pos)
            pos = n if newline == -1 else newline + 1
        else:
            break
    return pos


def _parse(text: str, pos: int) -> tuple[SExp, int]:
    if pos >= len(text):
        raise SExpError("unexpected end of input", pos, text)
    ch = text[pos]
    if ch == "(":
        return _parse_list(text, pos + 1)
    if ch == ")":
        raise SExpError("unbalanced ')'", pos, text)
    if ch == '"':
        return _parse_string(text, pos + 1)
    return _parse_atom(text, pos)


def _parse_list(text: str, pos: int) -> tuple[list[SExp], int]:
    items: list[SExp] = []
    n = len(text)
    while True:
        pos = _skip(text, pos)
        if pos >= n:
            raise SExpError("unterminated list", pos, text)
        if text[pos] == ")":
            return items, pos + 1
        item, pos = _parse(text, pos)
        items.append(item)


def _parse_string(text: str, pos: int) -> tuple[str, int]:
    out: list[str] = []
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch == "\\":
            if pos + 1 >= n:
                raise SExpError("dangling escape in string", pos, text)
            nxt = text[pos + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            pos += 2
            continue
        if ch == '"':
            return "".join(out), pos + 1
        out.append(ch)
        pos += 1
    raise SExpError("unterminated string", pos, text)


def _parse_atom(text: str, pos: int) -> tuple[str, int]:
    start = pos
    n = len(text)
    while pos < n and text[pos] not in _WS and text[pos] not in "()\"":
        pos += 1
    if pos == start:
        raise SExpError("empty atom", pos, text)
    return text[start:pos], pos


# ── small helpers for walking a parsed tree ──────────────────────────


def head(node: SExp) -> str | None:
    """The leading symbol of a list node, or None for an atom/empty list."""
    if isinstance(node, list) and node and isinstance(node[0], str):
        return node[0]
    return None


def children(node: SExp, name: str):
    """Yield every direct child list of *node* whose head is *name*."""
    if not isinstance(node, list):
        return
    for item in node:
        if isinstance(item, list) and head(item) == name:
            yield item


def child(node: SExp, name: str) -> SExp | None:
    """The first direct child list of *node* with head *name*, if any."""
    for item in children(node, name):
        return item
    return None


def value(node: SExp, name: str, default: str | None = None) -> str | None:
    """The single value of ``(name "value")`` beneath *node*."""
    found = child(node, name)
    if found is None or len(found) < 2 or not isinstance(found[1], str):
        return default
    return found[1]
