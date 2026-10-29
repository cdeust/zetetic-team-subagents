#!/usr/bin/env python3
"""Reconcile once against an explicit owner's repository inventory.

Uses the same discovery and authenticated coordinator as hosted Codex.yml.
Bootstrap execution is serialized by the host before enabling hosted recovery;
GitHub issue-comment creation has no conditional-create/idempotency API.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_codex_review_reconcile as reconcile  # noqa: E402
from ci_codex_reviews import EvidenceError, REPO_PATTERN, _json  # noqa: E402


def inventory(path):
    data = _json(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"owner", "repositories"}:
        raise EvidenceError("inventory")
    owner, repos = data["owner"], data["repositories"]
    if not isinstance(owner, str) or not isinstance(repos, list) or not repos:
        raise EvidenceError("inventory")
    unique = set()
    for repo in repos:
        if (not isinstance(repo, str) or REPO_PATTERN.fullmatch(repo) is None
            or repo.split("/")[0] != owner or repo.split("/")[1] in (".", "..")
            or repo.casefold() in unique):
            raise EvidenceError("inventory")
        unique.add(repo.casefold())
    return repos


def _resume(repo, candidate, dry_run):
    prior = os.environ.get("EXPECTED_PR")
    try:
        os.environ["EXPECTED_PR"] = str(candidate["number"])
        trigger = {**candidate, "run_id": None}
        return reconcile.events.resume(repo, trigger, dry_run=dry_run)
    finally:
        if prior is None:
            os.environ.pop("EXPECTED_PR", None)
        else:
            os.environ["EXPECTED_PR"] = prior


def once(repos, *, dry_run=False):
    results = []
    for repo in repos:
        print(f"codex controller: repository={repo} discover", file=sys.stderr, flush=True)
        try:
            candidates = reconcile.discover(repo)
        except EvidenceError as exc:
            results.append(dict(repository=repo, error=str(exc)))
            continue
        print(f"codex controller: repository={repo} candidates={len(candidates)}", file=sys.stderr, flush=True)
        for candidate in candidates:
            print(f"codex controller: repository={repo} pr={candidate['number']} reconcile", file=sys.stderr, flush=True)
            try:
                result = _resume(repo, candidate, dry_run)
                results.append(dict(repository=repo, **candidate, result=result))
            except EvidenceError as exc:
                results.append(dict(repository=repo, **candidate, error=str(exc)))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = once(inventory(args.inventory), dry_run=args.dry_run)
        print(json.dumps(result, sort_keys=True))
        return int(any("error" in row for row in result))
    except (EvidenceError, OSError, UnicodeError) as exc:
        category = str(exc) if isinstance(exc, EvidenceError) else "inventory"
        print("codex controller: " + category, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
