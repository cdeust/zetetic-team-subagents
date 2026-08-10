"""Unit tests for tools/deletion_gate.py — the removed-top-level-definition
gate (coding-standards.md S8, the deletion-gate incident: cdeust/cortex-viz
commit 45d4a80).

Imported dotted (tools.deletion_gate) per mutmut's trampoline-matching
requirement (tests/test_manifest_gate.py). tools/deletion_gate.py itself
imports its sibling tools/deletion_gate_lang.py by BARE name (so a script
invocation and the PreToolUse hook, which both put tools/ directly on
sys.path, resolve it) — this file adds tools/ to sys.path too so the same
bare import resolves under pytest's dotted-package import as well.

The end-to-end shell suite (tools/tests/deletion-gate/run-tests.sh, 26
cases including the real-incident shape, rename/move, the observation-only
trailer rejection, and the PreToolUse hook) is the behavioral contract;
this file is the in-process unit layer coverage.py and mutmut need.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import tools.deletion_gate as dg


# ── constants ────────────────────────────────────────────────────────────────

def test_exit_codes_are_distinct_and_correct():
    assert dg.EXIT_OK == 0
    assert dg.EXIT_BLOCK == 1
    assert dg.EXIT_USAGE == 2
    assert len({dg.EXIT_OK, dg.EXIT_BLOCK, dg.EXIT_USAGE}) == 3


def test_trailer_key_and_observation_phrases():
    assert dg.TRAILER_KEY == "Retired-Because"
    assert "no callers" in dg.OBSERVATION_ONLY_PHRASES
    assert "dead code" in dg.OBSERVATION_ONLY_PHRASES


# ── normalize_body / find_rename_match ───────────────────────────────────────

def test_normalize_body_swaps_the_definitions_own_name_and_drops_blank_lines():
    body = "def emit(x):\n\n    return x\n"
    normalized = dg.normalize_body(body, "emit")
    assert "emit" not in normalized
    assert "\x00NAME\x00" in normalized
    assert "" not in normalized.splitlines()


def test_find_rename_match_picks_the_highest_similarity_unconsumed_candidate():
    removed = dg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
    close = dg.Definition("b.py", "publish", "function", "def publish(x):\n    return x\n")
    far = dg.Definition("c.py", "unrelated", "function", "def unrelated():\n    return 99999\n")
    match = dg.find_rename_match(removed, [far, close], consumed=set())
    assert match is not None
    idx, cand, ratio = match
    assert cand is close
    assert ratio >= dg.RENAME_SIMILARITY_THRESHOLD


def test_find_rename_match_respects_consumed_and_kind():
    removed = dg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
    same_name_wrong_kind = dg.Definition("b.py", "emit", "class", "def emit(x):\n    return x\n")
    assert dg.find_rename_match(removed, [same_name_wrong_kind], set()) is None

    cand = dg.Definition("b.py", "publish", "function", "def emit(x):\n    return x\n")
    assert dg.find_rename_match(removed, [cand], consumed={0}) is None


def test_find_rename_match_none_when_nothing_added():
    removed = dg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
    assert dg.find_rename_match(removed, [], set()) is None


# ── extract_trailer / is_substantive ─────────────────────────────────────────

def test_extract_trailer_multiline_message():
    msg = "chore: drop x\n\nRetired-Because: superseded by y in export_v2.py.\n"
    assert dg.extract_trailer(msg, dg.TRAILER_KEY) == "superseded by y in export_v2.py."


def test_extract_trailer_absent_returns_none():
    assert dg.extract_trailer("chore: drop x\n\nno trailer here\n", dg.TRAILER_KEY) is None


def test_extract_trailer_joins_multiple_occurrences():
    msg = "Retired-Because: reason one.\nRetired-Because: reason two.\n"
    joined = dg.extract_trailer(msg, dg.TRAILER_KEY)
    assert "reason one." in joined and "reason two." in joined


def test_is_substantive_rejects_observation_only():
    assert dg.is_substantive("no callers, unused, dead code.") is False


def test_is_substantive_accepts_a_real_reason():
    assert dg.is_substantive(
        "superseded by the streaming exporter in export_v2.py two releases ago"
    ) is True


def test_is_substantive_boundary_is_inclusive_at_15_significant_chars():
    fifteen_letters = "abcdefghijklmno"
    assert len(fifteen_letters) == 15
    assert dg.is_substantive(fifteen_letters) is True
    assert dg.is_substantive(fifteen_letters[:-1]) is False


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
    assert dg.is_test_path(path) is True


@pytest.mark.parametrize("path", [
    "pkg/lib.py",
    "server/graph_event_stream.py",
    "contest.py",  # must not false-positive on a substring
])
def test_is_test_path_false(path):
    assert dg.is_test_path(path) is False


# ── require_pcre / find_survivors / changed_paths / collect_definitions ─────

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


def test_require_pcre_passes_on_a_normal_git_build(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    dg.require_pcre(str(git_repo))  # raises on failure; no exception is the assertion


def test_find_survivors_matches_call_attr_and_import_shapes(git_repo: Path):
    (git_repo / "caller.py").write_text(
        "from lib import emit\n\n"
        "def run():\n"
        "    return emit(1)\n"
    )
    (git_repo / "other.py").write_text("x = 1\n")  # must not match a different lang scope
    head = _commit(git_repo, "init")
    survivors = dg.find_survivors(str(git_repo), head, False, "emit", "python")
    assert any("caller.py" in s for s in survivors)
    assert not any("other.py" in s for s in survivors)


def test_find_survivors_matches_shell_bare_word_invocation(git_repo: Path):
    (git_repo / "lib.sh").write_text("emit_event() {\n  echo 1\n}\n")
    (git_repo / "caller.sh").write_text('emit_event "hello"\n')
    head = _commit(git_repo, "init")
    survivors = dg.find_survivors(str(git_repo), head, False, "emit_event", "shell")
    assert any("caller.sh" in s for s in survivors)


def test_find_survivors_raises_on_a_bad_ref(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    with pytest.raises(dg.GitError, match="git grep failed"):
        dg.find_survivors(str(git_repo), "not-a-real-ref", False, "x", "python")


def test_show_file_returns_none_for_a_path_absent_at_ref(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    head = _commit(git_repo, "init")
    assert dg.show_file(str(git_repo), head, "missing.py") is None


def test_run_git_raises_git_error_on_failure(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    with pytest.raises(dg.GitError, match="failed"):
        dg.run_git(str(git_repo), ["not-a-real-git-subcommand"])


def test_changed_paths_reports_rename_status_when_git_detects_one(git_repo: Path):
    (git_repo / "a.py").write_text("def f():\n" + "    return 1\n" * 20)
    base = _commit(git_repo, "init")
    subprocess.run(["git", "mv", "a.py", "b.py"], cwd=git_repo, check=True, capture_output=True)
    head = _commit(git_repo, "rename file, same big body")
    rows = dg.changed_paths(str(git_repo), base, head, False)
    assert any(status.startswith("R") for status, _, _ in rows)


def test_find_survivors_exclude_path_drops_that_files_matches(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return emit(x - 1)\n")
    head = _commit(git_repo, "init")
    survivors = dg.find_survivors(
        str(git_repo), head, False, "emit", "python", exclude_path="lib.py"
    )
    assert survivors == []


def test_changed_paths_reports_status_and_paths(git_repo: Path):
    (git_repo / "a.py").write_text("x = 1\n")
    base = _commit(git_repo, "init")
    (git_repo / "a.py").write_text("x = 2\n")
    (git_repo / "b.py").write_text("y = 1\n")
    head = _commit(git_repo, "second")
    rows = dg.changed_paths(str(git_repo), base, head, False)
    statuses = {p: s for s, p, _ in rows}
    assert statuses["a.py"] == "M"
    assert statuses["b.py"] == "A"


def test_collect_definitions_finds_removed_and_added(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit")
    removed, added = dg.collect_definitions(str(git_repo), base, head, False)
    assert [d.name for d in removed] == ["emit"]
    assert added == []


# ── evaluate(): the four dispositions, end to end ────────────────────────────

def test_evaluate_blocks_on_a_surviving_caller(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit, no trailer")
    result = dg.evaluate(str(git_repo), base, head, False, "drop emit, no trailer")
    assert result.blocked is True
    assert any("caller.py" in f.message for f in result.findings)


def test_evaluate_passes_a_legitimate_deletion_with_a_substantive_trailer(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    message = (
        "chore: drop orphan\n\n"
        "Retired-Because: superseded by the streaming exporter two releases ago.\n"
    )
    head = _commit(git_repo, message)
    result = dg.evaluate(str(git_repo), base, head, False, message)
    assert result.blocked is False


def test_evaluate_blocks_an_observation_only_trailer(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    message = "chore: drop orphan\n\nRetired-Because: no callers, unused, dead code.\n"
    head = _commit(git_repo, message)
    result = dg.evaluate(str(git_repo), base, head, False, message)
    assert result.blocked is True
    assert "restates the absence" in result.findings[0].message


def test_evaluate_passes_a_rename_with_no_trailer(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def publish(x):\n    return x\n")
    head = _commit(git_repo, "rename emit -> publish")
    result = dg.evaluate(str(git_repo), base, head, False, "rename emit -> publish")
    assert result.blocked is False
    assert "rename/move" in result.findings[0].message


def test_evaluate_skips_a_test_path_removal(git_repo: Path):
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_thing.py").write_text("def test_x():\n    assert True\n")
    base = _commit(git_repo, "init")
    (git_repo / "tests" / "test_thing.py").write_text("")
    head = _commit(git_repo, "drop a retired test")
    result = dg.evaluate(str(git_repo), base, head, False, "drop a retired test")
    assert result.blocked is False
    assert "SKIP" in result.findings[0].message


def test_evaluate_require_trailer_false_defers_the_no_survivor_case(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop orphan")
    result = dg.evaluate(str(git_repo), base, head, False, "", require_trailer=False)
    assert result.blocked is False
    assert "required at commit time" in result.findings[0].message


def test_evaluate_no_removed_definitions_returns_empty_findings(git_repo: Path):
    (git_repo / "lib.py").write_text("def keep(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def keep(x):\n    return x + 1\n")
    head = _commit(git_repo, "tweak body only")
    result = dg.evaluate(str(git_repo), base, head, False, "tweak body only")
    assert result.findings == []
    assert result.blocked is False


# ── message resolution helpers ───────────────────────────────────────────────

def test_commit_message_returns_the_full_body(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    head = _commit(git_repo, "feat: a subject\n\na body line.\n")
    assert "a body line." in dg.commit_message(str(git_repo), head)


def test_range_messages_covers_every_commit_in_range(git_repo: Path):
    (git_repo / "f.py").write_text("x = 1\n")
    base = _commit(git_repo, "first")
    (git_repo / "f.py").write_text("x = 2\n")
    head = _commit(git_repo, "second")
    combined = dg.range_messages(str(git_repo), base, head)
    assert "second" in combined


# ── CLI: build_parser / resolve_message / main ───────────────────────────────

def test_build_parser_requires_no_default_repo_value_of_dot():
    args = dg.build_parser().parse_args(["--commit", "abc123"])
    assert args.repo == "."
    assert args.commit == "abc123"
    assert args.staged is False


def test_main_usage_error_when_no_mode_given(capsys):
    code = dg.main(["--repo", "."])
    assert code == dg.EXIT_USAGE
    assert "one of --commit" in capsys.readouterr().err


def test_main_end_to_end_commit_mode_blocks_on_a_survivor(git_repo: Path, capsys):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit, no trailer")
    code = dg.main(["--repo", str(git_repo), "--commit", head])
    out = capsys.readouterr().out
    assert code == dg.EXIT_BLOCK
    assert "BLOCK" in out
    assert "caller.py" in out


def test_main_end_to_end_range_mode_passes_a_clean_diff(git_repo: Path, capsys):
    (git_repo / "lib.py").write_text("def keep(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def keep(x):\n    return x + 1\n")
    head = _commit(git_repo, "tweak")
    code = dg.main(["--repo", str(git_repo), "--base", base, "--head", head])
    assert code == dg.EXIT_OK
    assert "no top-level definitions were removed" in capsys.readouterr().out


def test_main_staged_mode_with_message_file_requires_the_trailer(git_repo: Path, tmp_path: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    msg_file = tmp_path / "msg.txt"
    msg_file.write_text("chore: drop orphan\n\nno trailer\n")
    code = dg.main(["--repo", str(git_repo), "--staged", "--message-file", str(msg_file)])
    assert code == dg.EXIT_BLOCK


def test_main_staged_without_message_file_defers_rather_than_blocks(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    code = dg.main(["--repo", str(git_repo), "--staged"])
    assert code == dg.EXIT_OK


def test_main_end_to_end_rename_only_diff_prints_pass(git_repo: Path, capsys):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def publish(x):\n    return x\n")
    head = _commit(git_repo, "rename emit -> publish")
    code = dg.main(["--repo", str(git_repo), "--commit", head])
    out = capsys.readouterr().out
    assert code == dg.EXIT_OK
    assert "PASS" in out
    assert "deletion-gate: pass" in out


def test_main_git_error_maps_to_usage_exit(tmp_path: Path, capsys):
    # Not a git repo at all -> require_pcre's `git -C` invocation fails closed.
    code = dg.main(["--repo", str(tmp_path), "--commit", "deadbeef"])
    assert code == dg.EXIT_USAGE
    assert "error:" in capsys.readouterr().err
