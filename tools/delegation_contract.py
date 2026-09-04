#!/usr/bin/env python3
"""delegation_contract.py — fail-closed validator for a delegation contract.

Single responsibility: given a delegation-contract JSON file, decide launch
or deny per schemas/delegation-contract.schema.yaml, BEFORE the caller
(scripts/spawn-agent.sh) performs any worktree, process, branch, or remote
mutation. This module never mutates the filesystem outside its own lock
directory (register_active/release_active) and never launches anything.

Closes HC-ZETETIC-004 (mechanical-delegation-preconditions): "A malformed or
conflicting delegation will launch and mutate state before the system
surfaces its missing authority, ownership conflict, or unverifiable
completion contract" — this module is the pre-mutation oracle that stops
that.

Exit codes (CLI mode): 0 = valid (launch), 1 = invalid (deny), 2 = usage.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}

REQUIRED_FIELDS = (
    "schema_version",
    "agent",
    "target_repo",
    "owned_paths",
    "excluded_paths",
    "worktree_policy",
    "push_authority",
    "handback_artifacts",
    "acceptance_oracle",
    "model",
    "tool_grant",
    "checkpoint_policy",
)

VALID_PUSH_AUTHORITY = {"forbidden", "allowed", "required"}
VALID_WORKTREE_POLICY = {"required", "none"}


class ContractError(Exception):
    """A single fail-closed rejection reason, per the schema's
    fail_closed_reject_reasons table."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def load_contract(path: Path) -> dict[str, Any]:
    """Read and JSON-parse the contract file.

    precondition: path exists and is readable.
    postcondition: returns the parsed dict, or raises ContractError
    ('malformed_json') on any parse failure — never returns a partial dict.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("malformed_json", f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError("malformed_json", f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("malformed_json", f"{path}: top-level value is not an object")
    return data


def _resolve_agent_file(repo_root: Path, agent: str) -> Path | None:
    for candidate in (repo_root / "agents" / f"{agent}.md", repo_root / "agents" / "genius" / f"{agent}.md"):
        if candidate.is_file():
            return candidate
    return None


def _path_escapes_repo(repo_root: Path, pattern: str) -> bool:
    """A glob pattern escapes the repo if its literal (non-wildcard) prefix,
    once joined to repo_root and normalized, is not repo_root or a
    descendant of it. '..' segments are the concrete failure mode named in
    the HC-ZETETIC-004 fixture corpus."""
    joined = os.path.normpath(os.path.join(str(repo_root), pattern))
    repo_str = os.path.normpath(str(repo_root))
    return joined != repo_str and not joined.startswith(repo_str + os.sep)


# excluded_paths is legitimately allowed to be an empty list ("May be empty"
# per the schema doc) — presence, not non-emptiness, is what's required for
# it. owned_paths is checked for presence in _check_required_fields too, but
# its emptiness gets the more specific `empty_owned_paths` reason from
# _check_paths rather than the generic `missing_required_field`.
_PRESENCE_ONLY_FIELDS = {"excluded_paths", "owned_paths"}


def _check_required_fields(contract: dict[str, Any]) -> None:
    """Every REQUIRED_FIELDS entry present and non-empty (excluded_paths /
    owned_paths exempted from the non-empty half; each has its own,
    more specific check downstream)."""
    for field in REQUIRED_FIELDS:
        if field not in contract or contract[field] is None:
            raise ContractError("missing_required_field", field)
        if field not in _PRESENCE_ONLY_FIELDS and contract[field] in ("", [], {}):
            raise ContractError("missing_required_field", field)
    if contract["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContractError("unknown_schema_version", str(contract["schema_version"]))


def _check_agent(contract: dict[str, Any], repo_root: Path) -> None:
    if not repo_root.is_dir():
        raise ContractError("missing_required_field", f"target_repo does not exist: {repo_root}")
    if _resolve_agent_file(repo_root, contract["agent"]) is None:
        raise ContractError("unknown_agent", contract["agent"])


def _first_escaping_pattern(repo_root: Path, patterns: list[str]) -> str | None:
    """Return the first pattern (if any) that resolves outside repo_root —
    a single guard clause instead of a nested loop-with-raise, keeping
    callers at nesting depth <= 3 (coding-standards §4.5)."""
    escaping = (p for p in patterns if _path_escapes_repo(repo_root, p))
    return next(escaping, None)


def _check_paths(contract: dict[str, Any], repo_root: Path) -> None:
    owned = contract["owned_paths"]
    if not isinstance(owned, list) or not owned:
        raise ContractError("empty_owned_paths")

    excluded = contract["excluded_paths"]
    if not isinstance(excluded, list):
        raise ContractError("missing_required_field", "excluded_paths must be a list")

    escaping = _first_escaping_pattern(repo_root, list(owned) + list(excluded))
    if escaping is not None:
        raise ContractError("path_escapes_repo", escaping)


def _check_push_and_handback(contract: dict[str, Any]) -> None:
    if contract["worktree_policy"] not in VALID_WORKTREE_POLICY:
        raise ContractError("missing_required_field", f"invalid worktree_policy: {contract['worktree_policy']}")

    push_authority = contract["push_authority"]
    if push_authority not in VALID_PUSH_AUTHORITY:
        raise ContractError("invalid_push_authority", str(push_authority))

    handback = contract["handback_artifacts"]
    if not isinstance(handback, list) or not handback:
        raise ContractError("missing_required_field", "handback_artifacts")
    if push_authority in ("allowed", "required") and "pr_number" not in handback:
        raise ContractError("missing_pr_number_handback", push_authority)


def _check_oracle_tools_checkpoint(contract: dict[str, Any]) -> None:
    oracle = contract["acceptance_oracle"]
    if not isinstance(oracle, dict) or not oracle.get("type") or not oracle.get("criterion"):
        raise ContractError("empty_acceptance_oracle")

    tool_grant = contract["tool_grant"]
    if not isinstance(tool_grant, list) or not tool_grant:
        raise ContractError("empty_tool_grant")

    checkpoint = contract["checkpoint_policy"]
    threshold = checkpoint.get("threshold_tokens") if isinstance(checkpoint, dict) else None
    scope = checkpoint.get("scope") if isinstance(checkpoint, dict) else None
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0 or not scope:
        raise ContractError("invalid_checkpoint_policy")


def validate_schema(contract: dict[str, Any], repo_root_override: Path | None = None) -> None:
    """Structural + semantic validation. Raises ContractError on the first
    violation found — fail closed, no partial acceptance. Delegates each
    concern (required fields, agent resolution, path safety, push/handback
    consistency, oracle/tools/checkpoint) to its own single-purpose check.

    precondition: contract is a dict (already JSON-parsed).
    postcondition: no exception raised implies every REQUIRED_FIELDS entry
    is present, non-empty where required, and every path stays inside
    target_repo.
    """
    _check_required_fields(contract)
    repo_root = repo_root_override or Path(contract["target_repo"])
    _check_agent(contract, repo_root)
    _check_paths(contract, repo_root)
    _check_push_and_handback(contract)
    _check_oracle_tools_checkpoint(contract)


def _lock_dir(repo_root: Path) -> Path:
    return repo_root / ".claude" / "delegation-locks"


def _globs_intersect(a: str, b: str) -> bool:
    return a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)


def _find_overlap(mine: list[str], theirs: list[str]) -> tuple[str, str] | None:
    """First (my_pattern, their_pattern) pair that intersects, or None.
    A flat generator expression instead of a nested for-loop-with-raise
    keeps this at nesting depth 1 (coding-standards §4.5)."""
    pairs = ((a, b) for a in mine for b in theirs if _globs_intersect(a, b))
    return next(pairs, None)


def _load_lock(lock_file: Path) -> dict[str, Any] | None:
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_overlap(contract: dict[str, Any], repo_root_override: Path | None = None) -> None:
    """Deny if any currently-active lock for the same target_repo has an
    owned_paths glob intersecting this contract's owned_paths.

    precondition: validate_schema(contract) already passed (owned_paths is a
    non-empty list of in-repo patterns).
    postcondition: no exception implies no active lock overlaps; the lock
    directory itself is left untouched (registration is a separate step).
    """
    repo_root = repo_root_override or Path(contract["target_repo"])
    lock_dir = _lock_dir(repo_root)
    if not lock_dir.is_dir():
        return
    mine = contract["owned_paths"]
    for lock_file in sorted(lock_dir.glob("*.json")):
        other = _load_lock(lock_file)
        if other is None:
            continue
        overlap = _find_overlap(mine, other.get("owned_paths", []))
        if overlap is not None:
            mine_pattern, their_pattern = overlap
            raise ContractError(
                "overlapping_ownership",
                f"'{mine_pattern}' conflicts with active lock {lock_file.name} "
                f"(agent={other.get('agent', '?')}, pattern='{their_pattern}')",
            )


def register_active(contract: dict[str, Any], lock_name: str, repo_root_override: Path | None = None) -> Path:
    """Write the active-contract lock file. Caller (spawn-agent.sh, via the
    trap) is responsible for removing it on exit — release_active does the
    removal; this function only creates it, after validate_schema and
    check_overlap have both passed."""
    repo_root = repo_root_override or Path(contract["target_repo"])
    lock_dir = _lock_dir(repo_root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{lock_name}.json"
    lock_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return lock_path


def release_active(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def validate(contract_path: Path, repo_root_override: Path | None = None) -> dict[str, Any]:
    """Full fail-closed validation: parse, schema, overlap. Returns the
    parsed contract on success. Raises ContractError on the first failure —
    this IS the pre-mutation oracle spawn-agent.sh calls."""
    contract = load_contract(contract_path)
    validate_schema(contract, repo_root_override)
    check_overlap(contract, repo_root_override)
    return contract


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path, help="path to the delegation-contract JSON file")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="override target_repo for testing (defaults to the contract's own target_repo field)",
    )
    args = parser.parse_args(argv)

    try:
        contract = validate(args.contract, args.repo_root)
    except ContractError as exc:
        print(json.dumps({"decision": "deny", "reason": exc.reason, "detail": exc.detail}), file=sys.stderr)
        return 1

    print(json.dumps({"decision": "launch", "agent": contract["agent"], "push_authority": contract["push_authority"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
