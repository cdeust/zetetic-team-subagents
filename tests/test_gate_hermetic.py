"""A verdict is a function of (tree, rules, runner): nothing else the agent can touch decides it.

PR #169 review round 5. Each test is an attack (or a liveness failure) the review demonstrated against the real
hooks, replayed here as subprocesses against a throwaway repository: B2, an untracked `.venv/bin/python` or
`node_modules/.bin` shim, or a variable of the hook's environment (`PYTEST_ADDOPTS`, `CLAUDE_PLUGIN_ROOT`), made a
failing tree green, and a failure under one interpreter was reused under another; B3, two verifications of one tree
deleted each other's private checkout; B1, a ratchet check judged every legacy file.

Event-synchronised only: a worker's end is its process exit (wait_exit), a held check announces itself on a FIFO.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gate_support import GIT_ENV, HOOKS, Gate, git, payload, write_config
from task_support import tasks, wait_exit

COMMIT = 'git commit -m "wip"'
FAILS = {"name": "py", "argv": ["{python}", "-c", "import sys; sys.exit(1)"]}


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    yield g
    g.close()


def declare(g: Gate, checks: list, **extra) -> None:
    """Commit ``checks`` as the repository's rules (outside the hooks, as the owner would)."""
    write_config(g.repo, checks, **extra)
    git(g.repo, "add", "-A")
    git(g.repo, "commit", "-q", "-m", "rules", "--no-verify")


def hook(g: Gate, script: str, command: str, **opts):
    """``script`` run as Claude Code runs it, by the interpreter ``opts["python"]`` (default: this one), with
    ``opts["env"]`` added to the session's environment."""
    python, env = opts.get("python", sys.executable), opts.get("env") or {}
    out = subprocess.run([python, "-B", str(HOOKS / script)], input=json.dumps(payload(command, g.repo)),
                         cwd=str(g.repo), capture_output=True, text=True, env={**os.environ, **GIT_ENV, **g.env, **env})
    return out.returncode, out.stderr


def settle(g: Gate, tree: str) -> dict:
    """Block until the worker verifying ``tree`` has exited (its process exit); return its final record."""
    rec = g.record(tree)
    wait_exit(rec["pid"])
    return g.record(tree)


def verdict_after_staging(g: Gate, env: dict | None = None) -> tuple:
    """Stage a change, let the head start's verification end, then ask the commit hook: (rc, stderr, record)."""
    tree = g.stage("two\n")
    hook(g, "gate-start.py", "git add a.txt", env=env)
    rec = settle(g, tree)
    rc, err = hook(g, "gate-proof.py", COMMIT, env=env)
    return rc, err, rec


def test_a_venv_shim_in_the_working_copy_does_not_turn_a_failing_tree_green(gate):
    declare(gate, [FAILS])
    shim = gate.repo / ".venv" / "bin" / "python"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\nexit 0\n")  # untracked: what an agent can write in its own working copy
    shim.chmod(0o755)
    rc, err, rec = verdict_after_staging(gate)
    assert rec["state"] == "failed" and rc == 2 and "verification FAILED" in err


def test_pytest_addopts_in_the_hooks_environment_does_not_disarm_the_tests(gate):
    (gate.repo / "test_a.py").write_text("def test_a():\n    assert 1 + 1 == 3\n")
    declare(gate, [{"name": "tests", "argv": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_a.py"]}])
    rc, err, rec = verdict_after_staging(gate, {"PYTEST_ADDOPTS": "--collect-only"})
    assert rec["state"] == "failed" and rc == 2 and "verification FAILED" in err


def test_claude_plugin_root_in_the_hooks_environment_does_not_reach_the_checks(gate):
    declare(gate, [{"name": "env", "argv": ["sh", "-c", 'test -z "${CLAUDE_PLUGIN_ROOT+set}"']}])
    rc, err, rec = verdict_after_staging(gate, {"CLAUDE_PLUGIN_ROOT": str(HOOKS.parent)})  # Claude Code exports it
    assert rec["state"] == "done" and rc == 0, err


def test_node_modules_in_the_working_copy_is_not_the_npm_suites_runner(gate, tmp_path):
    """The npm stack default ran `npm test` with the working copy's node_modules linked in. A stub npm that does
    what npm does with a test script (node_modules/.bin first on PATH) stands in for npm itself."""
    (gate.repo / ".zetetic" / "gate.json").unlink()
    (gate.repo / "package.json").write_text('{"scripts": {"test": "mytest"}}\n')
    git(gate.repo, "add", "-A")
    git(gate.repo, "commit", "-q", "-m", "an npm project", "--no-verify")
    stub = tmp_path / "bin" / "npm"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\nPATH="$PWD/node_modules/.bin:$PATH" exec mytest\n')
    stub.chmod(0o755)
    shim = gate.repo / "node_modules" / ".bin" / "mytest"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\nexit 0\n")
    shim.chmod(0o755)
    rc, err, rec = verdict_after_staging(gate, {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}"})
    assert rec["state"] == "failed" and rc == 2 and "verification FAILED" in err


def test_a_verdict_is_never_reused_under_another_interpreter(gate, tmp_path):
    """p13: a check that passes only under one interpreter. Its failure under the other must not be the cached
    verdict of the tree: the interpreter is part of the key, so asking under the right one verifies again."""
    other = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(other)], check=True, capture_output=True)
    python = str(other / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python"))
    declare(gate, [{"name": "py", "argv": ["{python}", "-c", f"import sys; sys.exit(sys.executable != {python!r})"]}])
    tree = gate.stage("two\n")
    hook(gate, "gate-start.py", "git add a.txt")
    first = settle(gate, tree)
    rc, err = hook(gate, "gate-proof.py", COMMIT, python=python)
    assert first["state"] == "failed" and rc == 2 and "verification started" in err, err
    again = [p for p in gate.state.glob(f"gate-commit-{tree}-*.json") if p.stem != first["id"]]
    assert len(again) == 1
    wait_exit(tasks.status(again[0].stem, str(gate.repo))["pid"])
    assert hook(gate, "gate-proof.py", COMMIT, python=python)[0] == 0


def test_an_interpreter_that_lives_in_the_repository_is_refused(gate):
    declare(gate, [{"name": "py", "argv": ["{python}", "-c", "pass"]}])
    venv = gate.repo / ".venv"  # untracked, created after the rules were committed
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True)
    gate.stage("two\n")
    rc, err = hook(gate, "gate-proof.py", COMMIT, python=str(venv / "bin" / "python"))
    assert rc == 2 and "imports from the repository" in err and not list(gate.state.glob("gate-*.json"))


HOLDER = (
    'if mkdir "$D/claim1" 2>/dev/null; then who=1; else who=2; fi\n'
    'exec 3<"$D/hold$who"\n'
    'echo "$who" > "$D/ready"\n'
    "cat <&3 >/dev/null\n"
    'for f in "$@"; do [ -f "$f" ] || continue; if grep -q BAD "$f"; then exit 1; fi; done\n'
)  # a check that skips a file it cannot find, as tools/craftsmanship-checker.sh does: it passes an emptied checkout


class Holds:
    """Two FIFOs a held check blocks on, one per verification, and the READY line each check writes."""

    def __init__(self, root: Path):
        self.root = root
        self.fds = {}
        for name in ("ready", "hold1", "hold2"):
            os.mkfifo(root / name)
            self.fds[name] = os.open(root / name, os.O_RDWR)

    def ready(self) -> str:
        line = b""
        while not line.endswith(b"\n"):
            line += os.read(self.fds["ready"], 1)
        return line.decode().strip()

    def release(self, n: int) -> None:
        os.close(self.fds.pop(f"hold{n}"))

    def close(self) -> None:
        for fd in self.fds.values():
            os.close(fd)


def test_two_verifications_of_one_tree_never_delete_each_others_checkout(gate, tmp_path):
    """B3. The commit task and the push task of one tree under two keys run at once; each check holds, then reads
    its own checkout. A worker that removes the directory of another lets a failing tree through twice."""
    holds_dir = tmp_path / "holds"
    holds_dir.mkdir()
    holds = Holds(holds_dir)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(gate.repo, "remote", "add", "origin", str(remote))
    declare(gate, [{"name": "no-bad", "paths": ["*.txt"], "argv": ["sh", "-c", HOLDER, "gate", "{files}"]}],
            env={"D": str(holds_dir)})
    try:
        tree = gate.stage("BAD: this tree fails its check\n")
        hook(gate, "gate-start.py", "git add a.txt", env={"LANG": "C"})
        assert holds.ready() == "1"
        git(gate.repo, "branch", "side", git(gate.repo, "commit-tree", tree, "-p", "HEAD", "-m", "same tree"))
        hook(gate, "gate-proof.py", "git push origin side", env={"LANG": "en_US.UTF-8"})  # another key, same tree
        assert holds.ready() == "2"
        ids = sorted(p.stem for p in gate.state.glob(f"gate-*{tree}-*.json"))
        assert len(ids) == 2
        holds.release(1)
        holds.release(2)
        finals = [tasks.status(i, str(gate.repo)) for i in ids]
        for rec in finals:
            wait_exit(rec["pid"])
        assert [tasks.status(i, str(gate.repo))["state"] for i in ids] == ["failed", "failed"]
    finally:
        holds.close()


def test_a_ratchet_check_judges_the_files_a_change_adds_even_in_full_mode(gate):
    """B1. Legacy debt in a tracked file: a check scoped to added files (CI's ratchet) passes a change to that file,
    even when nothing vouches for the base (full mode), and fails a change that adds a file with the same debt."""
    (gate.repo / "legacy.txt").write_text("DEBT\n")
    declare(gate, [{"name": "ratchet", "paths": ["*.txt"], "scope": "added",
                    "argv": ["sh", "-c", 'for f in "$@"; do ! grep -q DEBT "$f" || exit 1; done', "gate", "{files}"]}])
    (gate.repo / "legacy.txt").write_text("DEBT, still, after an unrelated edit\n")
    git(gate.repo, "add", "legacy.txt")
    tree = git(gate.repo, "write-tree")
    hook(gate, "gate-start.py", "git add legacy.txt")
    assert settle(gate, tree)["state"] == "done" and hook(gate, "gate-proof.py", COMMIT)[0] == 0
    (gate.repo / "new.txt").write_text("DEBT\n")
    git(gate.repo, "add", "new.txt")
    tree = git(gate.repo, "write-tree")
    hook(gate, "gate-start.py", "git add new.txt")
    assert settle(gate, tree)["state"] == "failed" and hook(gate, "gate-proof.py", COMMIT)[0] == 2
