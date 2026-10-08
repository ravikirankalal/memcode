"""Python symbol-level anchors (stdlib `ast`): a memory about an edit can be tied to the function or
method that was edited, so it goes stale only when THAT symbol changes, not on any edit to the file.

Hashes are over the AST, so comments and formatting do not count; docstring and code changes do.
Files that do not parse (or are not Python) simply have no symbol anchor and fall back to the file hash.
"""
from __future__ import annotations

import ast
import hashlib


def _walk(body, prefix: str, out: dict[str, tuple[str, int, int]]) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{node.name}"
            h = hashlib.sha1(ast.dump(node, include_attributes=False).encode()).hexdigest()
            out[name] = (h, node.lineno, node.end_lineno or node.lineno)
            if isinstance(node, ast.ClassDef):
                _walk(node.body, f"{name}.", out)


def python_symbols(source: str) -> dict[str, tuple[str, int, int]] | None:
    """qualified name -> (ast hash, first line, last line); None if the source does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    out: dict[str, tuple[str, int, int]] = {}
    _walk(tree.body, "", out)
    return out


def symbol_for_snippet(source: str, snippet: str) -> tuple[str, str] | None:
    """(qualified name, hash) of the innermost function/method containing `snippet`'s first
    non-blank line in `source`; None when it cannot be located or lies outside any symbol."""
    snippet = (snippet or "").strip("\n")
    if not snippet.strip():
        return None
    syms = python_symbols(source)
    if not syms:
        return None
    first = next(ln for ln in snippet.splitlines() if ln.strip())
    idx = source.find(snippet)
    if idx != -1:
        line = source.count("\n", 0, idx + snippet.index(first)) + 1
    else:
        hits = [i for i, ln in enumerate(source.splitlines(), 1) if ln.strip() == first.strip()]
        if len(hits) != 1:          # absent or ambiguous: do not guess
            return None
        line = hits[0]
    best = None
    for name, (h, lo, hi) in syms.items():
        if lo <= line <= hi and (best is None or hi - lo < best[2] - best[1]):
            best = (name, lo, hi, h)
    return (best[0], best[3]) if best else None


def current_symbol_hash(source: str, name: str) -> str | None:
    """Hash of `name` in `source`; None if the symbol is gone. Raises ValueError if unparseable."""
    syms = python_symbols(source)
    if syms is None:
        raise ValueError("unparseable")
    got = syms.get(name)
    return got[0] if got else None
