"""Actual disposable Git remotes prove package tags and refusal behavior.

Source: git-scm.com/docs/git-push (--atomic); tasks/package-release-tags.md.
No hosted repository, remote network, user identity or product version is changed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ci_tag.py"


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


@pytest.fixture
def repositories(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote.git"
    local.mkdir()
    remote.mkdir()
    git(local, "init", "-q", "-b", "main")
    git(remote, "init", "-q", "--bare")
    git(local, "remote", "add", "origin", str(remote))
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "fixture",
    )
    git(local, "push", "-q", "origin", "main")
    return local, remote, git(local, "rev-parse", "HEAD")


def publish(repositories, tags, **overrides):
    local, _, sha = repositories
    env = dict(
        os.environ,
        RELEASE_TAGS=json.dumps(tags),
        TESTED_SHA=sha,
        GITHUB_STEP_SUMMARY=str(local / "summary"),
        **overrides,
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=local,
        env=env,
        capture_output=True,
        text=True,
    )


def test_publishes_distinct_package_versions_at_tested_sha_and_is_idempotent(
    repositories,
):
    local, remote, sha = repositories
    tags = ["engine/v1.2.3", "claude-mods/v0.1.2"]
    result = publish(repositories, tags)
    assert result.returncode == 0, result.stderr
    original = git(remote, "show-ref", "--tags")
    for tag in tags:
        assert git(remote, "rev-parse", f"refs/tags/{tag}^{{}}") == sha
    assert git(remote, "rev-parse", "refs/heads/main") == sha
    assert publish(repositories, tags).returncode == 0
    assert git(remote, "show-ref", "--tags") == original
    assert "Existing engine/v1.2.3: target preserved" in (local / "summary").read_text()


@pytest.mark.parametrize(
    "tags",
    [
        [],
        "v1",
        ["good/v1", "bad..ref"],
        ["good/v1", "good/v1"],
        ["good/v1", None],
        ["good", "good/child"],
    ],
)
def test_invalid_complete_plan_creates_no_local_or_remote_tag(repositories, tags):
    local, remote, _ = repositories
    assert publish(repositories, tags).returncode != 0
    assert git(local, "tag", "--list") == ""
    assert git(remote, "tag", "--list") == ""
    assert not (local / "summary").exists()


def test_wrong_checkout_is_rejected_before_tag_creation(repositories):
    local, remote, _ = repositories
    env = dict(
        os.environ,
        RELEASE_TAGS='["engine/v1"]',
        TESTED_SHA="0" * 40,
        GITHUB_STEP_SUMMARY=str(local / "summary"),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=local,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert git(local, "tag", "--list") == git(remote, "tag", "--list") == ""


def test_preexisting_version_at_older_commit_remains_unchanged(repositories):
    local, remote, older = repositories
    assert publish(repositories, ["engine/v1"]).returncode == 0
    original = git(remote, "rev-parse", "refs/tags/engine/v1")
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "next fixture",
    )
    current = git(local, "rev-parse", "HEAD")
    git(local, "push", "-q", "origin", "main")
    assert publish((local, remote, current), ["engine/v1", "other/v2"]).returncode == 0
    assert git(remote, "rev-parse", "refs/tags/engine/v1") == original
    assert git(remote, "rev-parse", "refs/tags/engine/v1^{}") == older
    assert git(remote, "rev-parse", "refs/tags/other/v2^{}") == current


def test_remote_rejection_prevents_partial_publication(repositories):
    local, remote, _ = repositories
    hook = remote / "hooks/update"
    hook.write_text('#!/bin/sh\n[ "$1" != refs/tags/refused/v2 ]\n')
    hook.chmod(0o755)
    result = publish(repositories, ["allowed/v1", "refused/v2"])
    assert result.returncode != 0
    assert git(remote, "tag", "--list") == ""
    assert not (local / "summary").exists()


def test_overlapping_publishers_preserve_winner_and_finish_remaining_tags(
    repositories, tmp_path
):
    first, remote, first_sha = repositories
    second = tmp_path / "second"
    subprocess.run(["git", "clone", "-q", str(first), str(second)], check=True)
    git(second, "remote", "set-url", "origin", str(remote))
    git(
        second,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "second publisher",
    )
    second_sha = git(second, "rev-parse", "HEAD")
    git(second, "push", "-q", "origin", "main")
    install_overlap_hook(first, first_sha, second, tmp_path)
    result = publish((second, remote, second_sha), ["shared/v1", "second/v1"])
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "refs/tags/shared/v1^{}") == first_sha
    assert git(remote, "rev-parse", "refs/tags/first/v1^{}") == first_sha
    assert git(remote, "rev-parse", "refs/tags/second/v1^{}") == second_sha
    assert (second / "attempts").read_text().splitlines() == ["push", "push"]
    summary = (second / "summary").read_text()
    assert "Existing shared/v1: target preserved" in summary
    assert "Published second/v1" in summary


def install_overlap_hook(first, first_sha, second, tmp_path):
    launch = tmp_path / "launch_first.py"
    launch.write_text(
        "import os, subprocess\n"
        f'env=dict(os.environ, RELEASE_TAGS=\'["shared/v1","first/v1"]\', TESTED_SHA={first_sha!r}, '
        f"GITHUB_STEP_SUMMARY={str(first / 'summary')!r})\n"
        f"subprocess.run([{sys.executable!r},{str(SCRIPT)!r}],cwd={str(first)!r},env=env,check=True)\n"
    )
    hook = second / ".git/hooks/pre-push"
    hook.write_text(
        f"#!/bin/sh\necho push >> attempts\nif [ ! -f launched ]; then\n"
        f'  touch launched\n  "{sys.executable}" "{launch}" || exit 1\nfi\n'
    )
    hook.chmod(0o755)


def test_trusted_main_checkout_can_tag_an_older_tested_ancestor(repositories):
    local, remote, older = repositories
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "advance trusted main",
    )
    git(local, "push", "-q", "origin", "main")
    current = git(local, "rev-parse", "HEAD")
    result = publish((local, remote, older), ["engine/v1"])
    assert result.returncode == 0, result.stderr
    assert git(local, "rev-parse", "HEAD") == current
    assert git(remote, "rev-parse", "refs/tags/engine/v1^{}") == older


def test_untrusted_checkout_cannot_publish_even_its_own_tested_sha(repositories):
    local, remote, _ = repositories
    git(local, "checkout", "-q", "-b", "unmerged")
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "outside main",
    )
    untrusted = git(local, "rev-parse", "HEAD")
    result = publish((local, remote, untrusted), ["engine/v1"])
    assert result.returncode != 0
    assert git(local, "tag", "--list") == git(remote, "tag", "--list") == ""


def test_trusted_checkout_rejects_tested_commit_outside_main(repositories):
    local, remote, _ = repositories
    git(local, "checkout", "-q", "-b", "unmerged")
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "outside main",
    )
    untrusted = git(local, "rev-parse", "HEAD")
    git(local, "checkout", "-q", "main")
    result = publish((local, remote, untrusted), ["engine/v1"])
    assert result.returncode != 0
    assert git(local, "tag", "--list") == git(remote, "tag", "--list") == ""


def test_missing_trusted_main_ref_cannot_publish(repositories):
    local, remote, _ = repositories
    git(local, "update-ref", "-d", "refs/remotes/origin/main")
    assert publish(repositories, ["engine/v1"]).returncode != 0
    assert git(local, "tag", "--list") == git(remote, "tag", "--list") == ""


def test_annotated_tag_object_is_not_an_explicit_tested_commit(repositories):
    local, remote, _ = repositories
    git(
        local,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "tag",
        "-a",
        "source-tag",
        "-m",
        "fixture tag",
    )
    tag_object = git(local, "rev-parse", "refs/tags/source-tag")
    result = publish((local, remote, tag_object), ["engine/v1"])
    assert result.returncode != 0
    assert git(remote, "tag", "--list") == ""
    assert git(local, "tag", "--list") == "source-tag"
