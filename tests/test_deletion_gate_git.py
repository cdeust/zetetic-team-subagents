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


def test_find_survivors_ignores_a_same_named_local_definition(git_repo: Path):
    # Every Stop hook in this repo defines its own _note/repo_root. Another
    # file's definition, and its bare calls to it, are bound locally and are
    # not references to the removed one (measured 2026-09-08: 23 false
    # survivors on repo_root, all of this shape). The fixture name is not a
    # real helper of this repository, so these strings never become
    # survivors of a real removal.
    (git_repo / "other_hook.py").write_text(
        "def local_helper():\n    return '.'\n\n\ndef main():\n    root = local_helper()\n"
    )
    head = _commit(git_repo, "init")
    assert dgg.find_survivors(str(git_repo), head, None, "local_helper", "python") == []


def test_find_survivors_keeps_attribute_and_import_shapes_in_a_defining_file(git_repo: Path):
    (git_repo / "mixed.py").write_text(
        "from lib import local_helper as lib_helper\n"
        "import lib\n\n\n"
        "def local_helper():\n"
        "    return lib.local_helper()\n"
    )
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(str(git_repo), head, None, "local_helper", "python")
    assert any("lib.local_helper()" in s for s in survivors)
    assert any("from lib import local_helper" in s for s in survivors)
    assert not any("def local_helper" in s for s in survivors)


def test_find_survivors_drops_attribute_refs_in_files_that_never_name_the_definer(git_repo: Path):
    # `args.local_helper` on an argparse namespace, in a script that never
    # names the hook, cannot hold an object bound to the hook's module.
    (git_repo / "hooks").mkdir()
    (git_repo / "hooks" / "stop-x.py").write_text("def local_helper():\n    return '.'\n")
    (git_repo / "script.py").write_text("root = args.local_helper\n")
    head = _commit(git_repo, "init")
    with_definer = dgg.find_survivors(
        str(git_repo), head, None, "local_helper", "python", defined_in="hooks/stop-x.py"
    )
    assert not any("script.py" in s for s in with_definer)
    without = dgg.find_survivors(str(git_repo), head, None, "local_helper", "python")
    assert any("script.py" in s for s in without)  # the rule needs the definer's path


def test_find_survivors_keeps_attribute_refs_in_a_file_that_names_the_definer(git_repo: Path):
    (git_repo / "hooks").mkdir()
    (git_repo / "hooks" / "stop-x.py").write_text("def local_helper():\n    return '.'\n")
    (git_repo / "test_stop_x.py").write_text(
        'HOOK = "hooks/stop-x.py"\nhook = load(HOOK)\nassert hook.local_helper()\n'
    )
    (git_repo / "by_module.py").write_text("import stop_x\nstop_x.local_helper()\n")
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(
        str(git_repo), head, None, "local_helper", "python", defined_in="hooks/stop-x.py"
    )
    assert any("test_stop_x.py" in s for s in survivors)
    assert any("by_module.py" in s for s in survivors)


def test_find_survivors_ignores_a_match_that_sits_only_in_a_comment(git_repo: Path):
    (git_repo / "notes.py").write_text(
        "from lib import local_helper\n"
        "# the fixture replaces `local_helper()` for every test\n"
        "x = 1  # not local_helper() either\n"
        "y = local_helper()  # this one is a call\n"
    )
    (git_repo / "notes.sh").write_text('# local_helper "x" is commented out\nlocal_helper "y"\n')
    head = _commit(git_repo, "init")
    py = dgg.find_survivors(str(git_repo), head, None, "local_helper", "python")
    calls = [s for s in py if "local_helper()" in s]
    assert len(calls) == 1 and "y = local_helper()" in calls[0]
    sh = dgg.find_survivors(str(git_repo), head, None, "local_helper", "shell")
    assert len(sh) == 1 and 'local_helper "y"' in sh[0]


def test_find_survivors_python_bare_call_needs_an_import_to_count(git_repo: Path):
    # LEGB: a free name resolves in the module's own globals. Without an
    # import of `local_helper`, `local_helper()` is a local, a builtin, or
    # text inside a docstring; it cannot reach the removed definition.
    (git_repo / "docstring.py").write_text('def t():\n    """Replaces `local_helper()` here."""\n')
    (git_repo / "imported.py").write_text("from lib import local_helper\nlocal_helper()\n")
    (git_repo / "starred.py").write_text("from lib import *\nlocal_helper()\n")
    head = _commit(git_repo, "init")
    survivors = dgg.find_survivors(str(git_repo), head, None, "local_helper", "python")
    assert not any("docstring.py" in s for s in survivors)
    assert any("imported.py" in s and "local_helper()" in s for s in survivors)
    assert any("starred.py" in s and "local_helper()" in s for s in survivors)


def test_find_survivors_attribute_rule_in_worktree_mode(git_repo: Path):
    (git_repo / "hooks").mkdir()
    (git_repo / "hooks" / "stop-x.py").write_text("def local_helper():\n    return '.'\n")
    (git_repo / "script.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "script.py").write_text("root = args.local_helper\n")  # unstaged
    survivors = dgg.find_survivors(
        str(git_repo), "HEAD", dgg.MODE_WORKTREE, "local_helper", "python",
        defined_in="hooks/stop-x.py",
    )
    assert survivors == []


def test_find_survivors_worktree_mode_ignores_a_local_definition(git_repo: Path):
    (git_repo / "caller.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "caller.py").write_text("def emit():\n    pass\n\nemit()\n")  # unstaged
    survivors = dgg.find_survivors(str(git_repo), "HEAD", dgg.MODE_WORKTREE, "emit", "python")
    assert survivors == []


def test_find_survivors_shell_local_function_is_not_a_survivor(git_repo: Path):
    (git_repo / "other.sh").write_text('emit_event() {\n  echo 1\n}\nemit_event "x"\n')
    head = _commit(git_repo, "init")
    assert dgg.find_survivors(str(git_repo), head, None, "emit_event", "shell") == []


def test_find_survivors_staged_mode_searches_the_index(git_repo: Path):
    (git_repo / "caller.py").write_text("from lib import emit\nemit(1)\n")
    _commit(git_repo, "init")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    survivors = dgg.find_survivors(str(git_repo), "HEAD", dgg.MODE_STAGED, "emit", "python")
    assert any("caller.py" in s for s in survivors)


def test_find_survivors_worktree_mode_searches_the_working_tree(git_repo: Path):
    (git_repo / "caller.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    (git_repo / "caller.py").write_text("from lib import emit\nemit(1)\n")  # unstaged
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
