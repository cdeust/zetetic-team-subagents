#!/usr/bin/env python3
"""Render separate event paths from canonical job blocks without a YAML dependency.

Source: tasks/ci-event-separation-20261024.md. GitHub preserves the caller event:
https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#github-context
"""

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile
from textwrap import indent
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
# Source: templates/ci/native/source.json pins the copied Cortex configuration.
CLI_ASSETS = (".github/claude-cli/package.json", ".github/claude-cli/package-lock.json")
NATIVE_ASSETS = (
    "scripts/tests/test_no_main_comparison.py",
    ".github/workflows/Codex.yml",
    ".github/workflows/claude-review.yml",
    ".github/workflows/claude.yml",
    *CLI_ASSETS,
    "scripts/ci_codex_review_event.py",
    "scripts/ci_codex_review_event_source.py",
    "scripts/ci_codex_review_resume.py",
    "scripts/ci_codex_review_reconcile.py",
    "scripts/ci_codex_review_runtime.py",
    "scripts/ci_codex_review_pages.py",
    "scripts/ci_codex_review_comments.py",
    "scripts/ci_codex_review_reaction.py",
    "scripts/ci_codex_review_agreement.py",
    "scripts/ci_codex_reviews.py",
    "scripts/tests/codex_resume_fixtures.py",
    "scripts/tests/test_ci_codex_review_resume.py",
    "scripts/tests/test_ci_codex_review_event_fixtures.py",
    "scripts/tests/test_ci_codex_review_event.py",
    "scripts/tests/test_ci_codex_review_event_attempts.py",
    "scripts/tests/test_ci_codex_review_event_cli.py",
    "scripts/tests/test_ci_codex_review_reconcile.py",
    "scripts/tests/test_ci_codex_review_reaction.py",
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
# The default profile's resolver merges on the verdict of the PR Review workflow, so the
# render delivers that workflow with what it runs: the review budget, the /review-pr
# command and its five reviewers (templates/ci/review, Cortex's files byte for byte).
REVIEW_ASSETS = (
    ".github/workflows/claude-review.yml",
    "scripts/ci_review_budget.py",
    ".claude/commands/review-pr.md",
    ".claude/agents/code-quality-reviewer.md",
    ".claude/agents/documentation-accuracy-reviewer.md",
    ".claude/agents/performance-reviewer.md",
    ".claude/agents/security-code-reviewer.md",
    ".claude/agents/test-coverage-reviewer.md",
)
# The default profile follows Cortex: the review is its own workflow (claude-review.yml)
# and the resolver reads its verdict, so the Pipeline carries no review job (ADR-1121).
JOB_ORDER = ("resolve", "close-issues", "contract", *CATEGORIES, "merge", "tag")
NATIVE_JOB_ORDER = ("resolve", "contract", *CATEGORIES, "review", "merge", "tag")
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
    if tuple(match[1] for match in matches) not in (JOB_ORDER, NATIVE_JOB_ORDER):
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
    # resolve and close-issues exist only where a completed run is resolved.
    resolver_only = ("resolve", "close-issues")
    pull_request_only = ("review", "merge")
    skipped = pull_request_only if completion else resolver_only
    order = tuple(name for name in jobs if name not in skipped)
    rendered = event_header(header, completion) + "".join(jobs[name] for name in order)
    if completion and (
        "claude-code-action@" in rendered
        or "secrets.CLAUDE_CODE_OAUTH_TOKEN" in rendered
    ):
        raise ValueError(
            "Completion engine cannot contain the PR review action or OAuth secret"
        )
    return rendered


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
    # issues: write is the close-issues job's: a GITHUB_TOKEN merge does not
    # trigger GitHub's closing keywords, so the resolver closes the issues itself.
    if "secrets: inherit" in text or "id-token: write" in text:
        raise ValueError("Completion caller exposes unnecessary privileges")
    return text


def caller_events(text, native_review):
    """The native resolver accepts a Pipeline completion only: no review wake-up there."""
    wake = (
        "# The review and the Pipeline finish in either order: each completion wakes the\n"
        "# resolver, which merges once both are there (ADR-1127).\n"
    )
    both = "    workflows: [Pipeline, PR Review]\n"
    if not native_review:
        replace_exact(text, both, both)
        return text
    return replace_exact(replace_exact(text, wake, ""), both, "    workflows: [Pipeline]\n")


def artifacts(root=ROOT, native_review=False):
    profile = "native/pipeline.yml" if native_review else "pipeline.yml"
    source = root / "templates/ci" / profile
    caller = root / "templates/ci/pipeline-after-merge.yml"
    text = source.read_text()
    # Fixed header: a hash here changed every consumer's bytes on each render
    # (owner rule 2026-10-29, enforced by tests/test_no_main_comparison.py).
    header = "# generated by zetetic-team-subagents render-ci\n"
    result = {
        "pipeline.yml": header + workflow(text, False),
        "pipeline-post-merge.yml": header + workflow(text, True),
        "pipeline-after-merge.yml": header
        + completion_caller(caller_events(caller.read_text(), native_review)),
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


POST_MERGE = ".github/workflows/pipeline-post-merge.yml"
NATIVE_PARSER = "scripts/ci_native_verdict.py"
OVERLAY_START = "          # render-ci: native-verdict begin\n"
OVERLAY_END = "          # render-ci: native-verdict end\n"
CLAUDE_GATE = '                  _review_approves(pr["number"], head, repository, api)\n'
NATIVE_GATE = '                  _selected_review_approves(pr["number"], head, repository, api)\n'


def validate_path(target, path):
    if any((target / parent).is_symlink() for parent in path.relative_to(target).parents):
        raise ValueError("Refusing symlink output parent: " + str(path))
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Refusing non-file output: " + str(path))


def overlay_files(target, root, workflow):
    assets = root / "templates/ci/overlay"
    parser = (assets / "ci_native_verdict.py").read_text()
    resolver = (assets / "native-resolver.py").read_text()
    overlay = OVERLAY_START + indent(parser + "\n\n" + resolver, " " * 10) + OVERLAY_END
    if OVERLAY_START in workflow:
        if workflow.count(OVERLAY_START) != 1 or workflow.count(OVERLAY_END) != 1:
            raise ValueError("Invalid native-verdict overlay markers")
        before, _, rest = workflow.partition(OVERLAY_START)
        _, found, after = rest.partition(OVERLAY_END + "\n")
        if not found:
            raise ValueError("Invalid native-verdict overlay marker order")
        workflow = replace_exact(before + after, NATIVE_GATE, CLAUDE_GATE)
    elif OVERLAY_END in workflow:
        raise ValueError("Missing native-verdict overlay start")
    anchor = "          def _merge_open_pr(pr, merge_path, head, api, repository):\n"
    workflow = replace_exact(workflow, anchor, overlay + "\n" + anchor)
    workflow = replace_exact(workflow, CLAUDE_GATE, NATIVE_GATE)
    parser_path = target / NATIVE_PARSER
    validate_path(target, parser_path)
    return {target / POST_MERGE: workflow.encode(), parser_path: parser.encode()}


def prepare_files(target, root=ROOT, native_review=False, no_schedule=False, native_verdict=False):
    if no_schedule and not native_review:
        raise ValueError("--no-schedule requires --native-review")
    post_merge = target / POST_MERGE
    validate_path(target, post_merge)
    workflow = post_merge.read_bytes().decode() if post_merge.exists() else ""
    if native_verdict or OVERLAY_START in workflow or OVERLAY_END in workflow:
        if native_review:
            raise ValueError("--native-review conflicts with the native-verdict overlay")
        if not workflow:
            raise ValueError("--native-verdict requires an existing pipeline-post-merge.yml")
        return overlay_files(target, root, workflow)
    files = {
        target / ".github/workflows" / name: body.encode()
        for name, body in artifacts(root, native_review).items()
    }
    assets = root / "templates/ci/native/assets"
    if native_review:
        files.update(
            {target / name: native_asset(assets / name, no_schedule) for name in NATIVE_ASSETS}
        )
    else:
        review = root / "templates/ci/review"
        files.update({target / name: (review / name).read_bytes() for name in REVIEW_ASSETS})
        files.update({target / name: (assets / name).read_bytes() for name in CLI_ASSETS})
    example = (root / "templates/ci/ci.example.json").read_bytes()
    if not (target / "ci.json").exists():
        files[target / "ci.json"] = example
    for path in files:
        validate_path(target, path)
    return files


class Output(NamedTuple):
    data: bytes
    device: int
    inode: int
    uid: int
    gid: int
    mode: int


def output_state(data, info):
    return Output(data, info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))


def read_output(path):
    # Read both the bytes and their identity from the same regular file.
    if path.is_symlink():
        raise OSError("Refusing symlink output: " + str(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Refusing non-file output: " + str(path))
        return output_state(stream.read(), info)


def require_output(path, expected):
    if read_output(path) != expected:
        raise OSError("Concurrent edit of rendered output: " + str(path))


def write_output(path, data, expected, permissions):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".render-ci-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            if permissions is not None:
                mode, owner, group = permissions
                info = os.fstat(stream.fileno())
                if info.st_uid != owner or info.st_gid != group:
                    raise OSError("Cannot preserve output ownership: " + str(path))
                if hasattr(os, "fchmod"):
                    os.fchmod(stream.fileno(), mode)
                else:
                    os.chmod(temporary, mode)
            written = output_state(data, os.fstat(stream.fileno()))
        require_output(path, expected)
        os.replace(temporary, path)
        return written
    finally:
        Path(temporary).unlink(missing_ok=True)


def deliver(files, dry_run=False):
    before = {path: read_output(path) for path in files}
    changed = [path for path, body in files.items() if before[path] is None or before[path].data != body]
    for path in changed:
        original = before[path]
        if original and original.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
            raise ValueError("Refusing special mode on rendered output: " + str(path))
    if dry_run:
        for path in changed:
            print("Would write:", path)
        return
    written = {}
    try:
        for path in changed:
            original = before[path]
            # New outputs stay private (mkstemp). Only existing data-file access
            # bits may be carried forward; generated files never gain an executable bit.
            allowed = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
            permissions = (original.mode & allowed, original.uid, original.gid) if original else None
            written[path] = write_output(path, files[path], original, permissions)
    except OSError:
        conflicts = []
        for path in reversed(written):
            original = before[path]
            try:
                if original is None:
                    require_output(path, written[path])
                    path.unlink()
                else:
                    permissions = original.mode, original.uid, original.gid
                    write_output(path, original.data, written[path], permissions)
            except OSError as exc:
                conflicts.append(str(exc))
        if conflicts:
            raise RuntimeError("Could not roll back rendered outputs: " + ", ".join(conflicts))
        raise
    for path in files:
        print("Wrote:" if path in changed else "Unchanged:", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--native-verdict",
        action="store_true",
        help="overlay authenticated native merge verdicts on an existing consumer pipeline",
    )
    profile.add_argument(
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
        args.target,
        native_review=args.native_review,
        no_schedule=args.no_schedule,
        native_verdict=args.native_verdict,
    )
    deliver(files, args.dry_run)


if __name__ == "__main__":
    main()
