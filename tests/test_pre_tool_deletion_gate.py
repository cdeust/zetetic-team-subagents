"""Contract tests for hooks/pre-tool-deletion-gate.py — the PreToolUse
Tier 1 of the deletion gate (tools/deletion_gate.py owns the mechanism;
this hook is a caller of it — coding-standards.md S1.2).

The module is loaded by path: `pre-tool-deletion-gate.py` has hyphens and
`hooks/` is not a package, so there is no dotted import for it. Same
technique as tests/test_secret_shield.py and tests/test_context_guard.py.
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
HOOK_PATH = REPO_ROOT / "hooks" / "pre-tool-deletion-gate.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("pre_tool_deletion_gate", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_hook()


# ── fixtures ─────────────────────────────────────────────────────────────────

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


def _run_main(monkeypatch, event: dict) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    return gate.main()


# ── _post_image ──────────────────────────────────────────────────────────────

def test_post_image_write_returns_content():
    assert gate._post_image("Write", {"content": "x = 1\n"}, None) == "x = 1\n"


def test_post_image_write_rejects_a_non_string_content():
    assert gate._post_image("Write", {"content": 5}, None) is None


def test_post_image_edit_replaces_old_with_new():
    pre = "def emit(x):\n    return x\n"
    post = gate._post_image("Edit", {"old_string": "def emit(x):", "new_string": "def emit_v2(x):"}, pre)
    assert post == "def emit_v2(x):\n    return x\n"


def test_post_image_edit_replace_all_replaces_every_occurrence():
    pre = "a a a\n"
    post = gate._post_image("Edit", {"old_string": "a", "new_string": "b", "replace_all": True}, pre)
    assert post == "b b b\n"


def test_post_image_edit_returns_none_when_old_string_not_found():
    pre = "def emit(x):\n    return x\n"
    assert gate._post_image("Edit", {"old_string": "nope", "new_string": "x"}, pre) is None


def test_post_image_edit_returns_none_without_a_pre_image():
    assert gate._post_image("Edit", {"old_string": "a", "new_string": "b"}, None) is None


def test_post_image_unknown_tool_returns_none():
    assert gate._post_image("Bash", {}, "x") is None


# ── _removed_definitions ─────────────────────────────────────────────────────

def test_removed_definitions_finds_the_diff():
    pre = "def emit(x):\n    return x\ndef keep(y):\n    return y\n"
    post = "def keep(y):\n    return y\n"
    removed = gate._removed_definitions(pre, post, "python")
    assert set(removed) == {"emit"}


def test_removed_definitions_empty_when_nothing_removed():
    text = "def keep(y):\n    return y\n"
    assert gate._removed_definitions(text, text, "python") == {}


def test_removed_definitions_pre_none_means_nothing_could_be_removed():
    assert gate._removed_definitions(None, "def a():\n    pass\n", "python") == {}


# ── _resolve_repo_root / _repo_relative ──────────────────────────────────────

def test_resolve_repo_root_finds_the_toplevel(git_repo: Path):
    (git_repo / "sub").mkdir()
    (git_repo / "sub" / "f.py").write_text("x = 1\n")
    _commit(git_repo)
    root = gate._resolve_repo_root(str(git_repo / "sub" / "f.py"))
    assert Path(root).resolve() == git_repo.resolve()


def test_resolve_repo_root_falls_back_to_the_parent_dir_outside_git(tmp_path: Path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    (outside / "f.py").write_text("x = 1\n")
    assert gate._resolve_repo_root(str(outside / "f.py")) == str(outside)


def test_repo_relative_returns_the_relative_path(git_repo: Path):
    (git_repo / "lib.py").write_text("x = 1\n")
    rel = gate._repo_relative(str(git_repo), str(git_repo / "lib.py"))
    assert rel == "lib.py"


def test_repo_relative_falls_back_to_the_input_when_not_under_repo(tmp_path: Path):
    other = tmp_path / "elsewhere.py"
    assert gate._repo_relative(str(tmp_path / "repo"), str(other)) == str(other)


# ── _block_reason ────────────────────────────────────────────────────────────

def test_block_reason_names_a_surviving_caller(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    _commit(git_repo)
    removed = {"emit": ("function", "def emit(x):\n    return x\n")}
    reason = gate._block_reason(str(git_repo), "lib.py", "python", removed)
    assert reason is not None
    assert "caller.py" in reason
    assert "lib.py::emit" in reason


def test_block_reason_none_when_no_survivors(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    _commit(git_repo)
    removed = {"orphan": ("function", "def orphan(x):\n    return x\n")}
    assert gate._block_reason(str(git_repo), "lib.py", "python", removed) is None


# ── _emit_block ──────────────────────────────────────────────────────────────

def test_emit_block_returns_2_and_prints_the_reason(capsys):
    assert gate._emit_block("removing lib.py::emit would leave 1 caller") == 2
    err = capsys.readouterr().err
    assert "removing lib.py::emit" in err
    assert "Retired-Because:" in err


# ── _target_edit ─────────────────────────────────────────────────────────────

def test_target_edit_accepts_edit_and_write():
    fp, lang, tool, tin = gate._target_edit(
        {"tool_name": "Edit", "tool_input": {"file_path": "lib.py"}}
    )
    assert (fp, lang, tool) == ("lib.py", "python", "Edit")
    assert tin == {"file_path": "lib.py"}


def test_target_edit_rejects_other_tools():
    fp, *_ = gate._target_edit({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert fp is None


def test_target_edit_rejects_unrecognized_language():
    fp, *_ = gate._target_edit({"tool_name": "Edit", "tool_input": {"file_path": "README.md"}})
    assert fp is None


def test_target_edit_rejects_a_test_path():
    fp, *_ = gate._target_edit(
        {"tool_name": "Edit", "tool_input": {"file_path": "tests/test_thing.py"}}
    )
    assert fp is None


def test_target_edit_rejects_missing_file_path():
    fp, *_ = gate._target_edit({"tool_name": "Edit", "tool_input": {}})
    assert fp is None


def test_target_edit_rejects_non_dict_tool_input():
    fp, *_ = gate._target_edit({"tool_name": "Edit", "tool_input": "oops"})
    assert fp is None


# ── main(): end to end via stdin ─────────────────────────────────────────────

def test_main_blocks_when_a_caller_would_be_stranded(git_repo: Path, monkeypatch, capsys):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x + 1\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(3)\n")
    _commit(git_repo)
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(git_repo / "lib.py"),
            "old_string": "def emit(x):\n    return x + 1\n",
            "new_string": "",
        },
    }
    code = _run_main(monkeypatch, event)
    err = capsys.readouterr().err
    assert code == 2
    assert "caller.py" in err


def test_main_passes_when_no_definition_is_removed(git_repo: Path, monkeypatch):
    (git_repo / "lib.py").write_text("def keep(x):\n    return x\n")
    _commit(git_repo)
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(git_repo / "lib.py"),
            "old_string": "return x",
            "new_string": "return x + 1",
        },
    }
    assert _run_main(monkeypatch, event) == 0


def test_main_passes_for_a_write_with_no_prior_file(git_repo: Path, monkeypatch):
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(git_repo / "new.py"), "content": "def a():\n    pass\n"},
    }
    assert _run_main(monkeypatch, event) == 0


def test_main_fails_open_on_unparseable_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert gate.main() == 0


def test_main_fails_open_when_stdin_read_raises(monkeypatch):
    class Exploding:
        def read(self):
            raise OSError("stdin gone")

    monkeypatch.setattr(sys, "stdin", Exploding())
    assert gate.main() == 0


def test_main_passes_when_removal_search_hits_a_git_error(tmp_path: Path, monkeypatch):
    """The file exists but its directory is not inside any git repo — the
    survivor search cannot run, and the hook fails open for the tool call
    rather than blocking on ambiguity (the commit-time gate fails closed
    instead)."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    (not_a_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(not_a_repo / "lib.py"),
            "old_string": "def emit(x):\n    return x\n",
            "new_string": "",
        },
    }
    assert _run_main(monkeypatch, event) == 0
