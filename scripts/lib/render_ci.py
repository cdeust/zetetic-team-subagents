#!/usr/bin/env python3
"""Render separate event paths from canonical job blocks without a YAML dependency.

Source: tasks/ci-event-separation-20261024.md. GitHub preserves the caller event:
https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#github-context
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
# Source: templates/ci/native/source.json pins the copied Cortex configuration.
NATIVE_ASSETS = (
    "scripts/tests/test_ci_workflow_authorization.py",
    ".github/workflows/Codex.yml",
    ".github/workflows/claude-review.yml",
    ".github/workflows/claude.yml",
    ".github/claude-cli/package.json",
    ".github/claude-cli/package-lock.json",
    "scripts/ci_codex_review_event.py",
    "scripts/ci_codex_review_event_source.py",
    "scripts/ci_codex_review_resume.py",
    "scripts/ci_codex_review_reconcile.py",
    "scripts/ci_codex_review_runtime.py",
    "scripts/ci_codex_review_comments.py",
    "scripts/ci_codex_review_agreement.py",
    "scripts/ci_codex_reviews.py",
    "scripts/tests/codex_resume_fixtures.py",
    "scripts/tests/test_ci_codex_review_resume.py",
    "scripts/tests/test_ci_codex_review_event_fixtures.py",
    "scripts/tests/test_ci_codex_review_event.py",
    "scripts/tests/test_ci_codex_review_event_attempts.py",
    "scripts/tests/test_ci_codex_review_event_cli.py",
    "scripts/tests/test_ci_codex_review_reconcile.py",
    "scripts/tests/test_ci_codex_review_schedule.py",
    "scripts/tests/test_ci_codex_review_schedule_cli.py",
    "scripts/tests/test_ci_codex_review_proof_first.py",
    "scripts/tests/test_ci_codex_review_gate_groups.py",
    ".claude/commands/review-pr.md",
    ".claude/agents/code-quality-reviewer.md",
    ".claude/agents/documentation-accuracy-reviewer.md",
    ".claude/agents/performance-reviewer.md",
    ".claude/agents/security-code-reviewer.md",
    ".claude/agents/test-coverage-reviewer.md",
)
JOB_ORDER = ("resolve", "contract", *CATEGORIES, "review", "merge", "tag")
SOURCE_SHA = "${{ github.event_name == 'workflow_run' && needs.resolve.outputs.tested_sha || github.sha }}"
CONTRACT_GATE = """    needs: resolve
    if: >-
      always() && !cancelled() && (github.event_name != 'workflow_run'
      || (needs.resolve.result == 'success' && needs.resolve.outputs.run_tests == 'true'))
"""
TAG_EVENT = "((github.event_name == 'push' && github.ref == 'refs/heads/main') || github.event_name == 'workflow_run')"


def replace_exact(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError("Canonical template changed at: " + old.splitlines()[0])
    return text.replace(old, new)


def split_jobs(text):
    header, separator, body = text.partition("\njobs:\n")
    if not separator or re.search(r"^jobs:", body, re.MULTILINE):
        raise ValueError("Canonical template needs exactly one jobs mapping")
    matches = list(re.finditer(r"^  ([a-z][a-z0-9_-]*):\n", body, re.MULTILINE))
    if tuple(match[1] for match in matches) != JOB_ORDER:
        raise ValueError("Canonical job names/order differ from the explicit contract")
    jobs = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        jobs[match[1]] = body[match.start() : end]
    return header + "\njobs:\n", jobs


def contract_job(text, completion):
    if completion:
        gate = (
            "    needs: resolve\n    if: >-\n"
            "      !cancelled() && github.event_name == 'workflow_run'\n"
            "      && needs.resolve.result == 'success' && needs.resolve.outputs.run_tests == 'true'\n"
        )
        sha = "${{ needs.resolve.outputs.tested_sha }}"
    else:
        gate = "    if: >-\n      !cancelled()\n"
        sha = "${{ github.sha }}"
    text = replace_exact(text, CONTRACT_GATE, gate)
    return replace_exact(text, SOURCE_SHA, sha, count=2)


def event_header(header, completion):
    direct_on = """on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  push:
    branches: [main]
"""
    if "workflow_call:" in header or "workflow_run:" in header:
        raise ValueError("Canonical template must declare only direct event triggers")
    if completion:
        header = replace_exact(
            header, "name: Pipeline\n", "name: Pipeline post-merge tests\n"
        )
        header = replace_exact(
            header,
            direct_on,
            """on:
  workflow_call:
    secrets:
      RELEASE_TAG_SSH_KEY:
        required: false
""",
        )
    else:
        replace_exact(header, direct_on, direct_on)
    return header


def workflow(text, completion):
    header, jobs = split_jobs(text)
    jobs["contract"] = contract_job(jobs["contract"], completion)
    event = (
        "github.event_name == 'workflow_run'"
        if completion
        else "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    jobs["tag"] = replace_exact(jobs["tag"], TAG_EVENT, event)
    order = (
        ("resolve", "contract", *CATEGORIES, "tag")
        if completion
        else ("contract", *CATEGORIES, "review", "merge", "tag")
    )
    rendered = event_header(header, completion) + "".join(jobs[name] for name in order)
    if completion and (
        "claude-code-action@" in rendered
        or "secrets.CLAUDE_CODE_OAUTH_TOKEN" in rendered
    ):
        raise ValueError(
            "Completion engine cannot contain the PR review action or OAuth secret"
        )
    return rendered


def blob(path):
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def completion_caller(text):
    """Refuse a template that reconnects the privileged caller to PR review."""
    expected = "    uses: ./.github/workflows/pipeline-post-merge.yml"
    uses = re.findall(r"^\s*uses:.*$", text, re.MULTILINE)
    if uses != [expected]:
        raise ValueError("Completion caller must target only the post-merge engine")
    secret = (
        "    secrets:\n      RELEASE_TAG_SSH_KEY: ${{ secrets.RELEASE_TAG_SSH_KEY }}\n"
    )
    replace_exact(text, secret, secret)
    if (
        "secrets: inherit" in text
        or "issues: write" in text
        or "id-token: write" in text
    ):
        raise ValueError("Completion caller exposes unnecessary privileges")
    return text


def artifacts(root=ROOT, native_review=False):
    profile = "native/pipeline.yml" if native_review else "pipeline.yml"
    source = root / "templates/ci" / profile
    caller = root / "templates/ci/pipeline-after-merge.yml"
    text = source.read_text()
    header = "# generated by zetetic-team-subagents render-ci "
    result = {
        "pipeline.yml": header + blob(source) + "\n" + workflow(text, False),
        "pipeline-post-merge.yml": header + blob(source) + "\n" + workflow(text, True),
        "pipeline-after-merge.yml": header
        + blob(caller)
        + "\n"
        + completion_caller(caller.read_text()),
    }
    return result


def native_asset(path: Path, no_schedule: bool) -> bytes:
    data = path.read_bytes()
    if no_schedule and path.name == "Codex.yml":
        # Source: native/assets/.github/workflows/Codex.yml fallback trigger.
        # Keep dispatch discovery and both authenticated completion event paths.
        schedule = (
            "  # Supported fallback: review-thread resolution has no Actions event.\n"
            "  # GitHub documents five minutes as the shortest schedule interval.\n"
            "  schedule:\n"
            '    - cron: "*/5 * * * *"\n'
        )
        data = replace_exact(data.decode(), schedule, "").encode()
    return data


def prepare_files(target, root=ROOT, native_review=False, no_schedule=False):
    if no_schedule and not native_review:
        raise ValueError("--no-schedule requires --native-review")
    # Resolve/validate every source before the first destination write.
    files = {
        target / ".github/workflows" / name: body.encode()
        for name, body in artifacts(root, native_review).items()
    }
    if native_review:
        assets = root / "templates/ci/native/assets"
        files.update(
            {target / name: native_asset(assets / name, no_schedule) for name in NATIVE_ASSETS}
        )
    example = (root / "templates/ci/ci.example.json").read_bytes()
    if not (target / "ci.json").exists():
        files[target / "ci.json"] = example
    for path in files:
        if any(
            (target / parent).is_symlink()
            for parent in path.relative_to(target).parents
        ):
            raise ValueError("Refusing symlink output parent: " + str(path))
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Refusing non-file output: " + str(path))
    return files


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".render-ci-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def deliver(files, dry_run=False):
    before = {path: path.read_bytes() if path.exists() else None for path in files}
    changed = [path for path, body in files.items() if before[path] != body]
    if dry_run:
        for path in changed:
            print("Would write:", path)
        return
    written = []
    try:
        for path in changed:
            write_bytes(path, files[path])
            written.append(path)
    except OSError:
        for path in reversed(written):
            if path.read_bytes() != files[path]:
                raise RuntimeError(
                    "Concurrent edit prevents rollback: " + str(path)
                ) from None
            if before[path] is None:
                path.unlink()
            else:
                write_bytes(path, before[path])
        raise
    for path in files:
        print("Wrote:" if path in changed else "Unchanged:", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--native-review",
        action="store_true",
        help="install native Codex and official Claude review workflows",
    )
    parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="omit native Codex polling; retain event and manual completion",
    )
    args = parser.parse_args()
    if args.no_schedule and not args.native_review:
        parser.error("--no-schedule requires --native-review")
    if not args.target.is_dir():
        parser.error("target must be an existing repository directory")
    files = prepare_files(
        args.target, native_review=args.native_review, no_schedule=args.no_schedule
    )
    deliver(files, args.dry_run)


if __name__ == "__main__":
    main()
