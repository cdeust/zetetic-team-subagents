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

Two refinements found by dogfooding this gate against its own commits
(2026-08-10), both self-caught by .githooks/commit-msg before either ever
reached a fixture:

- Rename before survivor. _evaluate_one checks rename/move BEFORE the
  survivor grep, not after. Checking the grep first would BLOCK every
  well-formed move whose new location is still called by its old name
  (every move that keeps working): moving `range_messages` out of this
  file into deletion_gate_git.py, with this file updated to import and
  call it, produced a "survivor" that was really evidence the move was
  done correctly. Rename-match gets first refusal because it positively
  confirms "the same body exists elsewhere", which the grep alone cannot
  tell apart from "an old caller nobody fixed".
- Touched files are exempt from "survivor". A caller inside a file the
  CURRENT DIFF already added or modified is evidence the author saw it and
  kept it consistent, not a dangling reference — the incident's own commit
  message names the opposite shape ("in files that commit's own diff never
  touched") as exactly what let its missing callers go unnoticed. Only a
  survivor in a file the diff left alone blocks (evaluate()'s `touched`
  set, `_touched_files()`).

This is Tier 3 (the commit/CI-range check, and the only tier that can
verify the Retired-Because: trailer — no commit exists yet at Tier 1/2).
Also wired as: hooks/pre-tool-deletion-gate.py (Tier 1, PreToolUse, blocks
an Edit/Write before it lands), hooks/post-tool-deletion-gate.py (Tier 2,
PostToolUse on Edit|Write|Bash, --worktree mode, the net for a removal that
arrives by a path Tier 1 cannot see), and .githooks/pre-commit +
.githooks/commit-msg (this same CLI, run natively for a `git commit` made
outside a Claude Code session).

Usage:
  deletion_gate.py --repo <path> --commit <sha> [--message-file <path>]
  deletion_gate.py --repo <path> --base <ref> --head <ref>
  deletion_gate.py --repo <path> --staged --message-file <path>
  deletion_gate.py --repo <path> --worktree [--message-file <path>]

Exit codes: 0 pass, 1 block (>=1 removed definition failed the gate),
            2 usage/git error.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass, field

# Sibling modules in the same directory — importable without a sys.path
# change because Python always puts a script's own directory at sys.path[0],
# and every caller (deletion-gate.sh, the CLI, both hooks) already resolves
# tools/ before importing this file.
from deletion_gate_git import (
    MODE_STAGED,
    MODE_WORKTREE,
    Definition,
    GitError,
    changed_paths,
    collect_definitions,
    commit_message,
    find_survivors,
    is_test_path,
    range_messages,
    require_pcre,
)

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

RENAME_SIMILARITY_THRESHOLD = 0.90  # source: difflib.SequenceMatcher.ratio()
# docs — 1.0 is an exact match after name-swap; 0.90 tolerates a renamed
# parameter or a reformatted line while rejecting a substantively different
# body. Not paper-derived (no publication defines "same function" for source
# text); calibrated against the fixtures in tools/tests/deletion-gate.


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


@dataclass
class GateRequest:
    """Parameter object for evaluate() (coding-standards.md S4.4: more than
    4 parameters is a missing data type — repo/base/head/message/mode/
    require_trailer are six related facets of ONE request, not six
    independent concerns)."""
    repo: str
    base: str
    head: str
    message: str
    mode: str | None = None  # None="ref", MODE_STAGED, or MODE_WORKTREE
    require_trailer: bool = True


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


### Messages — these are the gate's only interface with the agent reading
# them (Anthropic, "Writing tools for agents": an error response must orient
# the reader toward the corrective action, not just state a failure). Every
# BLOCK message below says, in order: what was removed, who still calls it
# and where (or what is missing), then the two paths forward — repair is
# normal, removal needs its callers migrated first and a real reason last —
# closing with the incident that makes the rule concrete. Centralized here so
# the CLI/CI finding, the PreToolUse hook and the PostToolUse hook show the
# reader the exact same words for the exact same defect (coding-standards.md
# S3.3: one formatter, not three hand-copied paragraphs that drift).

INCIDENT_COUNTEREXAMPLE = (
    "cdeust/cortex-viz commit 45d4a80 removed three forwarders justified as "
    "having \"never had a caller in this repository's history\" — they had "
    "four, in files that commit's own diff never touched, and the released "
    "version could not build a graph."
)

# source: operational default — keeps a single BLOCK message readable in a
# terminal/log; the message states the true total and how to see the rest
# rather than truncating silently.
SURVIVOR_SHOW_LIMIT = 10


def format_survivor_block(label: str, name: str, survivors: list) -> str:
    shown = survivors[:SURVIVOR_SHOW_LIMIT]
    lines = [
        f"BLOCK {label}: removed, but still called from {len(survivors)} "
        f"place(s) — showing {len(shown)} of {len(survivors)}; see the rest "
        f"with: git grep -n -P '\\b{name}\\s*\\(|\\.{name}\\b' -- '*.py' "
        f"'*.ts' '*.rs' '*.sh' (adjust the extension list to the language)."
    ]
    lines += [f"    {s}" for s in shown]
    lines.append(
        "  Normal path: restore or repair the definition so these callers "
        "keep working."
    )
    lines.append(
        "  If removal is genuinely intended: migrate every caller listed "
        "above off it FIRST, in this commit or an earlier one, THEN remove "
        "the definition with a Retired-Because: trailer explaining why the "
        "job no longer needs doing."
    )
    lines.append(f"  {INCIDENT_COUNTEREXAMPLE}")
    return "\n".join(lines)


def format_no_trailer_block(label: str) -> str:
    return (
        f"BLOCK {label}: no surviving caller was found, but the commit "
        f"carries no {TRAILER_KEY}: trailer either. Add one to the commit "
        f"message stating WHY the job no longer needs doing — what replaced "
        f"it, or what feature it was removed alongside — not just that "
        f"nothing calls it today. Example: `{TRAILER_KEY}: superseded by "
        f"the streaming exporter in export_v2.py two releases ago.`\n"
        f"  {INCIDENT_COUNTEREXAMPLE}"
    )


def format_observation_only_block(label: str, trailer: str) -> str:
    return (
        f"BLOCK {label}: the {TRAILER_KEY}: trailer only restates that "
        f"nothing calls it ({trailer!r}) — that is the OBSERVATION, not a "
        f"reason, and it is close to verbatim what the incident's own "
        f"commit message said. State WHY the job no longer needs doing: "
        f"what replaced it, what it was removed alongside, or where it was "
        f"migrated to.\n  {INCIDENT_COUNTEREXAMPLE}"
    )


def _evaluate_one(rd: Definition, ctx: dict, added: list, consumed: set) -> Finding:
    """The four-way disposition for a single removed definition. Split out
    of evaluate()'s loop body to keep both under the S4.2 function-length
    cap without folding the branches back into one another.

    Rename-match runs BEFORE the survivor grep, not after — see the
    "rename before survivor" note in the module docstring for why checking
    order the other way around self-blocked this very refactor."""
    label = f"{rd.file}::{rd.name} ({rd.kind})"
    if is_test_path(rd.file):
        return Finding(False, f"SKIP  {label} — test path, exempt")

    match = find_rename_match(rd, added, consumed)
    if match:
        idx, cand, ratio = match
        consumed.add(idx)
        return Finding(
            False, f"PASS  {label} — matches added {cand.file}::{cand.name} "
                   f"(similarity={ratio:.2f}, treated as rename/move)"
        )

    survivors = find_survivors(
        ctx["repo"], ctx["ref"], ctx["mode"], rd.name, rd.lang,
        exclude_paths=ctx["touched"],
    )
    if survivors:
        return Finding(True, format_survivor_block(label, rd.name, survivors))

    trailer = extract_trailer(ctx["message"], TRAILER_KEY)
    if trailer and is_substantive(trailer):
        return Finding(False, f"PASS  {label} — no survivors; {TRAILER_KEY}: {trailer}")
    if trailer:
        return Finding(True, format_observation_only_block(label, trailer))
    if not ctx["require_trailer"]:
        # No commit exists yet to carry a trailer (the staged-diff or
        # worktree "net" — a PreToolUse hook only sees one file at a time
        # and this gate also runs on the accumulated diff before commit).
        # Deferring here is not a silent pass: the commit/CI-range
        # invocation of this same evaluate() with require_trailer=True is
        # what actually closes the "no survivors, no reason" hole (module
        # docstring point 3) — this path exists so staging a legitimate
        # deletion is never blocked before there is anywhere to put the
        # reason.
        return Finding(
            False, f"PASS  {label} — no survivors; {TRAILER_KEY} required "
                   f"at commit time (not checked before then)"
        )
    return Finding(True, format_no_trailer_block(label))


def _touched_files(request: GateRequest) -> set:
    """Every path this diff added, modified, deleted or renamed — the set a
    survivor must fall OUTSIDE of to count as dangerous. A caller inside a
    file this same diff already touched is evidence the author saw it and
    kept it consistent; the incident's own commit message names the
    opposite shape exactly ("in files that commit's own diff never
    touched") as what made the missing callers invisible."""
    touched = set()
    for status, old_path, new_path in changed_paths(
        request.repo, request.base, request.head, request.mode
    ):
        touched.add(old_path)
        touched.add(new_path)
    return touched


def evaluate(request: GateRequest) -> GateResult:
    removed, added = collect_definitions(request.repo, request.base, request.head, request.mode)
    # worktree mode's post-image is the actual working tree, not any git
    # ref, so its survivor search must target the same place (find_survivors
    # treats MODE_WORKTREE as "search the working tree") — the PostToolUse
    # "net" is worthless if it removes a definition from the disk it just
    # read but then greps a stale committed tree for callers.
    ref = None if request.mode == MODE_WORKTREE else request.head
    ctx = {
        "repo": request.repo, "ref": ref, "mode": request.mode,
        "message": request.message, "require_trailer": request.require_trailer,
        "touched": _touched_files(request),
    }
    consumed: set = set()
    result = GateResult()
    for rd in removed:
        result.findings.append(_evaluate_one(rd, ctx, added, consumed))
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deletion_gate", description=__doc__)
    p.add_argument("--repo", default=".", help="repository to gate")
    p.add_argument("--commit", help="single commit sha to gate (diffs sha^..sha)")
    p.add_argument("--base", help="base ref (range mode)")
    p.add_argument("--head", default="HEAD", help="head ref (range mode)")
    p.add_argument("--staged", action="store_true", help="gate HEAD vs the index")
    p.add_argument(
        "--worktree", action="store_true",
        help="gate HEAD vs the actual on-disk working tree (catches sed/rm/patch/"
             "multi-step edits that never touch the index — the PostToolUse net)",
    )
    p.add_argument("--message-file", help="path to a commit message file")
    return p


def resolve_message(repo: str, args) -> str:
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as fh:
            return fh.read()
    if args.commit:
        return commit_message(repo, args.commit)
    if args.staged or args.worktree:
        return ""
    return range_messages(repo, args.base, args.head)


def count_modes_given(args) -> int:
    return sum((bool(args.commit), bool(args.staged), bool(args.worktree), bool(args.base)))


def resolve_mode(args) -> tuple:
    """(base, head, mode, require_trailer) for the CLI mode selected by
    args. Each branch fixes all four TOGETHER as one decision for that
    mode — they must never be derived independently. That independence is
    exactly what CodeQL's py/uninitialized-local-variable flagged at
    deletion_gate.py:443 (sha 6ef90aa): require_trailer used to be derived
    from `args.staged` alone in a separate statement, while base/head were
    chosen by commit-priority (`if args.commit: ... elif args.staged: ...`).
    The flagged line was not actually unreachable in the strict Python
    sense, but the root cause the analyzer was reacting to was real: a
    caller combining `--commit` and `--staged` got the two silently
    disagreeing — base/head took the commit diff, but `staged=True` (or, in
    this generalized form, MODE_STAGED) was still forwarded into
    evaluate()/collect_definitions, which diffs the empty staged index
    instead of commit^..commit, and a real trailer-less deletion passed
    silently. A gate that cannot tell which of several mutually exclusive
    modes was requested must refuse the input, not let one flag silently
    win over the others — enforced by the caller via count_modes_given()
    before this function ever runs, so exactly one of the branches below
    applies and every returned value is unconditionally fixed by it.
    """
    base, head = args.base, args.head
    mode = None
    require_trailer = True

    if args.commit:
        base, head = f"{args.commit}^", args.commit
    elif args.staged:
        base, head = "HEAD", args.head  # pre-image is the last commit; head is unused
        mode = MODE_STAGED
        require_trailer = bool(args.message_file)
    elif args.worktree:
        base, head = "HEAD", args.head  # post-image is the working tree, not head
        mode = MODE_WORKTREE
        require_trailer = bool(args.message_file)

    return base, head, mode, require_trailer


def main(argv: list) -> int:
    args = build_parser().parse_args(argv)
    modes_given = count_modes_given(args)
    if modes_given == 0:
        print(
            "error: one of --commit, --base/--head, --staged, or --worktree is "
            "required", file=sys.stderr,
        )
        return EXIT_USAGE
    if modes_given > 1:
        # A caller passing two mode flags at once (e.g. --commit sha
        # --staged) leaves it undecided which diff the gate should run.
        # Refuse the input; do not let one flag silently win.
        print(
            "error: --commit, --staged, --worktree, and --base/--head are "
            "mutually exclusive modes — combine none or exactly one",
            file=sys.stderr,
        )
        return EXIT_USAGE

    base, head, mode, require_trailer = resolve_mode(args)

    try:
        require_pcre(args.repo)
        message = resolve_message(args.repo, args)
        request = GateRequest(args.repo, base, head, message, mode, require_trailer)
        result = evaluate(request)
    except GitError as exc:
        print(
            f"error: could not verify this diff for removed definitions ({exc}). "
            f"Fix the git/tooling problem above and retry — this gate refuses to "
            f"pass a removal it could not check.",
            file=sys.stderr,
        )
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
