"""`memory-tool.sh scopes` lists every scope with ONE python process, not two per scope.

Measured 2026-10-14: 38 scopes cost 4.4 s of the SessionStart hook (limit 3 s),
all of it interpreter start-ups and `find`s. The listing itself must not change.
"""

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest
from leak_support import stop_pii_daemon

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "memory-tool.sh"


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


def _memory(tmp_path):
    root = tmp_path / "memories"
    for scope, files in {"alpha": {"a.md": "12345", ".hidden": "xx"}, "beta": {"b.md": "1"},
                         "_private": {"p.md": "1"}, "gamma": {}}.items():
        (root / scope).mkdir(parents=True)
        for name, body in files.items():
            (root / scope / name).write_text(body)
    (root / "alpha" / ".dir").mkdir()
    (root / "alpha" / ".dir" / "inside.md").write_text("abc")  # counted: only the file name is tested
    (root / "alpha" / "link.md").symlink_to(root / "beta" / "b.md")  # a symlink is not a regular file
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "defaults": {"owners": ["_user"], "readers": ["*"]},
        "scopes": {"alpha": {"owners": ["worker"], "readers": ["*"]},
                   "beta": {"owners": ["_user"], "readers": ["_user"]}},
    }))
    return root, registry


def _shim(tmp_path):
    """A `python3` first on PATH that logs each start and then runs the real one."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    log = tmp_path / "python-starts"
    shim = shim_dir / "python3"
    shim.write_text(f'#!/bin/sh\necho start >> "{log}"\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return shim_dir, log


def test_scopes_listing_and_one_interpreter(tmp_path):
    root, registry = _memory(tmp_path)
    shim_dir, log = _shim(tmp_path)
    env = {**os.environ, "MEMORY_ROOT": str(root), "MEMORY_REGISTRY": str(registry),
           "MEMORY_AGENT_ID": "worker", "PATH": f"{shim_dir}:{os.environ['PATH']}"}
    out = subprocess.run([str(TOOL), "scopes"], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.splitlines() == [
        "SCOPE                   FILES    BYTES  ACCESS",
        "/memories/alpha             2       8B  rw",
        "/memories/beta              1       1B  none",
        "/memories/gamma             0       0B  r",
    ]
    assert log.read_text().count("start") == 1


# -- the ACL decision itself: a security boundary, every token and the strict mode ----------
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import memory_acl  # noqa: E402

import pytest  # noqa: E402

REGISTRY = {
    "curator_agents": ["librarian"],
    "defaults": {"owners": ["_user"], "readers": ["*"]},
    "scopes": {
        "open": {"owners": ["*"], "readers": ["*"]},
        "named": {"owners": ["worker"], "readers": ["worker"]},
        "curated": {"owners": ["_curator"], "readers": ["_curator"]},
        "user-only": {"owners": ["_user"], "readers": ["_user"]},
    },
}


@pytest.mark.parametrize("scope, access, agent, expected", [
    ("open", "write", "anyone", True),            # "*" matches every agent
    ("named", "read", "worker", True),            # exact agent id
    ("named", "read", "other", False),
    ("named", "write", "other", False),
    ("curated", "write", "librarian", True),      # _curator expands to curator_agents
    ("curated", "read", "worker", False),
    ("user-only", "read", "_user", True),         # _user matches only the user
    ("user-only", "read", "librarian", False),
    ("unlisted", "read", "anyone", True),         # absent scope takes defaults.readers
    ("unlisted", "write", "_user", True),         # ... and defaults.owners
    ("unlisted", "write", "worker", False),
])
def test_allowed(scope, access, agent, expected):
    assert memory_acl.allowed(REGISTRY, scope, access, agent) is expected


def test_strict_unknown_scope_denies_writes_to_unlisted_scopes_only():
    strict = {**REGISTRY, "strict_unknown_scope": True}
    assert memory_acl.allowed(strict, "unlisted", "write", "_user") is False
    assert memory_acl.allowed(strict, "unlisted", "read", "anyone") is True
    assert memory_acl.allowed(strict, "open", "write", "anyone") is True


def test_registry_without_defaults_falls_back_to_user_owned_world_readable():
    bare = {"scopes": {}}
    assert memory_acl.allowed(bare, "any", "read", "worker") is True
    assert memory_acl.allowed(bare, "any", "write", "worker") is False
    assert memory_acl.allowed(bare, "any", "write", "_user") is True


def test_scopes_with_acl_disabled_are_open_to_everyone(tmp_path):
    root, _ = _memory(tmp_path)
    env = {**os.environ, "MEMORY_ROOT": str(root), "MEMORY_NO_ACL": "1",
           "MEMORY_AGENT_ID": "worker"}
    out = subprocess.run([str(TOOL), "scopes"], env=env, capture_output=True, text=True, check=True)
    assert [line.split()[-1] for line in out.stdout.splitlines()[1:]] == ["rw", "rw", "rw"]


@pytest.fixture
def pii_daemon_stopped(tmp_path):
    """The first write through the tool starts a PII daemon for the root; stop it afterwards.

    It is long-lived by design (one per MEMORY_ROOT, idle exit after 30 s), so the test that
    drove the tool stops it through the documented path: SIGTERM to its pid sidecar.
    """
    yield
    stop_pii_daemon(tmp_path / "memories")


def test_acl_check_gates_writes_through_the_tool(tmp_path, pii_daemon_stopped):
    root, registry = _memory(tmp_path)
    env = {**os.environ, "MEMORY_ROOT": str(root), "MEMORY_REGISTRY": str(registry)}
    body = '---\ndescription: "t"\n---\nx'

    def create(agent, scope):
        run = subprocess.run([str(TOOL), "create", f"/memories/{scope}/new.md", body],
                             env={**env, "MEMORY_AGENT_ID": agent}, capture_output=True, text=True)
        return run.stdout

    assert "not permitted to write" in create("worker", "beta")
    assert "File created successfully" in create("worker", "alpha")
