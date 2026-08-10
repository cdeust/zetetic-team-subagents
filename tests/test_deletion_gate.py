"""Unit tests for tools/deletion_gate.py — the removed-top-level-definition
gate's POLICY layer (coding-standards.md S8, the deletion-gate incident:
cdeust/cortex-viz commit 45d4a80): the four-way disposition (block /
rename-pass / trailer-pass / trailer-block), the shared actionable message
formatters, and the CLI. The git I/O primitives it calls live in
tools/deletion_gate_git.py and are tested in tests/test_deletion_gate_git.py.

Imported dotted (tools.deletion_gate) per mutmut's trampoline-matching
requirement (tests/test_manifest_gate.py). tools/deletion_gate.py itself
imports its sibling modules by BARE name (so a script invocation and both
hooks, which all put tools/ directly on sys.path, resolve them) — this file
adds tools/ to sys.path too so the same bare import resolves under pytest's
dotted-package import as well.

The end-to-end shell suite (tools/tests/deletion-gate/run-tests.sh, 36
cases including the real-incident shape, rename/move, the observation-only
trailer rejection, the PreToolUse/PostToolUse hooks, and the native git
hooks) is the behavioral contract; this file is the in-process unit layer
coverage.py and mutmut need.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import tools.deletion_gate as dg
import tools.deletion_gate_git as dgg


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
    removed = dgg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
    close = dgg.Definition("b.py", "publish", "function", "def publish(x):\n    return x\n")
    far = dgg.Definition("c.py", "unrelated", "function", "def unrelated():\n    return 99999\n")
    match = dg.find_rename_match(removed, [far, close], consumed=set())
    assert match is not None
    idx, cand, ratio = match
    assert cand is close
    assert ratio >= dg.RENAME_SIMILARITY_THRESHOLD


def test_find_rename_match_respects_consumed_and_kind():
    removed = dgg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
    same_name_wrong_kind = dgg.Definition("b.py", "emit", "class", "def emit(x):\n    return x\n")
    assert dg.find_rename_match(removed, [same_name_wrong_kind], set()) is None

    cand = dgg.Definition("b.py", "publish", "function", "def emit(x):\n    return x\n")
    assert dg.find_rename_match(removed, [cand], consumed={0}) is None


def test_find_rename_match_none_when_nothing_added():
    removed = dgg.Definition("a.py", "emit", "function", "def emit(x):\n    return x\n")
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


# ── message formatters ───────────────────────────────────────────────────────

def test_format_survivor_block_shows_the_true_total_not_a_silent_truncation():
    survivors = [f"caller{i}.py:1:x" for i in range(dg.SURVIVOR_SHOW_LIMIT + 5)]
    msg = dg.format_survivor_block("lib.py::emit (function)", "emit", survivors)
    assert f"showing {dg.SURVIVOR_SHOW_LIMIT} of {len(survivors)}" in msg
    assert "Retired-Because:" in msg
    assert dg.INCIDENT_COUNTEREXAMPLE in msg


def test_format_no_trailer_block_names_the_missing_key_and_the_incident():
    msg = dg.format_no_trailer_block("lib.py::orphan (function)")
    assert "Retired-Because:" in msg
    assert dg.INCIDENT_COUNTEREXAMPLE in msg


def test_format_observation_only_block_quotes_the_trailer_and_names_the_defect():
    msg = dg.format_observation_only_block("lib.py::orphan (function)", "no callers, unused.")
    assert "no callers, unused." in msg
    assert "OBSERVATION" in msg


# ── evaluate(): the four dispositions, end to end ────────────────────────────

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


def test_evaluate_blocks_on_a_surviving_caller(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit, no trailer")
    request = dg.GateRequest(str(git_repo), base, head, "drop emit, no trailer")
    result = dg.evaluate(request)
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
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, message))
    assert result.blocked is False


def test_evaluate_blocks_an_observation_only_trailer(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    message = "chore: drop orphan\n\nRetired-Because: no callers, unused, dead code.\n"
    head = _commit(git_repo, message)
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, message))
    assert result.blocked is True
    assert "is the OBSERVATION, not a reason" in result.findings[0].message


def test_evaluate_passes_a_rename_with_no_trailer(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def publish(x):\n    return x\n")
    head = _commit(git_repo, "rename emit -> publish")
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, "rename emit -> publish"))
    assert result.blocked is False
    assert "rename/move" in result.findings[0].message


def test_evaluate_skips_a_test_path_removal(git_repo: Path):
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_thing.py").write_text("def test_x():\n    assert True\n")
    base = _commit(git_repo, "init")
    (git_repo / "tests" / "test_thing.py").write_text("")
    head = _commit(git_repo, "drop a retired test")
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, "drop a retired test"))
    assert result.blocked is False
    assert "SKIP" in result.findings[0].message


def test_evaluate_require_trailer_false_defers_the_no_survivor_case(git_repo: Path):
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop orphan")
    request = dg.GateRequest(str(git_repo), base, head, "", require_trailer=False)
    result = dg.evaluate(request)
    assert result.blocked is False
    assert "required at commit time" in result.findings[0].message


def test_evaluate_no_removed_definitions_returns_empty_findings(git_repo: Path):
    (git_repo / "lib.py").write_text("def keep(x):\n    return x\n")
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("def keep(x):\n    return x + 1\n")
    head = _commit(git_repo, "tweak body only")
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, "tweak body only"))
    assert result.findings == []
    assert result.blocked is False


def test_evaluate_worktree_mode_catches_an_unstaged_survivor(git_repo: Path):
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")  # unstaged
    request = dg.GateRequest(
        str(git_repo), "HEAD", "HEAD", "", mode=dgg.MODE_WORKTREE, require_trailer=False
    )
    result = dg.evaluate(request)
    assert result.blocked is True
    assert any("caller.py" in f.message for f in result.findings)


def test_evaluate_exempts_a_survivor_in_a_file_this_diff_already_touched(git_repo: Path):
    """Regression: a moved-AND-redesigned function (signature changed
    enough that find_rename_match's body-similarity check misses it) whose
    only "survivor" is the new caller in the file the SAME diff added is
    not the incident pattern — it is a self-consistent refactor. Caught by
    dogfooding this exact gate against its own commit (2026-08-10): moving
    changed_paths()/post_content() into deletion_gate_git.py while dropping
    the old (staged, worktree) bool pair for a single `mode` string changed
    their bodies enough to fall under RENAME_SIMILARITY_THRESHOLD, and the
    gate blocked its own legitimate refactor on the new call site it had
    just written."""
    (git_repo / "lib.py").write_text(
        "def helper(x, staged, worktree=False):\n"
        "    if worktree:\n        return 1\n"
        "    if staged:\n        return 2\n"
        "    return 0\n"
    )
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    (git_repo / "new_home.py").write_text(
        "def helper(x, mode=None):\n"
        "    if mode == 'w':\n        return 1\n"
        "    if mode == 's':\n        return 2\n"
        "    return 0\n"
    )
    (git_repo / "caller.py").write_text(
        "from new_home import helper\n\ndef run():\n    return helper(1)\n"
    )
    message = (
        "refactor: move+redesign helper, update the one caller\n\n"
        "Retired-Because: split into new_home.py with a mode arg replacing "
        "the two booleans; caller.py updated in this same commit.\n"
    )
    head = _commit(git_repo, message)
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, message))
    assert result.blocked is False


def test_evaluate_still_blocks_a_survivor_in_a_file_this_diff_did_not_touch(git_repo: Path):
    """The exemption above must not swallow the real incident shape: a
    caller in a file the diff never touched is still the danger."""
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text(
        "from lib import emit\n\ndef run():\n    return emit(1)\n"
    )
    base = _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop emit, no trailer")  # caller.py untouched
    result = dg.evaluate(dg.GateRequest(str(git_repo), base, head, "drop emit, no trailer"))
    assert result.blocked is True
    assert any("caller.py" in f.message for f in result.findings)


# ── CLI: build_parser / resolve_message / resolve_mode / main ───────────────

def test_build_parser_requires_no_default_repo_value_of_dot():
    args = dg.build_parser().parse_args(["--commit", "abc123"])
    assert args.repo == "."
    assert args.commit == "abc123"
    assert args.staged is False
    assert args.worktree is False


def test_main_usage_error_when_no_mode_given(capsys):
    code = dg.main(["--repo", "."])
    assert code == dg.EXIT_USAGE
    assert "one of --commit" in capsys.readouterr().err


def test_main_rejects_combining_commit_and_staged_as_ambiguous(git_repo: Path, capsys):
    # CodeQL py/uninitialized-local-variable, tools/deletion_gate.py:443 (sha
    # 6ef90aa): require_trailer was computed from `args.staged` alone while
    # base/head were chosen by commit-priority. Passing both flags together
    # decoupled the two: base/head took the commit path but staged=True was
    # still forwarded to evaluate()/collect_definitions, which diffs the
    # (empty) index instead of commit^..commit — the gate found zero removed
    # definitions and passed a real, trailer-less deletion. A gate that
    # cannot tell which of several mutually exclusive modes was requested
    # must refuse the input, not silently let one flag win over the others.
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop orphan, no trailer")
    code = dg.main(["--repo", str(git_repo), "--commit", head, "--staged"])
    assert code == dg.EXIT_USAGE
    assert "mutually exclusive" in capsys.readouterr().err


def test_main_commit_mode_requires_the_trailer_even_when_message_file_absent(
    git_repo: Path, capsys
):
    # require_trailer must be decided per selected mode, not by testing
    # args.staged/args.worktree in isolation: commit mode always has a real
    # commit message to check, so the trailer is required regardless of
    # --message-file.
    (git_repo / "lib.py").write_text("def orphan(x):\n    return x\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")
    head = _commit(git_repo, "drop orphan, no trailer")
    code = dg.main(["--repo", str(git_repo), "--commit", head])
    assert code == dg.EXIT_BLOCK
    assert "no Retired-Because" in capsys.readouterr().out


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


def test_main_worktree_mode_catches_an_unstaged_removal(git_repo: Path, capsys):
    """This is the shape --staged cannot see: a change on disk that was
    never `git add`ed at all — exactly what a Bash `sed`/`rm` leaves."""
    (git_repo / "lib.py").write_text("def emit(x):\n    return x\n")
    (git_repo / "caller.py").write_text("from lib import emit\n\ndef run():\n    return emit(1)\n")
    _commit(git_repo, "init")
    (git_repo / "lib.py").write_text("")  # on-disk only, not staged
    code = dg.main(["--repo", str(git_repo), "--worktree"])
    out = capsys.readouterr().out
    assert code == dg.EXIT_BLOCK
    assert "caller.py" in out


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


def test_resolve_mode_worktree_defers_the_trailer_without_a_message_file():
    class Args:
        commit = None
        staged = False
        worktree = True
        base = None
        head = "HEAD"
        message_file = None

    base, head, mode, require_trailer = dg.resolve_mode(Args())
    assert (base, head, mode) == ("HEAD", "HEAD", dgg.MODE_WORKTREE)
    assert require_trailer is False


def test_main_rejects_combining_worktree_and_staged_as_ambiguous(git_repo: Path, capsys):
    (git_repo / "lib.py").write_text("x = 1\n")
    _commit(git_repo, "init")
    code = dg.main(["--repo", str(git_repo), "--staged", "--worktree"])
    assert code == dg.EXIT_USAGE
    assert "mutually exclusive" in capsys.readouterr().err


def test_count_modes_given_counts_every_mode_flag():
    class Args:
        commit = "abc"
        staged = True
        worktree = False
        base = None

    assert dg.count_modes_given(Args()) == 2


def test_main_git_error_maps_to_usage_exit(tmp_path: Path, capsys):
    # Not a git repo at all -> require_pcre's `git -C` invocation fails closed.
    code = dg.main(["--repo", str(tmp_path), "--commit", "deadbeef"])
    assert code == dg.EXIT_USAGE
    assert "error:" in capsys.readouterr().err
