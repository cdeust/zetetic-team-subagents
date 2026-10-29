#!/usr/bin/env python3
"""acceptance_gate.py — the deterministic half of the whole-task acceptance gate.

Runs a configured set of *command* gates (zetetic-checker, test suites, and
contract-derived shell checks), aggregates their EXIT CODES, and returns an
accept/reject verdict. It makes no judgement of its own — a gate passes iff its
command exits 0. This is what lets the autonomous build loop judge convergence
on EXTERNAL signals rather than the model re-grading its own output (intrinsic
self-correction degrades reasoning — Huang et al., "Large Language Models Cannot
Self-Correct Reasoning Yet", arXiv:2310.01798).

Diff scoping: with --diff-base/--diff-head the gate computes the changed files
of that commit range, substitutes them for the {files} token in gate commands,
and REJECTS an empty diff (a build that changed nothing cannot be accepted).
This keeps the scope deterministic and tool-owned instead of letting the builder
choose what the judge sees by staging.

Repo & config: --root sets the directory the gates and the diff run in, so this
tool can gate ANY repository, not just the one it lives in. --config is
repeatable; the gates of every config file are merged in order, which lets a
caller compose a committed base config with a contract-derived one without either
file editing the other.

The agent-based gates (review, security and architecture lenses, each a built-in agent
carrying a `GENIUS:` pattern)
and the residual non-deterministic compare-to-contract live in the controlling
workflow; this tool is the deterministic, unit-testable core they build on.

Verdict (stdout JSON): {accepted, summary, gates[], unmet[], changed_files}.
Exit codes: 0 accepted, 3 rejected (>=1 mandatory gate failed, none configured,
or empty diff), 2 usage/config error. Fails closed — an empty or unreadable gate
set is a rejection, not an auto-accept.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# A single gate's wall-clock ceiling. Test suites + the zetetic checker on this
# tree finish in seconds; 10 min is a generous bound that still kills a hang.
# source: operational default — bounds a stuck gate, not a measured constant.
DEFAULT_GATE_TIMEOUT_S = 600

# git diff is a fast metadata query; bound it so a hung git cannot stall the gate.
# source: operational default.
GIT_TIMEOUT_S = 60

# Bytes of combined stdout+stderr kept per gate for the verdict. Enough to show
# the failing assertion; small enough to keep the verdict skimmable.
# source: operational default.
OUTPUT_TAIL_BYTES = 800

# Token replaced in a gate command by the space-joined changed-file list under
# diff scoping (e.g. "zetetic-checker.sh --files {files}").
FILES_TOKEN = "{files}"

EXIT_ACCEPTED = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3  # distinct from usage so a pipeline can tell "red build" from "bad config"


def load_config(path: Path) -> dict:
    """Parse the gate-config YAML. Raises on unreadable/malformed input."""
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError("gate config must be a mapping with a 'gates' list")
    return data


def load_and_merge(paths: list[Path]) -> dict:
    """Merge one or more gate configs into a single {gates} document.

    Gates are concatenated in file order, so a caller can compose a committed base
    config with a contract-derived one without either file editing the other.
    """
    gates: list = []
    for path in paths:
        cfg = load_config(path)
        file_gates = cfg.get("gates")
        if file_gates:  # a non-list lands as a single element so validate_config flags it, not extend()
            gates.extend(file_gates if isinstance(file_gates, list) else [file_gates])
    return {"gates": gates}


def validate_config(cfg: dict) -> list[str]:
    """Return human-readable config violations (empty == valid)."""
    errors: list[str] = []
    gates = cfg.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("config.gates must be a non-empty list")
        return errors
    for i, gate in enumerate(gates):
        if not isinstance(gate, dict):
            errors.append(f"gates[{i}] must be a mapping")
            continue
        if not gate.get("name"):
            errors.append(f"gates[{i}] missing name")
        if not gate.get("cmd"):
            errors.append(f"gates[{i}] missing cmd")
    return errors


def changed_files(base: str, head: str, root: Path) -> list[str]:
    """Existing files changed between base and head (added/copied/modified/renamed).
    Deletions are excluded — there is nothing left to check on a removed path."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"],
        cwd=str(root), capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise ValueError(f"git diff {base}...{head} failed: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _uses_files(cfg: dict) -> bool:
    return any(FILES_TOKEN in (g.get("cmd") or "") for g in cfg["gates"])


def _substitute(gate: dict, files: list[str]) -> dict:
    scoped = dict(gate)
    if FILES_TOKEN in (scoped.get("cmd") or ""):
        scoped["cmd"] = scoped["cmd"].replace(FILES_TOKEN, " ".join(files))
    return scoped


def run_gate(gate: dict, root: Path, timeout: int) -> dict:
    """Execute one gate command and record its exit code + output tail.

    shell=True is the audited purpose of this tool: a gate runs a command line
    from a committed, human-controlled config — exactly like a CI step or a
    Makefile target (coding-standards §7.2 override: isolated command runner).
    """
    name = gate["name"]
    cmd = gate["cmd"]
    mandatory = bool(gate.get("mandatory", True))
    origin = gate.get("origin", "base")
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(root), timeout=timeout,
            capture_output=True, text=True,
        )
        exit_code = proc.returncode
        tail = (proc.stdout + proc.stderr)[-OUTPUT_TAIL_BYTES:].strip()
    except subprocess.TimeoutExpired:
        exit_code, tail = 124, f"timed out after {timeout}s"  # 124: timeout convention (GNU coreutils)
    except OSError as exc:
        exit_code, tail = 127, f"could not run: {exc}"  # 127: command-not-found convention (POSIX shell)
    return {
        "name": name, "cmd": cmd, "mandatory": mandatory, "origin": origin,
        "passed": exit_code == 0, "exit": exit_code, "output_tail": tail,
    }


def evaluate(results: list[dict]) -> dict:
    """Aggregate gate results into a verdict. Accept iff >=1 mandatory gate
    exists and every mandatory gate passed — fail closed on an empty set."""
    mandatory = [r for r in results if r["mandatory"]]
    passed = sum(1 for r in results if r["passed"])
    if not mandatory:
        return {
            "accepted": False,
            "summary": "no mandatory gates configured — refusing to auto-accept",
            "gates": results,
            "unmet": ["no mandatory gates — fail closed"],
        }
    failed = [r for r in mandatory if not r["passed"]]
    return {
        "accepted": not failed,
        "summary": f"{passed}/{len(results)} gates passed; "
                   f"{len(mandatory) - len(failed)}/{len(mandatory)} mandatory passed",
        "gates": results,
        "unmet": [f"{r['name']} exited {r['exit']}: {r['output_tail'][:160]}" for r in failed],
    }


def _empty_diff_verdict(base: str, head: str) -> dict:
    return {
        "accepted": False,
        "summary": f"empty diff between {base} and {head} — build produced no change",
        "gates": [],
        "unmet": ["empty-diff: nothing changed (a build that changed nothing cannot be accepted)"],
        "changed_files": [],
    }


def _gate_worktree(root: Path, rev: str) -> str:
    """Create a throwaway DETACHED worktree of `rev` so gate commands evaluate its
    COMMITTED tree, not whatever is checked out in root. Returns the worktree path."""
    wt = tempfile.mkdtemp(prefix="abl-gate-")
    proc = subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", wt, rev],
        capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise ValueError(f"git worktree add {rev} failed: {proc.stderr.strip()}")
    return wt


def _remove_gate_worktree(root: Path, wt: str) -> None:
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", wt],
                   capture_output=True, text=True, timeout=GIT_TIMEOUT_S)


def run(config_paths: list[Path], root: Path, timeout: int,
        diff_base: str | None = None, diff_head: str | None = None,
        rev: str | None = None) -> tuple[dict, int]:
    """Load config(s), scope to the diff, run every gate, return (verdict, exit).

    With `rev`, gate commands run in a throwaway detached worktree of that committed
    rev (the diff is still computed in root, whose object store the worktree shares),
    so the verdict reflects committed content regardless of root's working tree."""
    cfg = load_and_merge(config_paths)
    errors = validate_config(cfg)
    if errors:
        raise ValueError("invalid gate config:\n  " + "\n  ".join(errors))
    scoped = bool(diff_base and diff_head)
    if _uses_files(cfg) and not scoped:
        raise ValueError("a gate uses {files} but --diff-base/--diff-head were not given")
    files = None
    gates = cfg["gates"]
    if scoped:
        files = changed_files(diff_base, diff_head, root)
        if not files:
            return _empty_diff_verdict(diff_base, diff_head), EXIT_REJECTED
        gates = [_substitute(g, files) for g in gates]
    gate_cwd, wt = root, None
    try:
        if rev:
            wt = _gate_worktree(root, rev)
            gate_cwd = Path(wt)
        verdict = evaluate([run_gate(g, gate_cwd, timeout) for g in gates])
    finally:
        if wt:
            _remove_gate_worktree(root, wt)
    verdict["changed_files"] = files
    return verdict, (EXIT_ACCEPTED if verdict["accepted"] else EXIT_REJECTED)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="acceptance_gate", description=__doc__)
    parser.add_argument("--config", action="append", required=True, metavar="FILE",
                        help="gate-config YAML; repeatable — every file's gates are merged in "
                             "order (e.g. a committed base config + a contract-derived config)")
    parser.add_argument("--root", default=".", help="working dir gates + diff run from (default: cwd)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_GATE_TIMEOUT_S,
                        help="per-gate timeout in seconds")
    parser.add_argument("--diff-base", help="scope gates to files changed since this ref")
    parser.add_argument("--diff-head", help="head ref of the diff range (with --diff-base)")
    parser.add_argument("--rev", help="run gate commands in a throwaway detached worktree of this committed "
                                      "rev, so the verdict reflects committed content not root's working tree")
    args = parser.parse_args(argv)
    try:
        verdict, code = run([Path(c) for c in args.config], Path(args.root), args.timeout,
                            args.diff_base, args.diff_head, args.rev)
    except (OSError, ValueError, yaml.YAMLError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(verdict, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
