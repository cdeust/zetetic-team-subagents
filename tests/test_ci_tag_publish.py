"""Actual disposable Git remotes prove package tags and refusal behavior.

Source: git-scm.com/docs/git-push (--atomic); tasks/package-release-tags.md.
No hosted repository, remote network, user identity or product version is changed.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ci_tag.py"


@pytest.mark.parametrize("status", [0, 1])
def test_release_credential_lifetime(repositories, status):
    """A real atomic push sees only the fixture key, even when the receiver rejects it."""
    local, remote, sha = repositories
    workflow = SCRIPT.parents[1] / ".github/workflows/pipeline.yml"
    steps = yaml.safe_load(workflow.read_text())["jobs"]["tag"]["steps"]
    publish_step = next(step for step in steps if step.get("id") == "publish")
    deploy_key = "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    outside_publish = [step["name"] for step in steps if step is not publish_step
                       and deploy_key in step.get("env", {}).values()]
    assert not outside_publish, f"write identity available outside publication: {outside_publish}"
    assert publish_step["env"]["SSH_KEY"] == deploy_key
    # Unix-domain socket addresses have a length limit. Avoid pytest's nested case names.
    with tempfile.TemporaryDirectory(prefix="") as runner_temp:
        root = Path(runner_temp)
        identity = root / "fixture"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", identity], check=True)
        fingerprint = subprocess.check_output(["ssh-keygen", "-lf", identity.with_suffix(".pub")],
                                              text=True).split()[1]
        key = identity.read_text()
        identity.unlink()
        witness = remote / "hooks/pre-receive"
        witness.write_text(
            '#!/bin/sh\nset -eu\n'
            'test -z "${SSH_KEY-}"\n'
            'printf "%s" "$SSH_AUTH_SOCK" > "$RUNNER_TEMP/socket"\n'
            'ssh-add -l > "$RUNNER_TEMP/identities"\n'
            'ssh-add -T "$RUNNER_TEMP/fixture.pub"\n'
            'exit "$RECEIVER_STATUS"\n'
        )
        witness.chmod(0o700)
        env = dict(PATH=os.environ["PATH"], HOME=runner_temp, GIT_CONFIG_NOSYSTEM="1",
                   RUNNER_TEMP=runner_temp, SSH_AUTH_SOCK=str(root / "no-agent"),
                   RELEASE_TAGS='["fixture/v1"]', TESTED_SHA=sha,
                   RECEIVER_STATUS=str(status), GITHUB_STEP_SUMMARY=str(root / "summary"))
        env["SSH_KEY"] = key
        result = subprocess.run(["bash", "-eo", "pipefail", "-c", publish_step["run"]], cwd=local, env=env,
                                capture_output=True, text=True)
        assert result.returncode == status, result.stderr
        identities = (root / "identities").read_text().splitlines()
        assert len(identities) == 1, "the receiver did not see the release identity"
        assert identities[0].split()[1] == fingerprint
        assert git(remote, "tag", "--list") == ("" if status else "fixture/v1")
        socket = Path((root / "socket").read_text())
        assert socket.is_absolute()
        probe = subprocess.run(["ssh-add", "-l"], env={"PATH": env["PATH"], "SSH_AUTH_SOCK": str(socket)},
                               capture_output=True)
        assert probe.returncode == 2, "SSH agent remained reachable after publication"
        for directory in (root, local, remote):
            assert not any(key.encode() in p.read_bytes() for p in directory.rglob("*") if p.is_file())


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


def test_the_tag_goes_on_the_tested_commit_whatever_main_is(repositories):
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
        "main moved on",
    )
    git(local, "push", "-q", "origin", "main")
    current = git(local, "rev-parse", "HEAD")
    result = publish((local, remote, older), ["engine/v1"])
    assert result.returncode == 0, result.stderr
    assert git(local, "rev-parse", "HEAD") == current
    assert git(remote, "rev-parse", "refs/tags/engine/v1^{}") == older


def test_the_tag_goes_on_the_commit_the_checkout_built(repositories):
    """The push event built this commit: it is tagged, with no comparison with main (owner rule 2026-10-29)."""
    local, remote, _ = repositories
    git(local, "checkout", "-q", "-b", "built")
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
        "built",
    )
    built = git(local, "rev-parse", "HEAD")
    result = publish((local, remote, built), ["engine/v1"])
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "refs/tags/engine/v1^{}") == built


def test_publication_does_not_read_a_remote_tracking_main(repositories):
    local, remote, _ = repositories
    git(local, "update-ref", "-d", "refs/remotes/origin/main")
    result = publish(repositories, ["engine/v1"])
    assert result.returncode == 0, result.stderr
    assert git(remote, "tag", "--list") == "engine/v1"


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
