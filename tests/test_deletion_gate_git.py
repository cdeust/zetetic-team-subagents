"""Unit tests for tools/deletion_gate_git.py — the git I/O primitives that
back tools/deletion_gate.py: reading a file at a ref/the index/the working
tree, diffing two states, and grepping the tree for survivors.

Imported dotted (tools.deletion_gate_git) per mutmut's trampoline-matching
requirement (tests/test_manifest_gate.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import tools.deletion_gate_git as dgg


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def g(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                        capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "t")
    return tmp_path


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True,
                    capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True, check=True).stdout.strip()


# ── mode constants ───────────────────────────────────────────────────────────

def test_mode_constants_are_distinct():
    assert dgg.MODE_STAGED != dgg.MODE_WORKTREE
    assert dgg.MODE_STAGED == "staged"
    assert dgg.MODE_WORKTREE == "worktree"


# ── require_pcre ─────────────────────────────────────────────────────────────

def test_require_pcre_passes_on_a_normal_git_build(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    dgg.require_pcre(str(git_repo))  # raises on failure; no exception is the assertion


# ── run_git / show_file ──────────────────────────────────────────────────────

def test_run_git_raises_git_error_on_failure(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    with pytest.raises(dgg.GitError, match="failed"):
        dgg.run_git(str(git_repo), ["not-a-real-git-subcommand"])


def test_show_file_returns_none_for_a_path_absent_at_ref(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    head = _commit(git_repo, "init")
    assert dgg.show_file(str(git_repo), head, "missing.py") is None


# ── changed_paths ────────────────────────────────────────────────────────────

def test_changed_paths_reports_status_and_paths(git_repo: Path):
    (git_repo / "a.py").write_text("x = 1\n")
    base = _commit(git_repo, "init")
    (git_repo / "a.py").write_text("x = 2\n")
    (git_repo / "b.py").write_text("y = 1\n")
    head = _commit(git_repo, "second")
    rows = dgg.changed_paths(str(git_repo), base, head)
    statuses = {p: s for s, p, _ in rows}
    assert statuses["a.py"] == "M"
    assert statuses["b.py"] == "A"


def test_changed_paths_reports_rename_status_when_git_detects_one(git_repo: Path):
    (git_repo / "a.py").write_text("def f():\n" + "    return 1\n" * 20)
    base = _commit(git_repo, "init")
    subprocess.run(["git", "mv", "a.py", "b.py"], cwd=git_repo, check=True, capture_output=True)
    head = _commit(git_repo, "rename file, same big body")
    rows = dgg.changed_paths(str(git_repo), base, head)
    assert any(status.startswith("R") for status, _, _ in rows)


def test_changed_paths_staged_mode_diffs_the_index(git_repo: Path):
    (git_repo / "a.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "a.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    rows = dgg.changed_paths(str(git_repo), "HEAD", "HEAD", dgg.MODE_STAGED)
    assert [(s, o) for s, o, _ in rows] == [("M", "a.py")]


def test_changed_paths_worktree_mode_sees_unstaged_changes(git_repo: Path):
    (git_repo / "a.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "a.py").write_text("x = 2\n")  # never `git add`ed
    rows = dgg.changed_paths(str(git_repo), "HEAD", "HEAD", dgg.MODE_WORKTREE)
    assert [(s, o) for s, o, _ in rows] == [("M", "a.py")]


# ── post_content / read_worktree_file / show_index ──────────────────────────

def test_read_worktree_file_returns_none_on_os_error(git_repo: Path, monkeypatch):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")

    def _boom(self, *a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert dgg.read_worktree_file(str(git_repo), "f.py") is None


def test_post_content_worktree_mode_reads_the_real_file(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "f.py").write_text("x = 2\n")  # unstaged
    assert dgg.post_content(str(git_repo), "HEAD", "f.py", dgg.MODE_WORKTREE) == "x = 2\n"


def test_post_content_staged_mode_reads_the_index(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "f.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    assert dgg.post_content(str(git_repo), "HEAD", "f.py", dgg.MODE_STAGED) == "x = 2\n"


def test_post_content_ref_mode_reads_the_named_ref(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    head = _commit(git_repo, "init")
    (git_repo / "f.py").write_text("x = 2\n")  # neither staged nor committed
    assert dgg.post_content(str(git_repo), head, "f.py") == "x = 1\n"


# ── collect_definitions ──────────────────────────────────────────────────────

def test_collect_definitions_finds_removed_and_added(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit")
    removed, added = dgg.collect_definitions(str(git_repo), base, head)
    assert [d.name for d in removed] == ["emit"]
    assert added == []


# ── is_test_path ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "tests/test_thing.py",
    "test/test_thing.py",
    "tools/tests/deletion-gate/run-tests.sh",
    "pkg/test_helper.py",
    "scripts/test-memory-e2e.sh",
    "pkg/foo_test.py",
    "pkg/foo_test.go",
    "ui/foo.test.ts",
    "ui/foo.spec.tsx",
])
def test_is_test_path_true(path):
    assert dgg.is_test_path(path) is True


@pytest.mark.parametrize("path", [
    "pkg/lib.py",
    "server/graph_event_stream.py",
    "contest.py",  # must not false-positive on a substring
])
def test_is_test_path_false(path):
    assert dgg.is_test_path(path) is False


# ── find_survivors ───────────────────────────────────────────────────────────

def test_find_survivors_matches_call_attr_and_import_shapes(git_repo: Path):
    (git_repo / "caller.py").write_text(
        "from lib import emit\n\n"
        "def run():\n"
        "    return emit(1)\n"
    )
    (git_repo / "other.py").write_text("x = 1\n")  # must not match a different lang scope
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(str(git_repo), head, None, "emit", "python")
    assert any("caller.py" in s for s in survivors)
    assert not any("other.py" in s for s in survivors)


def test_find_survivors_matches_shell_bare_word_invocation(git_repo: Path):
    (git_repo / "lib.sh").write_text("emit_event() {\n  echo 1\n}\n")
    (git_repo / "caller.sh").write_text('emit_event "hello"\n')
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(str(git_repo), head, None, "emit_event", "shell")
    assert any("caller.sh" in s for s in survivors)


def test_find_survivors_raises_on_a_bad_ref(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    with pytest.raises(dgg.GitError, match="git grep failed"):
        dgg.find_survivors(str(git_repo), "not-a-real-ref", None, "x", "python")


def test_find_survivors_exclude_path_drops_that_files_matches(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return emit(x - 1)\n")
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(
        str(git_repo), head, None, "emit", "python", exclude_paths={"lib.py"}
    )
    assert survivors == []


def test_find_survivors_staged_mode_searches_the_index(git_repo: Path):
    (git_repo / "caller.py").write_text("emit(1)\n")
    _commit(git_repo, "init")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    survivors = dgg.find_survivors(str(git_repo), "HEAD", dgg.MODE_STAGED, "emit", "python")
    assert any("caller.py" in s for s in survivors)


def test_find_survivors_worktree_mode_searches_the_working_tree(git_repo: Path):
    (git_repo / "caller.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "caller.py").write_text("emit(1)\n")  # unstaged
    survivors = dgg.find_survivors(str(git_repo), "HEAD", dgg.MODE_WORKTREE, "emit", "python")
    assert any("caller.py" in s for s in survivors)


# ── commit_message / range_messages ──────────────────────────────────────────

def test_commit_message_returns_the_full_body(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    head = _commit(git_repo, "feat: a subject\n\na body line.\n")
    assert "a body line." in dgg.commit_message(str(git_repo), head)


def test_range_messages_covers_every_commit_in_range(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    base = _commit(git_repo, "first")
    (git_repo / "f.py").write_text("x = 2\n")
    head = _commit(git_repo, "second")
    combined = dgg.range_messages(str(git_repo), base, head)
    assert "second" in combined
