"""Actual disposable Git remotes prove package tags and refusal behavior.

Source: git-scm.com/docs/git-push (--atomic); tasks/package-release-tags.md.
No hosted repository, remote network, user identity or product version is changed.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ci_tag.py"


def publish_step():
    workflow = SCRIPT.parents[1] / ".github/workflows/pipeline.yml"
    steps = yaml.safe_load(workflow.read_text())["jobs"]["tag"]["steps"]
    publish = next(step for step in steps if step.get("id") == "publish")
    deploy_key = "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    outside_publish = [step["name"] for step in steps if step is not publish
                       and deploy_key in step.get("env", {}).values()]
    assert not outside_publish, f"write identity available outside publication: {outside_publish}"
    assert publish["env"]["SSH_KEY"] == deploy_key
    return publish["run"]


def executable(path, script):
    path.write_text("#!/bin/sh\nset -eu\n" + script)
    path.chmod(0o700)


def install_transport(root):
    bin_dir = root / "bin"
    bin_dir.mkdir()
    # The real agent's argv names this test's tmp_path, including a detached second agent.
    (bin_dir / "test-agent").symlink_to(shutil.which("ssh-agent"))
    executable(bin_dir / "ssh-agent", '''
if [ "$1" != -k ]; then echo start >> "$RUNNER_TEMP/starts"; fi
exec "$RUNNER_TEMP/bin/test-agent" "$@"
''')
    executable(bin_dir / "ssh-add", '''
if [ "$1" = - ]; then
  printf '%s\\n' "$SSH_AGENT_PID" "$SSH_AUTH_SOCK" > "$RUNNER_TEMP/agent"
fi
exec "$REAL_SSH_ADD" "$@"
''')
    executable(bin_dir / "ssh", '''
"$REAL_SSH" -G "$@" > "$RUNNER_TEMP/ssh-config"
test "$1" = -F && test "$2" = /dev/null || exit 1
for last do :; done
case "$last" in
  "git-upload-pack '/fixture.git'") exec git-upload-pack "$FIXTURE_REMOTE" ;;
  "git-receive-pack '/fixture.git'") exec git-receive-pack "$FIXTURE_REMOTE" ;;
  *) exit 1 ;;
esac
''')
    return str(bin_dir) + os.pathsep + os.environ["PATH"]


@pytest.fixture
def release_case(repositories, tmp_path):
    local, remote, sha = repositories
    # Longer than Linux's 108-byte sockaddr_un.sun_path (unix(7)).
    root = tmp_path / ("long runner path-" * 8)
    root.mkdir()
    identity = root / "fixture"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", identity], check=True)
    key = identity.read_text()
    identity.unlink()
    (root / "github-env").touch()
    (root / "release-known-hosts").touch()
    (root / "tag.sock").write_text("pre-existing runner file")
    git(local, "remote", "set-url", "origin", "ssh://git@release.invalid/fixture.git")
    executable(remote / "hooks/pre-receive", '''
test -z "${SSH_KEY-}"
ssh-add -l > "$RUNNER_TEMP/identities"
ssh-add -T "$RUNNER_TEMP/fixture.pub"
exit "$RECEIVER_STATUS"
''')
    env = dict(PATH=install_transport(root), HOME=str(root), GIT_CONFIG_NOSYSTEM="1",
               RUNNER_TEMP=str(root), SSH_AUTH_SOCK=str(root / "no-agent"), SSH_KEY=key,
               REAL_SSH=shutil.which("ssh"), REAL_SSH_ADD=shutil.which("ssh-add"),
               GIT_SSH_VARIANT="ssh", FIXTURE_REMOTE=str(remote), RELEASE_TAGS='["fixture/v1"]',
               TESTED_SHA=sha, GITHUB_ENV=str(root / "github-env"), GITHUB_STEP_SUMMARY=str(root / "summary"))
    return root, env


def assert_agent_closed(root):
    assert (root / "github-env").stat().st_size == 0, "publish wrote to GITHUB_ENV"
    assert (root / "starts").read_text().splitlines() == ["start"], "additional SSH agent launched"
    pid, address = (root / "agent").read_text().splitlines()
    socket = Path(address)
    assert socket.is_absolute() and not socket.exists(), "publication socket survived"
    assert not socket.parent.exists(), "private socket directory survived"
    assert (root / "tag.sock").read_text() == "pre-existing runner file"
    probe = subprocess.run(["ssh-add", "-l"], env=dict(PATH=os.environ["PATH"], SSH_AUTH_SOCK=address),
                           capture_output=True)
    assert probe.returncode == 2, "SSH agent remained reachable after publication"
    state = subprocess.run(["ps", "-p", str(int(pid)), "-o", "stat="], capture_output=True, text=True)
    assert state.returncode in (0, 1) and not state.stderr, state.stderr
    assert not state.stdout.strip() or state.stdout.strip().startswith("Z"), "publication agent survived"


def assert_ssh_transport(root):
    lines = (root / "ssh-config").read_text().splitlines()
    config = dict(line.split(" ", 1) for line in lines)
    assert config["batchmode"] == "yes"
    assert config["identitiesonly"] == "no", "SSH must offer the dedicated agent identity"
    assert [line for line in lines if line.startswith("identityfile ")] == ["identityfile none"]
    assert config["stricthostkeychecking"] in ("true", "yes")
    assert config["userknownhostsfile"] == str(root / "release-known-hosts")
    assert config["globalknownhostsfile"] == "/dev/null"


@pytest.mark.spawns
@pytest.mark.parametrize("status", [0, 1])
def test_release_credential_lifetime(repositories, release_case, status):
    local, remote, _ = repositories
    root, env = release_case
    result = subprocess.run(["bash", "-eo", "pipefail", "-c", publish_step()], cwd=local,
                            env=dict(env, RECEIVER_STATUS=str(status)), capture_output=True, text=True)
    assert result.returncode == status, result.stderr
    assert_agent_closed(root)
    assert_ssh_transport(root)
    fingerprint = subprocess.check_output(["ssh-keygen", "-lf", root / "fixture.pub"], text=True).split()[1]
    identities = (root / "identities").read_text().splitlines()
    assert len(identities) == 1 and identities[0].split()[1] == fingerprint
    assert git(remote, "tag", "--list") == ("" if status else "fixture/v1")
    for directory in (root, local, remote):
        files = (p for p in directory.rglob("*") if p.is_file() and not p.is_symlink())
        assert not any(env["SSH_KEY"].encode() in p.read_bytes() for p in files)


@pytest.mark.spawns
def test_invalid_release_identity_closes_agent_before_transport(repositories, release_case):
    local, remote, _ = repositories
    root, env = release_case
    result = subprocess.run(["bash", "-eo", "pipefail", "-c", publish_step()], cwd=local,
                            env=dict(env, SSH_KEY="invalid test identity", RECEIVER_STATUS="0"), capture_output=True)
    assert result.returncode == 1 and b"Error loading key" in result.stderr
    assert_agent_closed(root)
    assert not (root / "ssh-config").exists()
    assert git(remote, "tag", "--list") == ""


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
