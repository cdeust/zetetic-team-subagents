"""Contract tests for hooks/post-tool-deletion-gate.py — Tier 2 (PostToolUse)
of the deletion gate: the net for a removal that arrives by any path Tier 1
(PreToolUse on Edit|Write) cannot see (Bash, a whole-file Write, a
multi-step accumulation).

The module is loaded by path: `post-tool-deletion-gate.py` has hyphens and
`hooks/` is not a package. Same technique as test_pre_tool_deletion_gate.py.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "post-tool-deletion-gate.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("post_tool_deletion_gate", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_hook()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def g(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "t")
    return tmp_path


def _commit(repo: Path, message: str = "init") -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True, check=True).stdout.strip()


def _run_main(monkeypatch, event: dict, cwd: Path) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    monkeypatch.chdir(cwd)
    return gate.main()


# ── _resolve_repo_root ───────────────────────────────────────────────────────

def test_resolve_repo_root_finds_the_toplevel(git_repo: Path):
    (git_repo / "sub").mkdir()
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo)
    assert Path(gate._resolve_repo_root(str(git_repo / "sub"))).resolve() == git_repo.resolve()


def test_resolve_repo_root_none_outside_a_repo(tmp_path: Path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert gate._resolve_repo_root(str(outside)) is None


# ── main(): the shape a PreToolUse hook cannot see ──────────────────────────

def test_main_catches_a_bash_originated_removal(git_repo: Path, monkeypatch, capsys):
    """This is the whole point of Tier 2: no Edit/Write tool_input exists
    for a `sed`/`rm`-shaped change, so only reading the real working tree
    catches it."""
    (git_repo / "lib.py").write_text("def emit(x):\n    return x + 1\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(3)\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("")  # the effect of an out-of-band sed/rm

    event = {"tool_name": "Bash", "tool_input": {"command": "sed -i '' '/def emit/,$d' lib.py"}}
    code = _run_main(monkeypatch, event, git_repo)
    err = capsys.readouterr().err
    assert code == 2
    assert "caller.py" in err
    assert "Retired-Because:" in err


def test_main_catches_a_whole_file_write_with_no_old_string(git_repo: Path, monkeypatch, capsys):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x + 1\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(3)\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("# rewritten, emit is gone\n")

    event = {"tool_name": "Write", "tool_input": {"file_path": str(git_repo / "lib.py")}}
    code = _run_main(monkeypatch, event, git_repo)
    assert code == 2
    assert "caller.py" in capsys.readouterr().err


def test_main_passes_when_nothing_was_removed(git_repo: Path, monkeypatch):
    (git_repo / "lib.py").write_text("def keep(x):\n    return x\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("def keep(x):\n    return x + 1\n")
    event = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    assert _run_main(monkeypatch, event, git_repo) == 0


def test_main_passes_a_legitimate_rename_with_no_message(git_repo: Path, monkeypatch):
    """No commit exists yet at PostToolUse time either — require_trailer is
    False for worktree mode, matching --staged's reasoning."""
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("def publish(x):\n    return x\n")
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(git_repo / "lib.py")}}
    assert _run_main(monkeypatch, event, git_repo) == 0


def test_main_ignores_unwatched_tools(git_repo: Path, monkeypatch):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("")
    event = {"tool_name": "Read", "tool_input": {"file_path": str(git_repo / "lib.py")}}
    assert _run_main(monkeypatch, event, git_repo) == 0


def test_main_passes_outside_a_git_repository(tmp_path: Path, monkeypatch):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    event = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert _run_main(monkeypatch, event, not_a_repo) == 0


def test_main_passes_before_any_commit_exists(tmp_path: Path, monkeypatch):
    """No HEAD to diff against is a scope gap (nothing to compare to), not
    an unverifiable removal — must not be conflated with the fail-closed
    path below."""
    repo = tmp_path / "fresh"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "lib.py").write_text("def emit(x):\n    return x\n")
    event = {"tool_name": "Bash", "tool_input": {"command": "touch x"}}
    assert _run_main(monkeypatch, event, repo) == 0


def test_main_fails_closed_when_verification_errors_after_a_removal_is_found(
    git_repo: Path, monkeypatch, capsys
):
    """collect_definitions finds a real removal; evaluate() then hits a git
    error while verifying survivors (e.g. PCRE unsupported) — this must
    BLOCK, not silently allow an unverified removal through."""
    (git_repo / "lib.py").write_text("def emit(x):\n    return x + 1\n")
    _commit(git_repo)
    (git_repo / "lib.py").write_text("")

    def _boom(*_a, **_kw):
        raise gate.dg.GitError("git grep -P unsupported")

    monkeypatch.setattr(gate.dg, "evaluate", _boom)
    event = {"tool_name": "Bash", "tool_input": {"command": "rm-ish"}}
    code = _run_main(monkeypatch, event, git_repo)
    err = capsys.readouterr().err
    assert code == 2
    assert "emit" in err
    assert "git grep -P unsupported" in err


def test_main_fails_open_on_unparseable_stdin(git_repo: Path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    monkeypatch.chdir(git_repo)
    assert gate.main() == 0


# ── message helpers ──────────────────────────────────────────────────────────

def test_indeterminate_reason_names_every_removed_definition():
    removed = [
        gate.dg.Definition("a.py", "emit", "function", "def emit():\n    pass\n"),
        gate.dg.Definition("a.py", "close", "function", "def close():\n    pass\n"),
    ]
    reason = gate._indeterminate_reason(removed, gate.dg.GitError("pcre unsupported"))
    assert "emit" in reason and "close" in reason
    assert "pcre unsupported" in reason
    assert "retry" in reason
