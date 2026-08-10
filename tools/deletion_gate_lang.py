#!/usr/bin/env python3
"""deletion_gate_lang.py — language registry and top-level-definition
extraction for tools/deletion_gate.py.

Split out of deletion_gate.py (coding-standards.md S4.1): this half is pure
text parsing (no git, no I/O, no policy) — detect a file's language, then
find every TOP-LEVEL function/class/etc. and its source-text body. The
policy half (what counts as "removed", when that requires a reason) stays
in deletion_gate.py and imports this module.

Adding a language is adding ONE row to LANG_REGISTRY (coding-standards.md
S1.2 Open/Closed) — never editing extract_definitions' dispatch.
"""
from __future__ import annotations

import re

# --- Language registry (S1.2 Open/Closed: add a language by adding a row) ---
# family "indent": block ends when a later non-blank line's indent <= the
#   definition line's indent (Python).
# family "brace": block ends at the matching '}' (or a bare ';' before any
#   '{', for a one-line brace-less statement) (JS/TS, Rust, shell).
LANG_REGISTRY = {
    "python": {
        "exts": {".py"},
        "family": "indent",
        "patterns": [
            (re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("), "function"),
            (re.compile(r"^class\s+([A-Za-z_]\w*)\s*[:\(]"), "class"),
        ],
    },
    "javascript": {
        "exts": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
        "family": "brace",
        "patterns": [
            (re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\("), "function"),
            (re.compile(r"^export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
            (re.compile(r"^export\s+const\s+([A-Za-z_$][\w$]*)\s*="), "const"),
        ],
    },
    "rust": {
        "exts": {".rs"},
        "family": "brace",
        "patterns": [
            (re.compile(r"^pub\s+fn\s+([A-Za-z_]\w*)"), "function"),
            (re.compile(r"^pub\s+struct\s+([A-Za-z_]\w*)"), "struct"),
            (re.compile(r"^pub\s+enum\s+([A-Za-z_]\w*)"), "enum"),
        ],
    },
    "shell": {
        "exts": {".sh", ".bash"},
        "family": "brace",
        "patterns": [
            (re.compile(r"^([A-Za-z_]\w*)\s*\(\)\s*\{"), "function"),
            (re.compile(r"^function\s+([A-Za-z_]\w*)\s*(?:\(\))?\s*\{"), "function"),
        ],
    },
}


def detect_lang(path: str) -> str | None:
    for lang, spec in LANG_REGISTRY.items():
        for ext in spec["exts"]:
            if path.endswith(ext):
                return lang
    return None


def _indent_block_end(lines: list, start: int) -> int:
    base_indent = len(lines[start]) - len(lines[start].lstrip(" \t"))
    last = start
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= base_indent:
            break
        last = j
    return last


def _line_brace_delta(line: str, depth: int, found_open: bool) -> tuple:
    """Scan one line's brace/quote structure. Returns (depth, found_open,
    closed) — closed is True the instant depth returns to <=0 after having
    opened at least once. Split out of _brace_block_end so the character
    scan (quote-skip while, inside a brace if, inside the line while) does
    not nest a 4th level inside that function's own per-line for loop
    (coding-standards.md S4.5)."""
    k = 0
    while k < len(line):
        c = line[k]
        if c in ("'", '"'):
            quote = c
            k += 1
            while k < len(line) and line[k] != quote:
                k += 2 if line[k] == "\\" else 1
        elif c == "{":
            depth += 1
            found_open = True
        elif c == "}":
            depth -= 1
            if found_open and depth <= 0:
                return depth, found_open, True
        k += 1
    return depth, found_open, False


def _brace_block_end(lines: list, start: int) -> int:
    depth, found_open = 0, False
    for j in range(start, len(lines)):
        depth, found_open, closed = _line_brace_delta(lines[j], depth, found_open)
        if closed:
            return j
        if not found_open and lines[j].rstrip().endswith(";"):
            return j
    # Unterminated brace block: fail closed by bounding at EOF rather than
    # silently truncating — the caller still sees a (possibly ragged) body,
    # never a skipped definition.
    return len(lines) - 1


def extract_definitions(text: str, lang: str) -> dict:
    """name -> (kind, body) for every TOP-LEVEL definition in text."""
    spec = LANG_REGISTRY[lang]
    lines = text.splitlines()
    defs: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        hit = None
        for regex, kind in spec["patterns"]:
            m = regex.match(line)
            if m:
                hit = (m.group(1), kind)
                break
        if hit is None:
            i += 1
            continue
        name, kind = hit
        end = (
            _indent_block_end(lines, i)
            if spec["family"] == "indent"
            else _brace_block_end(lines, i)
        )
        defs[name] = (kind, "\n".join(lines[i : end + 1]))
        i = end + 1
    return defs
