"""The release write key lives only inside its publish step (SEC-010, CWE-522).

Each test runs the real "Publish declared package tags" body of every distinct copy
(the two active workflows and the three Pipeline templates are byte-identical, which
tests/test_ci_tag_no_checkout.py enforces), through Git's ssh:// transport into a local
receiver, with a hostile ssh configuration in HOME. Harness: release_credential_support.

Cancellation follows actions/runner ProcessInvoker (commit 1060fd3,
src/Runner.Sdk/ProcessInvoker.cs lines 32-33 and 443-464): SIGINT to the step PID
alone, SIGTERM 7.5 s later, then the process tree is killed 2.5 s after that.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from release_credential_support import (
    SUN_PATH_BYTES, Fixture, alive, assert_agent_gone, processes, publish_bodies, wait_until_gone,
)

pytestmark = pytest.mark.spawns

RUNNER_SIGINT_WINDOW_S = 7.5
RUNNER_SIGTERM_WINDOW_S = 2.5
TRANSPORT_EXIT_S = 1.0
OPENSSH_PARENT_CHECK_S = 10  # ssh-agent.c: parent_alive_interval for a command-scoped agent
RELEASE_BOUND_S = 5  # the step's own wait before SIGKILL
BODIES = publish_bodies()


@pytest.fixture(params=BODIES, ids=[label for label, _ in BODIES])
def make(request, tmp_path):
    made = []

    def build(key=None):
        fixture = Fixture(tmp_path / f"case{len(made)}", request.param[1], *([key] if key else []))
        made.append(fixture)
        return fixture

    yield build
    for fixture in made:
        fixture.cleanup()


def assert_transport_ended(record: dict) -> None:
    # Git and its ssh client end on their own once the publisher is gone, as a real
    # client does on EOF; they get TRANSPORT_EXIT_S, the agent gets nothing.
    for pid in (record["pid"], record["parent"]):
        assert wait_until_gone(pid, TRANSPORT_EXIT_S), "a transport process outlived the step"


def assert_socket_released(fixture: Fixture, record: dict) -> None:
    socket = fixture.repo / record["socket"]  # a relative socket resolves from the step directory
    assert len(record["socket"].encode()) < SUN_PATH_BYTES, "the agent can bind its path as given"
    assert socket.parent not in (fixture.repo, fixture.runner_temp), "the socket has its own directory"
    assert_agent_gone(record, fixture.repo, fixture.env)
    assert not socket.exists(), "the agent socket outlived the step"
    assert not socket.parent.exists(), "the socket directory outlived the step"


def assert_nothing_left(fixture: Fixture) -> None:
    roots = (str(fixture.root), str(fixture.socket_base))
    leftovers = [row for row in processes() if not row[2].startswith("Z") and any(r in row[3] for r in roots)]
    assert leftovers == [], "a process of the step outlived it"
    group = [row for row in processes() if row[1] == str(fixture.process.pid) and not row[2].startswith("Z")]
    assert group == [], "a child of the step outlived it"
    assert set(os.listdir(fixture.runner_temp)) == fixture.runner_entries, "the step left files in RUNNER_TEMP"
    assert os.listdir(fixture.socket_base) == [], "the step left files in TMPDIR"
    for name, path in fixture.commands.items():
        assert path.read_text() == "", name + " must not carry anything from this step"
    for path in fixture.root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert fixture.secret_body.encode() not in path.read_bytes(), str(path)


def assert_released(fixture: Fixture) -> None:
    """Nothing that could still use the key outlives the step."""
    assert len(fixture.agent_starts()) == 1, "exactly one signing agent is started"
    for record in fixture.transports():
        assert_socket_released(fixture, record)
        assert_transport_ended(record)
    assert_nothing_left(fixture)


def assert_transport_isolated(fixture: Fixture, record: dict) -> None:
    config = record["config"]
    assert record["key_in_environment"] == "", "the raw key reached the transport"
    assert record["signed"] == "0", "the agent signs with the release identity"
    identities = [line for line in record["config_lines"] if line.startswith("identityfile ")]
    assert identities == ["identityfile none"], "no key file of the runner takes part"
    assert config.get("identitiesonly") == "no", "SSH must offer the dedicated agent identity"
    assert config.get("batchmode") == "yes"
    assert config.get("stricthostkeychecking") in ("true", "yes")
    assert config.get("globalknownhostsfile") == "/dev/null"
    assert config.get("userknownhostsfile") == str(fixture.runner_temp / "release-known-hosts")
    assert "proxycommand" not in config, "the host's ssh configuration reached the transport"


def test_success_publishes_through_git_ssh_and_releases_the_key(make):
    fixture = make()
    fixture.start()
    status, output = fixture.finish()
    assert status == 0, output
    assert fixture.remote_tag() == fixture.sha, output
    transports = fixture.transports()
    assert transports, "Git never ran the configured ssh transport"
    for record in transports:
        assert_transport_isolated(fixture, record)
    assert_released(fixture)


def test_rejected_push_fails_and_releases_the_key(make):
    fixture = make()
    fixture.receiver_hook("echo refused by fixture >&2\nexit 1\n")
    fixture.start()
    status, output = fixture.finish()
    assert status == 1, output
    assert fixture.remote_tag() is None
    assert fixture.transports(), output
    assert_released(fixture)


def test_unusable_key_fails_before_any_transport(make):
    fixture = make(key="not a private key\n")
    fixture.start()
    status, output = fixture.finish()
    assert status != 0, output
    assert fixture.transports() == [], output
    assert_released(fixture)


def cancel(make, sig: int, window: float) -> None:
    fixture = make()
    fixture.start(block=True)
    fixture.wait_ready()
    os.kill(fixture.process.pid, sig)  # the runner signals the step PID, not its group
    try:
        status, output = fixture.finish(timeout=window)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the step did not stop within the runner's {window} s window")
    assert status == 128 + sig, output
    assert fixture.remote_tag() is None
    assert_released(fixture)


def test_runner_sigint_releases_the_key_within_its_window(make):
    cancel(make, signal.SIGINT, RUNNER_SIGINT_WINDOW_S)


def test_runner_sigterm_releases_the_key_within_its_window(make):
    cancel(make, signal.SIGTERM, RUNNER_SIGTERM_WINDOW_S)


def test_second_signal_during_release_does_not_cut_it_short(make):
    """The runner follows SIGINT with SIGTERM; a terminal may send two SIGINTs."""
    fixture = make()
    fixture.start(block=True)
    fixture.wait_ready()
    os.kill(fixture.process.pid, signal.SIGINT)
    time.sleep(0.05)
    os.kill(fixture.process.pid, signal.SIGTERM)
    status, output = fixture.finish(timeout=RUNNER_SIGINT_WINDOW_S)
    assert status == 128 + signal.SIGINT, output
    assert_released(fixture)


def test_agent_that_ignores_sigterm_is_killed_and_fails_the_step(make):
    fixture = make()
    # A stopped agent cannot act on SIGTERM; SIGKILL still ends it.
    fixture.receiver_hook('kill -STOP "$(cat "$FIXTURE_LOG/agent-pid")"\nexit 0\n')
    started = time.monotonic()
    fixture.start()
    try:
        status, output = fixture.finish(timeout=RUNNER_SIGINT_WINDOW_S)
    except subprocess.TimeoutExpired:
        pytest.fail("the release hung on an agent that does not answer SIGTERM")
    assert time.monotonic() - started < RUNNER_SIGINT_WINDOW_S
    assert status == 1, output
    agent = fixture.transports()[0]["agent"]
    assert f"::error::release process {agent} did not stop on SIGTERM" in output
    assert_released(fixture)


def test_an_agent_slow_to_stop_is_given_the_bound_before_sigkill(make):
    """The receiver stops the agent during the push; the test resumes it 2 s later,
    after the release has sent SIGTERM. Pending meanwhile, SIGTERM ends the agent
    inside the 5 s bound: no SIGKILL, no error. (A timer started by the hook would
    hold the push open: Git waits for it, so the test plays the timer.)"""
    fixture = make()
    fixture.receiver_hook('kill -STOP "$(cat "$FIXTURE_LOG/agent-pid")"\n: > "$FIXTURE_LOG/stopped"\nexit 0\n')
    fixture.start()
    deadline = time.monotonic() + 30
    while not (fixture.log / "stopped").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(2)
    agent = int((fixture.log / "agent-pid").read_text())
    assert alive(agent), "the agent was killed before its 5 s bound"
    os.kill(agent, signal.SIGCONT)
    status, output = fixture.finish(timeout=RUNNER_SIGINT_WINDOW_S)
    assert status == 0, output
    assert "did not stop" not in output, output
    assert fixture.remote_tag() == fixture.sha
    assert_released(fixture)


def test_publisher_that_ignores_sigterm_is_killed_within_the_bound(make):
    fixture = make()
    fixture.stuck_publisher()
    fixture.start(block=True)
    fixture.wait_ready()
    record = fixture.transports()[0]
    os.kill(fixture.process.pid, signal.SIGINT)
    try:
        # The killed publisher's own children still hold the step output: the runner
        # kills the tree 2.5 s after its SIGTERM, which finish_leaving_orphans plays.
        status, output = fixture.finish_leaving_orphans(timeout=RUNNER_SIGINT_WINDOW_S)
    except subprocess.TimeoutExpired:
        pytest.fail("the release hung on a publisher that does not answer SIGTERM")
    assert status == 128 + signal.SIGINT, output
    assert "did not stop on SIGTERM" in output, output
    assert f"release process {record['agent']} did not stop" not in output, "the agent answers SIGTERM"
    assert_socket_released(fixture, record)


def test_killed_step_leaves_an_agent_that_stops_by_itself(make):
    """No step code runs after SIGKILL: the agent must be bound to the step's command."""
    fixture = make()
    fixture.start(block=True)
    fixture.wait_ready()
    record = fixture.transports()[0]
    assert record["list"] == "0"
    os.kill(fixture.process.pid, signal.SIGKILL)
    # The publisher and Git survive as orphans until the runner kills the tree;
    # the fixture's cleanup plays that part. Only the agent must not wait for it.
    fixture.process.wait(timeout=5)
    assert wait_until_gone(record["agent"], OPENSSH_PARENT_CHECK_S + 2), \
        "the agent kept the key after the step was killed"
    assert_agent_gone(record, fixture.repo, fixture.env)


def test_agent_gone_requires_a_positive_control_on_the_same_path():
    """Live agent behind a socket path longer than sun_path: ssh-add -l answers 2 by
    absolute path, as for a dead agent. Only a positive control tells them apart."""
    parent = Path(tempfile.mkdtemp(prefix="sun-path-", dir="/tmp"))
    deep = parent / ("d" * (120 - len(str(parent))))
    deep.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(parent)}
    agent = subprocess.Popen(["ssh-agent", "-D", "-a", "./agent"], cwd=deep, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not (deep / "agent").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        socket = str(deep / "agent")
        absolute = subprocess.run(["ssh-add", "-l"], env=dict(env, SSH_AUTH_SOCK=socket), capture_output=True)
        assert alive(agent.pid) and len(socket.encode()) >= SUN_PATH_BYTES and absolute.returncode == 2
        record = {"list": str(absolute.returncode), "socket": socket, "agent": str(agent.pid)}
        with pytest.raises(AssertionError, match="positive control"):
            assert_agent_gone(record, deep, env)
    finally:
        agent.kill()
        agent.wait()
        subprocess.run(["rm", "-rf", str(parent)], check=True)


def test_a_socket_directory_that_cannot_be_removed_fails_the_step(make):
    """The step owns its socket directory: anything else in it is reported, not left silently."""
    fixture = make()
    fixture.receiver_hook('touch "$(dirname "$SSH_AUTH_SOCK")/intruder"\nexit 0\n')
    fixture.start()
    status, output = fixture.finish()
    assert status == 1, output
    record = fixture.transports()[0]
    assert_agent_gone(record, fixture.repo, fixture.env)
    leftover = (fixture.repo / record["socket"]).parent
    assert os.listdir(leftover) == ["intruder"], "only the foreign file remains"
