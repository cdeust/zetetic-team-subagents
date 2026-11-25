"""Native harness for the "Publish declared package tags" step (SEC-010).

It runs the real step body as actions/runner does (`bash --noprofile --norc -eo
pipefail {0}`), with the real OpenSSH agent, and drives Git's SSH transport (an
ssh:// URL and GIT_SSH_COMMAND) into a local receiver. Only a fixture key generated
here is ever loaded. Used by tests/test_ci_release_credential_lifetime.py.

A probe that reports "agent gone" proves nothing unless the same probe first reached
the live agent: `ssh-add -l` also answers 2 when the socket path exceeds sun_path (104
bytes on macOS, 108 on Linux). The transport therefore records a positive control,
taken on the same socket path from the same directory, while the agent is alive.

RELEASE_CREDENTIAL_WORKFLOWS (paths joined by os.pathsep) replaces the workflows under
test, so the same proof replays on another revision (tests/replay_release_credentials.py).
Design source: ai-architect-mcp-spec d1ce975/5098df7, adapted to this repository.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_WORKFLOWS = (
    ".github/workflows/pipeline.yml",
    ".github/workflows/pipeline-post-merge.yml",
    "templates/ci/pipeline.yml",
    "templates/ci/native/pipeline.yml",
    "templates/ci/native/generated/pipeline.yml",
)
TAG = "fixture/v1"
SUN_PATH_BYTES = 104  # the smaller platform limit, terminating NUL included
DEFAULT_KEY = object()

HOSTILE_SSH_CONFIG = """Host *
  ProxyCommand /usr/bin/false
  IdentitiesOnly yes
  IdentityFile ~/.ssh/host-identity
  BatchMode no
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
"""

# Stand-in for the ssh client Git runs: records the effective client configuration and
# the agent it was given (the positive control), then serves Git against the receiver.
SSH_WRAPPER = """#!/bin/sh
set -u
log="$FIXTURE_LOG/ssh.$$"
# OpenSSH reads ~/.ssh/config from the passwd entry, not from $HOME: the host's
# configuration is given first with -F, and a later -F of the step replaces it.
"$FIXTURE_REAL_SSH" -F "$FIXTURE_HOST_CONFIG" -G "$@" > "$log.config" 2>&1
{
  echo "pid=$$"
  echo "parent=$PPID"
  echo "socket=${SSH_AUTH_SOCK-}"
  echo "agent=${SSH_AGENT_PID-}"
  echo "key_in_environment=${SSH_KEY+yes}"
  ssh-add -l >/dev/null 2>&1; echo "list=$?"
  ssh-add -T "$FIXTURE_PUBLIC_KEY" >/dev/null 2>&1; echo "signed=$?"
} > "$log.env"
printf '%s' "${SSH_AGENT_PID-}" > "$FIXTURE_LOG/agent-pid"
: > "$log.ready"
if [ -n "${FIXTURE_BLOCK-}" ]; then
  # A blocked transport hangs until Git goes away, then ends as a real client would.
  while kill -0 "$PPID" 2>/dev/null; do sleep 0.05; done
  exit 255
fi
grep -qx signed=0 "$log.env" || exit 255
for command; do :; done
exec sh -c "$command"
"""

# argv[0] of the real agent then names the test's directory, which the leak guard
# of tests/conftest.py watches.
AGENT_WRAPPER = """#!/bin/sh
printf '%s\\n' "${1-}" >> "$FIXTURE_LOG/agent-starts"
exec "$FIXTURE_BIN/real-ssh-agent" "$@"
"""

# A publisher that no longer answers SIGTERM (it stays in the foreground of a shell
# that ignores it), to prove the release bound covers the publisher too.
STUCK_PUBLISHER = """#!/bin/sh
trap '' TERM
"$FIXTURE_REAL_PYTHON" "$@"
"""


def workflows() -> tuple[Path, ...]:
    override = os.environ.get("RELEASE_CREDENTIAL_WORKFLOWS", "")
    paths = [Path(p) for p in override.split(os.pathsep) if p]
    return tuple(paths) or tuple(ROOT / p for p in REPOSITORY_WORKFLOWS)


def publish_body(path: Path) -> str:
    steps = yaml.safe_load(path.read_text())["jobs"]["tag"]["steps"]
    return next(step for step in steps if step.get("id") == "publish")["run"]


def publish_bodies() -> list[tuple[str, str]]:
    """Distinct step bodies, each labelled by the first copy carrying it."""
    seen = {}
    for path in workflows():
        seen.setdefault(publish_body(path), path.name if path.is_absolute() else str(path))
    return [(label, body) for body, label in seen.items()]


def alive(pid: int) -> bool:
    """A zombie has released its memory, sockets and keys: it is not alive."""
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = out.stdout.strip()
    return out.returncode == 0 and state != "" and not state.startswith("Z")


def processes() -> list[list[str]]:
    rows = subprocess.run(["ps", "-ww", "-Ao", "pid=,pgid=,stat=,args="], capture_output=True,
                          text=True, check=True).stdout.splitlines()
    return [row.split(None, 3) for row in rows if len(row.split(None, 3)) == 4]


def kill(pid) -> None:
    try:
        os.kill(int(pid), signal.SIGKILL)
    except (ProcessLookupError, ValueError):
        pass


def kill_group(leader: int) -> None:
    """macOS answers EPERM, not ESRCH, for a group whose leader is an unreaped zombie."""
    try:
        os.killpg(leader, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def git(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, **kwargs)


def executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o700)


def wait_until_gone(pid, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while alive(int(pid)) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not alive(int(pid))


def assert_agent_gone(record: dict, cwd: Path, env: dict) -> None:
    """The agent is gone only if the probe that reached it alive no longer does."""
    assert record["list"] == "0", "positive control: the transport never reached the live agent"
    probe = subprocess.run(["ssh-add", "-l"], cwd=cwd, capture_output=True,
                           env=dict(env, SSH_AUTH_SOCK=record["socket"]))
    assert probe.returncode == 2, "the same probe that reached the agent still does"
    assert not alive(int(record["agent"])), "the signing agent outlived the step"


class Fixture:
    """One step run: fixture key, hostile ssh configuration, receiver and runner files."""

    def __init__(self, root: Path, body: str, key=DEFAULT_KEY):
        self.root = root
        self.process = None
        root.mkdir()
        self.log = root / "log"
        self.log.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self._keys()
        self._runner()
        self._repositories()
        (root / "step.sh").write_text(body)
        # TMPDIR holds the agent socket; sun_path forbids a deep directory. Created
        # last, so a failed setup leaves nothing outside the test's directory.
        self.socket_base = Path(tempfile.mkdtemp(prefix="sec010-", dir="/tmp"))
        self.env = self._environment(key)
        self.runner_entries = set(os.listdir(self.runner_temp))

    def _keys(self) -> None:
        keys = self.root / "keys"
        keys.mkdir()
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "fixture", "-f", keys / "id"],
                       check=True)
        self.private = (keys / "id").read_text()
        (keys / "id").unlink()
        self.secret_body = self.private.splitlines()[1]
        self.public = keys / "id.pub"

    def _runner(self) -> None:
        self.runner_temp = self.root / "runner"
        self.runner_temp.mkdir()
        kind, blob = self.public.read_text().split(" ", 2)[:2]
        (self.runner_temp / "release-known-hosts").write_text(f"github.invalid {kind} {blob}\n")
        home = self.root / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "config").write_text(HOSTILE_SSH_CONFIG)
        executable(self.bin / "ssh", SSH_WRAPPER)
        executable(self.bin / "ssh-agent", AGENT_WRAPPER)
        (self.bin / "real-ssh-agent").symlink_to(shutil.which("ssh-agent"))
        self.commands = {name: self.root / name for name in ("github-env", "github-output", "github-path")}
        for path in self.commands.values():
            path.touch()

    def _repositories(self) -> None:
        work = self.root / "work"
        git("init", "-q", str(work))
        (work / "file").write_text("release fixture\n")
        git("-C", str(work), "add", "file")
        git("-C", str(work), "-c", "user.name=f", "-c", "user.email=f@f", "commit", "-q", "-m", "fixture")
        self.sha = git("-C", str(work), "rev-parse", "HEAD").stdout.strip()
        self.remote = self.root / "remote.git"
        git("init", "-q", "--bare", str(self.remote))
        self.repo = self.runner_temp / "release-repo"
        git("init", "-q", "--bare", str(self.repo))
        git("-C", str(self.repo), "fetch", "-q", str(work), self.sha)
        git("-C", str(self.repo), "remote", "add", "origin", "ssh://git@github.invalid" + str(self.remote))

    def _environment(self, key) -> dict:
        return {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "HOME": str(self.root / "home"), "TMPDIR": str(self.socket_base), "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "RUNNER_TEMP": str(self.runner_temp),
            "SSH_KEY": self.private if key is DEFAULT_KEY else key,
            "RELEASE_TAGS": '["' + TAG + '"]', "TESTED_SHA": self.sha,
            "GITHUB_ENV": str(self.commands["github-env"]),
            "GITHUB_OUTPUT": str(self.commands["github-output"]),
            "GITHUB_PATH": str(self.commands["github-path"]),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "FIXTURE_LOG": str(self.log), "FIXTURE_BIN": str(self.bin),
            "FIXTURE_PUBLIC_KEY": str(self.public), "FIXTURE_REAL_SSH": shutil.which("ssh"),
            "FIXTURE_REAL_PYTHON": shutil.which("python3"),
            "FIXTURE_HOST_CONFIG": str(self.root / "home" / ".ssh" / "config"),
        }

    def stuck_publisher(self) -> None:
        executable(self.bin / "python3", STUCK_PUBLISHER)

    def receiver_hook(self, body: str) -> None:
        executable(self.remote / "hooks" / "pre-receive", "#!/bin/sh\n" + body)

    def start(self, block: bool = False) -> subprocess.Popen:
        env = dict(self.env, **({"FIXTURE_BLOCK": "1"} if block else {}))
        # actions/runner runs `shell: bash` as: bash --noprofile --norc -eo pipefail {0}
        self.process = subprocess.Popen(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(self.root / "step.sh")],
            cwd=self.repo, env=env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return self.process

    def finish(self, timeout: float = 60) -> tuple[int, str]:
        output, _ = self.process.communicate(timeout=timeout)
        return self.process.returncode, output

    def finish_leaving_orphans(self, timeout: float) -> tuple[int, str]:
        """Wait for the step itself; orphans that still hold its output are then killed."""
        status = self.process.wait(timeout=timeout)
        kill_group(self.process.pid)
        return status, self.process.stdout.read()

    def transports(self) -> list[dict]:
        result = []
        for env_file in sorted(self.log.glob("ssh.*.env")):
            record = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
            config = Path(str(env_file)[:-len(".env")] + ".config").read_text().splitlines()
            record["config_lines"] = config
            record["config"] = {k: v for k, _, v in (line.partition(" ") for line in config)}
            result.append(record)
        return result

    def agent_starts(self) -> list[str]:
        starts = self.log / "agent-starts"
        lines = starts.read_text().splitlines() if starts.exists() else []
        return [first for first in lines if first != "-k"]

    def wait_ready(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if list(self.log.glob("ssh.*.ready")):
                return
            if self.process.poll() is not None:
                raise AssertionError("step exited before its transport started: " + self.process.stdout.read())
            time.sleep(0.05)
        raise AssertionError("transport never started")

    def remote_tag(self):
        out = subprocess.run(["git", "--git-dir", str(self.remote), "rev-parse", "--verify", "-q",
                              "refs/tags/" + TAG + "^{}"], capture_output=True, text=True)
        return out.stdout.strip() or None

    def cleanup(self) -> None:
        """Plays the runner's final tree kill; also reaps a stopped agent of an older design."""
        try:
            self._kill_everything()
        finally:
            shutil.rmtree(self.socket_base, ignore_errors=True)

    def _kill_everything(self) -> None:
        if self.process is not None:
            kill_group(self.process.pid)
            self.process.stdout.close()
        agents = [record["agent"] for record in self.transports()]
        if (self.log / "agent-pid").exists():
            agents.append((self.log / "agent-pid").read_text())
        for pid in agents:
            kill(pid)
        for record in self.transports():
            directory = (self.repo / record["socket"]).parent
            if directory.name.startswith("release-agent.") and directory not in (self.repo, self.runner_temp):
                shutil.rmtree(directory, ignore_errors=True)
        for pid, _, _, args in processes():
            if (str(self.root) in args or str(self.socket_base) in args) and int(pid) != os.getpid():
                kill(pid)
