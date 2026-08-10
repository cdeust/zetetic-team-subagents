#!/usr/bin/env python3
"""deletion_gate.py — makes "delete it instead of fixing it" mechanically
impossible to merge silently.

Incident (source: cdeust/cortex-viz commit 45d4a80): three module-level
forwarders (emit, close, reset) were removed from graph_event_stream.py,
justified in the code as having "never had a caller in this repository's
history". They had four — in graph_build_run.py and graph_build_merge.py.
The released 3.1.0 could not build a graph. A grep for the removed names
against the post-change tree would have found those callers instantly. That
grep is the whole mechanism this gate automates and makes mandatory.

For every top-level definition (function/class/etc.) removed by a diff:
  1. Search the POST-change tree for surviving references to its name.
     Any survivor -> BLOCK, naming the caller(s). Not arguable.
  2. No survivors, but the same body reappears elsewhere under a different
     name/path (a rename or a move) -> PASS silently. Nobody owes a
     rationale for spelling something differently.
  3. No survivors, no rename match -> the commit message MUST carry a
     `Retired-Because:` trailer, and that trailer must say more than "no
     callers" / "unused" / "dead code" (the OBSERVATION), because the
     observation is not the reason the incident's own commit message shows
     that pattern verbatim, and it produced the outage.

Fails closed: unreadable git state, an unparsable diff hunk, or a removed
definition whose body cannot be bounded is a BLOCK, never a silent skip. A
language absent from LANG_REGISTRY is out of scope (not a parse failure) and
is skipped — extending coverage is one registry entry (coding-standards.md
S1.2 Open/Closed), not a rewrite of the dispatch.

Usage:
  deletion_gate.py --repo <path> --commit <sha> [--message-file <path>]
  deletion_gate.py --repo <path> --base <ref> --head <ref>
  deletion_gate.py --repo <path> --staged --message-file <path>

Exit codes: 0 pass, 1 block (>=1 removed definition failed the gate),
            2 usage/git error.
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field

# Sibling module in the same directory — importable without a sys.path
# change because Python always puts a script's own directory at sys.path[0],
# and every caller (deletion-gate.sh, the CLI, the PreToolUse hook) already
# resolves tools/ before importing this file.
from deletion_gate_lang import LANG_REGISTRY, detect_lang, extract_definitions

EXIT_OK = 0
EXIT_BLOCK = 1
EXIT_USAGE = 2

TRAILER_KEY = "Retired-Because"

# Phrases that restate the OBSERVATION ("nothing calls this") rather than a
# REASON ("the job no longer needs doing, because ..."). Source: the incident
# commit's own justification, quoted verbatim in the module docstring above —
# this is the exact sentence the gate exists to refuse as sufficient.
OBSERVATION_ONLY_PHRASES = (
    "no caller", "no callers", "unused", "dead code", "never called",
    "not referenced", "no references", "not used", "no usages", "no usage",
    "not called", "unreferenced", "no longer used", "not needed",
)

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

RENAME_SIMILARITY_THRESHOLD = 0.90  # source: difflib.SequenceMatcher.ratio()
# docs — 1.0 is an exact match after name-swap; 0.90 tolerates a renamed
# parameter or a reformatted line while rejecting a substantively different
# body. Not paper-derived (no publication defines "same function" for source
# text); calibrated against the fixtures in tools/tests/deletion-gate.


@dataclass
class Definition:
    file: str
    name: str
    kind: str
    body: str
    lang: str = ""


@dataclass
class Finding:
    blocked: bool
    message: str


@dataclass
class GateResult:
    findings: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.blocked for f in self.findings)


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


def changed_paths(repo: str, base: str, head: str, staged: bool) -> list:
    """[(status, old_path, new_path)] between base and head (or the index)."""
    args = ["diff", "--name-status", "-M"]
    args += ["--cached"] if staged else [f"{base}..{head}"]
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


def post_content(repo: str, head: str, staged: bool, path: str) -> str | None:
    return show_index(repo, path) if staged else show_file(repo, head, path)


def collect_definitions(repo: str, base: str, head: str, staged: bool):
    """Return (removed: list[Definition], added: list[Definition])."""
    removed, added = [], []
    for status, old_path, new_path in changed_paths(repo, base, head, staged):
        # A wholly new file cannot have REMOVED a definition, but it can be
        # half of an undetected rename (git's -M similarity heuristic misses
        # small files where most lines changed, e.g. a 4-line function whose
        # only identifier was renamed) — so its ADDED definitions still feed
        # find_rename_match. Do not skip it outright; just skip the removed
        # side, which is already correct because pre_text is None for "A".
        lang_old = detect_lang(old_path)
        lang_new = detect_lang(new_path)
        pre_text = show_file(repo, base, old_path) if status != "A" else None
        post_text = None if status == "D" else post_content(repo, head, staged, new_path)

        pre_defs = extract_definitions(pre_text, lang_old) if pre_text and lang_old else {}
        post_defs = extract_definitions(post_text, lang_new) if post_text and lang_new else {}

        for name, (kind, body) in pre_defs.items():
            if name not in post_defs:
                removed.append(Definition(old_path, name, kind, body, lang_old))
        for name, (kind, body) in post_defs.items():
            if name not in pre_defs:
                added.append(Definition(new_path, name, kind, body, lang_new))
    return removed, added


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
    repo: str, ref: str | None, staged: bool, name: str, lang: str,
    exclude_path: str | None = None,
) -> list:
    """Lines that call, attribute-access, or import `name`, in the tree named
    by (ref, staged): a commit ref, the staged index, or — when ref is None
    and staged is False — the working tree as it stands right now (the shape
    a PreToolUse hook needs: the edit has not landed yet). Restricted to
    call/attribute/import shapes (not any textual occurrence) so a common
    English word does not over-block, and to the removed definition's own
    language's file extensions (not docs, not CHANGELOGs, not another
    language's identically-spelled identifier) — the precision/recall
    tradeoff, see module docstring point 1.

    `exclude_path`, when given, drops matches in that one file — the
    edit-time hook's own pre-image still holds the OLD body on disk, so a
    definition calling itself would otherwise survivor-match against text
    that is about to vanish in the very same edit.
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
    args = ["grep", "-n", "-I", "-P"]
    if staged:
        args += ["--cached"]
    args += [pattern]
    if not staged and ref:
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
    if exclude_path:
        search_ref = ref if not staged else None
        lines = [line for line in lines if _line_path(line, search_ref) != exclude_path]
    return lines


def normalize_body(body: str, name: str) -> str:
    swapped = re.sub(rf"\b{re.escape(name)}\b", "\0NAME\0", body)
    lines = [line.rstrip() for line in swapped.splitlines() if line.strip()]
    return "\n".join(lines)


def find_rename_match(removed: Definition, added: list, consumed: set):
    """The highest-similarity unconsumed added definition, if it clears the
    threshold — this is what tells a rename/move apart from an abandonment."""
    norm_removed = normalize_body(removed.body, removed.name)
    best, best_ratio = None, 0.0
    for idx, cand in enumerate(added):
        if idx in consumed or cand.kind != removed.kind:
            continue
        ratio = difflib.SequenceMatcher(
            None, norm_removed, normalize_body(cand.body, cand.name)
        ).ratio()
        if ratio > best_ratio:
            best, best_ratio = (idx, cand), ratio
    if best and best_ratio >= RENAME_SIMILARITY_THRESHOLD:
        return best[0], best[1], best_ratio
    return None


def extract_trailer(message: str, key: str) -> str | None:
    matches = re.findall(rf"^{re.escape(key)}:\s*(.+)$", message, re.MULTILINE)
    if not matches:
        return None
    return " ".join(m.strip() for m in matches)


def is_substantive(trailer: str) -> bool:
    """Reject a trailer that is only the OBSERVATION dressed as a reason."""
    remainder = trailer.lower()
    for phrase in OBSERVATION_ONLY_PHRASES:
        remainder = remainder.replace(phrase, "")
    letters_only = re.sub(r"[^a-z]", "", remainder)
    return len(letters_only) >= 15


def evaluate(
    repo: str, base: str, head: str, staged: bool, message: str,
    require_trailer: bool = True,
) -> GateResult:
    removed, added = collect_definitions(repo, base, head, staged)
    ref = head
    consumed: set = set()
    result = GateResult()
    for rd in removed:
        label = f"{rd.file}::{rd.name} ({rd.kind})"
        if is_test_path(rd.file):
            result.findings.append(Finding(False, f"SKIP  {label} — test path, exempt"))
            continue

        survivors = find_survivors(repo, ref, staged, rd.name, rd.lang)
        if survivors:
            detail = "; ".join(survivors[:10])
            result.findings.append(
                Finding(True, f"BLOCK {label} — {len(survivors)} surviving reference(s): {detail}")
            )
            continue

        match = find_rename_match(rd, added, consumed)
        if match:
            idx, cand, ratio = match
            consumed.add(idx)
            result.findings.append(
                Finding(False, f"PASS  {label} — matches added {cand.file}::{cand.name} "
                               f"(similarity={ratio:.2f}, treated as rename/move)")
            )
            continue

        trailer = extract_trailer(message, TRAILER_KEY)
        if trailer and is_substantive(trailer):
            result.findings.append(
                Finding(False, f"PASS  {label} — no survivors; {TRAILER_KEY}: {trailer}")
            )
        elif trailer:
            result.findings.append(
                Finding(True, f"BLOCK {label} — {TRAILER_KEY} trailer restates the "
                               f"absence of callers instead of giving a reason: {trailer!r}")
            )
        elif not require_trailer:
            # No commit exists yet to carry a trailer (the staged-diff "net" —
            # a PreToolUse hook only sees one file at a time and this gate also
            # runs on the accumulated staged diff before commit). Deferring
            # here is not a silent pass: the commit/CI-range invocation of
            # this same evaluate() with require_trailer=True is what actually
            # closes the "no survivors, no reason" hole (module docstring
            # point 3) — this path exists so staging a legitimate deletion
            # is never blocked before there is anywhere to put the reason.
            result.findings.append(
                Finding(False, f"PASS  {label} — no survivors; {TRAILER_KEY} required "
                               f"at commit time (not checked pre-commit)")
            )
        else:
            result.findings.append(
                Finding(True, f"BLOCK {label} — no survivors and no {TRAILER_KEY}: "
                               f"trailer in the commit message")
            )
    return result


def commit_message(repo: str, sha: str) -> str:
    return run_git(repo, ["log", "-1", "--format=%B", sha])


def range_messages(repo: str, base: str, head: str) -> str:
    return run_git(repo, ["log", "--format=%B%n---", f"{base}..{head}"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deletion_gate", description=__doc__)
    p.add_argument("--repo", default=".", help="repository to gate")
    p.add_argument("--commit", help="single commit sha to gate (diffs sha^..sha)")
    p.add_argument("--base", help="base ref (range mode)")
    p.add_argument("--head", default="HEAD", help="head ref (range mode)")
    p.add_argument("--staged", action="store_true", help="gate HEAD vs the index")
    p.add_argument("--message-file", help="path to a commit message file")
    return p


def resolve_message(repo: str, args) -> str:
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as fh:
            return fh.read()
    if args.commit:
        return commit_message(repo, args.commit)
    if args.staged:
        return ""
    return range_messages(repo, args.base, args.head)


def main(argv: list) -> int:
    args = build_parser().parse_args(argv)
    if not args.staged and not args.commit and not args.base:
        print("error: one of --commit, --base/--head, or --staged is required", file=sys.stderr)
        return EXIT_USAGE

    if args.commit:
        base, head = f"{args.commit}^", args.commit
    elif args.staged:
        base, head = "HEAD", args.head  # pre-image is the last commit; head is unused
    else:
        base, head = args.base, args.head
    # Staged with no message file: there is no commit yet to carry a
    # Retired-Because: trailer, so this run is the survivors-only "net"
    # (module docstring point 3 is deferred to the commit/CI-range run,
    # which always has a real message and always requires the trailer).
    require_trailer = not (args.staged and not args.message_file)

    try:
        require_pcre(args.repo)
        message = resolve_message(args.repo, args)
        result = evaluate(args.repo, base, head, args.staged, message, require_trailer)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    for finding in result.findings:
        print(finding.message)

    if not result.findings:
        print("deletion-gate: no top-level definitions were removed — pass")
        return EXIT_OK

    if result.blocked:
        print("deletion-gate: BLOCKED — see BLOCK lines above", file=sys.stderr)
        return EXIT_BLOCK
    print("deletion-gate: pass")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
