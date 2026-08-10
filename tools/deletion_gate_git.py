#!/usr/bin/env python3
"""deletion_gate_git.py — git I/O primitives for tools/deletion_gate.py.

Split out of deletion_gate.py (coding-standards.md S4.1, S4.4): this half
reads git state — a file at a ref, the staged index, or the actual on-disk
working tree; a diff between two of those; a grep for survivors — and turns
it into Definition objects. It makes no BLOCK/PASS decision; that policy
stays in deletion_gate.py, which imports this module.

`mode` replaces the earlier separate `staged: bool` / `worktree: bool`
parameters threaded through every function here (coding-standards.md S4.4:
"more than 4 parameters is a missing data type" — two mutually-exclusive
booleans ARE a missing enum). Values: None (or "ref") compares two named
refs; MODE_STAGED compares HEAD to the index; MODE_WORKTREE compares HEAD to
the real on-disk tree, which is what lets a PostToolUse hook see a removal
that arrived via `sed`/`rm`/`git rm`/a patch — none of which necessarily
ever touch the index, so MODE_STAGED alone would miss them.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from deletion_gate_lang import LANG_REGISTRY, detect_lang, extract_definitions

MODE_STAGED = "staged"
MODE_WORKTREE = "worktree"


@dataclass
class Definition:
    file: str
    name: str
    kind: str
    body: str
    lang: str = ""


class GitError(RuntimeError):
    pass


def require_pcre(repo: str) -> None:
    """Fail closed, loudly, if this git build lacks PCRE (-P) support —
    silently degrading to -E would mean \\b/\\s compile but match nothing
    (see find_survivors), which is exactly the failure mode this gate
    exists to close: a check that looks like it ran and did not."""
    proc = subprocess.run(
        ["git", "-C", repo, "grep", "-I", "-P", "-q", r"\bx\b", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode == 128 or "not supported" in proc.stderr.lower():
        raise GitError(
            "git grep -P (PCRE) is not supported by this git build — "
            "the survivor search cannot run correctly (\\b/\\s are silently "
            "inert under -E). Install a PCRE-enabled git."
        )


def run_git(repo: str, args: list) -> str:
    proc = subprocess.run(
        ["git", "-C", repo] + args, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def show_file(repo: str, ref: str, path: str) -> str | None:
    """Content of path at ref, or None if it does not exist there."""
    proc = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:{path}"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def changed_paths(repo: str, base: str, head: str, mode: str | None = None) -> list:
    """[(status, old_path, new_path)] between base and head, or the index
    (MODE_STAGED), or the actual on-disk working tree (MODE_WORKTREE)."""
    args = ["diff", "--name-status", "-M"]
    if mode == MODE_WORKTREE:
        args += [base]  # working tree vs base (HEAD), no --cached: staged
        # AND unstaged changes both count — that is the whole point of this
        # mode over MODE_STAGED.
    elif mode == MODE_STAGED:
        args += ["--cached"]
    else:
        args += [f"{base}..{head}"]
    out = run_git(repo, args)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            rows.append((status, parts[1], parts[2]))
        else:
            rows.append((status, parts[1], parts[1]))
    return rows


def show_index(repo: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", repo, "show", f":{path}"],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def read_worktree_file(repo: str, path: str) -> str | None:
    """The actual on-disk content, not any git-tracked snapshot — this is
    what makes MODE_WORKTREE see a `sed -i` or a raw `rm` that never
    touched the index."""
    full = Path(repo) / path
    try:
        return full.read_text(encoding="utf-8", errors="replace") if full.exists() else None
    except OSError:
        return None


def post_content(repo: str, head: str, path: str, mode: str | None = None) -> str | None:
    if mode == MODE_WORKTREE:
        return read_worktree_file(repo, path)
    if mode == MODE_STAGED:
        return show_index(repo, path)
    return show_file(repo, head, path)


def collect_definitions(repo: str, base: str, head: str, mode: str | None = None):
    """Return (removed: list[Definition], added: list[Definition])."""
    removed, added = [], []
    for status, old_path, new_path in changed_paths(repo, base, head, mode):
        # A wholly new file cannot have REMOVED a definition, but it can be
        # half of an undetected rename (git's -M similarity heuristic misses
        # small files where most lines changed, e.g. a 4-line function whose
        # only identifier was renamed) — so its ADDED definitions still feed
        # find_rename_match. Do not skip it outright; just skip the removed
        # side, which is already correct because pre_text is None for "A".
        lang_old = detect_lang(old_path)
        lang_new = detect_lang(new_path)
        pre_text = show_file(repo, base, old_path) if status != "A" else None
        post_text = None if status == "D" else post_content(repo, head, new_path, mode)

        pre_defs = extract_definitions(pre_text, lang_old) if pre_text and lang_old else {}
        post_defs = extract_definitions(post_text, lang_new) if post_text and lang_new else {}

        for name, (kind, body) in pre_defs.items():
            if name not in post_defs:
                removed.append(Definition(old_path, name, kind, body, lang_old))
        for name, (kind, body) in post_defs.items():
            if name not in pre_defs:
                added.append(Definition(new_path, name, kind, body, lang_new))
    return removed, added


# Paths a definition removal is exempt from (a test naming no production
# caller is the point of a test, not the incident this gate guards against).
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__)(/|$)"
    r"|(^|/)test_[^/]+\.(py|sh)$"
    r"|(^|/)test-[^/]+\.sh$"
    r"|_test\.(py|go|rs)$"
    r"|\.test\.(js|ts|tsx|jsx)$"
    r"|\.spec\.(js|ts|tsx|jsx)$"
)


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path))


def _line_path(line: str, ref: str | None) -> str:
    """The path field of a `git grep` output line, stripping the optional
    leading `<ref>:` that only appears when a ref (not the working tree or
    the index) was searched."""
    prefix = f"{ref}:" if ref else ""
    body = line[len(prefix):] if prefix and line.startswith(prefix) else line
    return body.split(":", 1)[0]


def find_survivors(
    repo: str, ref: str | None, mode: str | None, name: str, lang: str,
    exclude_paths: set | None = None,
) -> list:
    """Lines that call, attribute-access, or import `name`, in the tree named
    by (ref, mode): a commit ref, the staged index (MODE_STAGED), or —
    MODE_WORKTREE, or ref=None with no mode — the working tree as it stands
    right now (the shape a PreToolUse hook needs: the edit has not landed
    yet). Restricted to call/attribute/import shapes (not any textual
    occurrence) so a common English word does not over-block, and to the
    removed definition's own language's file extensions (not docs, not
    CHANGELOGs, not another language's identically-spelled identifier) —
    the precision/recall tradeoff, see module docstring point 1.

    `exclude_paths`, when given, drops matches in those files. Two distinct
    callers rely on this for two distinct reasons:
      - the edit-time hook excludes the file being edited: its pre-image
        still holds the OLD body on disk, so a definition calling itself
        would otherwise survivor-match against text about to vanish in the
        very same edit.
      - evaluate() excludes every file the CURRENT DIFF already touches: a
        caller inside a file this same diff modified or added is evidence
        the author already accounted for the move (see module docstring's
        incident quote, "in files that commit's own diff never touched" —
        that qualifier is the whole reason a real caller went unnoticed).
        Only a survivor in a file the diff left alone is the danger this
        gate exists to catch.
    """
    pattern = (
        rf"\b{re.escape(name)}\s*\("
        rf"|\.{re.escape(name)}\b"
        rf"|\bimport\s+{re.escape(name)}\b"
        rf"|\bfrom\s+\S+\s+import\s+[^#\n]*\b{re.escape(name)}\b"
    )
    if lang == "shell":
        # Shell invokes a function as a bare command word, never `name(`
        # (that syntax defines a function, it does not call one) — a caller
        # like `emit_event "hello"` matches none of the call/attr/import
        # shapes above and would silently read as "no survivors". Anchored
        # to line-start (with optional leading whitespace) so it does not
        # also match `name` appearing mid-argument-list elsewhere.
        pattern += rf"|^\s*{re.escape(name)}\b"
    # -P (PCRE), not -E: git's -E is the platform's POSIX ERE, which on
    # macOS/BSD git builds does not support \b or \s — they compile silently
    # and match nothing rather than erroring, which would have made this
    # gate silently pass on the exact incident it exists to catch. Verified
    # against Apple Git 2.50.1: -E returns 0 matches for '\.emit\b', -P finds
    # the callers. Requires git built with PCRE (checked once at gate start).
    # --cached is a search-mode OPTION and must precede the pattern; a <rev>
    # is a positional argument and must follow it. Putting --cached after the
    # pattern makes git try to resolve it as a revision and fail closed with
    # "unable to resolve revision: --cached" — verified against Apple Git
    # 2.50.1 while building this gate's own test suite.
    staged = mode == MODE_STAGED
    args = ["grep", "-n", "-I", "-P"]
    if staged:
        args += ["--cached"]
    args += [pattern]
    if not staged and mode != MODE_WORKTREE and ref:
        args += [ref]
    # else: no ref argument -> git grep's default target, the working tree.
    exts = LANG_REGISTRY.get(lang, {}).get("exts")
    if exts:
        args += ["--"] + [f"*{ext}" for ext in sorted(exts)]
    proc = subprocess.run(
        ["git", "-C", repo] + args, capture_output=True, text=True, check=False
    )
    if proc.returncode not in (0, 1):
        raise GitError(f"git grep failed (PCRE support required): {proc.stderr.strip()}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if exclude_paths:
        search_ref = ref if not staged and mode != MODE_WORKTREE else None
        lines = [line for line in lines if _line_path(line, search_ref) not in exclude_paths]
    return lines


def commit_message(repo: str, sha: str) -> str:
    return run_git(repo, ["log", "-1", "--format=%B", sha])


def range_messages(repo: str, base: str, head: str) -> str:
    return run_git(repo, ["log", "--format=%B%n---", f"{base}..{head}"])
