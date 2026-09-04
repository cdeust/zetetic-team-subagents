"""Build the per-run provenance sidecar: repo SHA, prompt hash, CLI/model
version, environment. Required by the pre-registration's reproducibility
manifest (Move 3) -- a run missing any of these fields is not reported.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from typing import Any


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def repo_sha(repo_root: str, allow_dirty: bool) -> tuple[str, bool]:
    """Precondition: repo_root is a git worktree. Postcondition: returns
    (HEAD sha, is_dirty). Raises if the tree is dirty and allow_dirty is
    False -- refuse to record a run against an unreproducible code state."""
    sha = _run(["git", "-C", repo_root, "rev-parse", "HEAD"])
    status = _run(["git", "-C", repo_root, "status", "--porcelain"])
    is_dirty = bool(status)
    if is_dirty and not allow_dirty:
        raise RuntimeError(
            f"repo at {repo_root} is dirty; refusing to record a run against "
            "an unreproducible code_hash (coding-standards.md §8 / Move 3)"
        )
    return sha, is_dirty


def cli_version() -> str:
    # `claude --version` prints "<semver> (Claude Code)"; keep the raw
    # string rather than parsing it, since the manifest just needs it to be
    # re-derivable, not machine-parsed downstream.
    return _run(["claude", "--version"])


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def environment_fields() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }


@dataclass(frozen=True)
class RunIdentity:
    """Parameter object for build_sidecar (coding-standards §4.4): the
    fields that vary per run, as opposed to repo_root/allow_dirty which are
    invocation-level, not run-level."""
    task_id: str
    condition: str
    replication: int
    order_position: str
    model: str
    effort: str
    prompt_text: str
    seed: int


def build_sidecar(*, repo_root: str, identity: RunIdentity, allow_dirty: bool = False) -> dict[str, Any]:
    """Assemble the full provenance sidecar for one run. Every field here is
    mandatory per the reproducibility-manifest checklist (Move 3); the caller
    fills in usage/result after the CLI call returns."""
    sha, dirty = repo_sha(repo_root, allow_dirty)
    return {
        "task_id": identity.task_id,
        "condition": identity.condition,
        "replication": identity.replication,
        "order_position": identity.order_position,
        "code_hash": sha,
        "code_dirty": dirty,
        "prompt_hash": prompt_hash(identity.prompt_text),
        "cli_version": cli_version(),
        "model": identity.model,
        "effort": identity.effort,
        "rng_seed_for_order": identity.seed,
        "environment": environment_fields(),
    }
