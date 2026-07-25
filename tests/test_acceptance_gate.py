"""Unit tests for tools/acceptance_gate.py — the deterministic acceptance-gate core.

These import the module directly (not through the acceptance-gate.sh wrapper) so
that mutation testing (mutmut, rules/coding-standards.md §12) can mutate the
module in its sandbox and have these tests KILL the mutants. The shell harness in
tools/tests/acceptance-gate/run-tests.sh remains the integration test through the
wrapper; this is the in-process unit layer mutmut needs.

Every gate command here is a portable POSIX shell builtin (true/false/exit/printf)
so the suite is hermetic — no external tools, no network.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import tools.acceptance_gate as ag


# ── constants (kills literal mutants on the operational defaults) ─────────────

def test_exit_codes_are_distinct_and_correct():
    assert ag.EXIT_ACCEPTED == 0
    assert ag.EXIT_USAGE == 2
    assert ag.EXIT_REJECTED == 3
    assert len({ag.EXIT_ACCEPTED, ag.EXIT_USAGE, ag.EXIT_REJECTED}) == 3


def test_operational_default_constants():
    assert ag.DEFAULT_GATE_TIMEOUT_S == 600
    assert ag.GIT_TIMEOUT_S == 60
    assert ag.OUTPUT_TAIL_BYTES == 800
    assert ag.FILES_TOKEN == "{files}"


# ── load_config ──────────────────────────────────────────────────────────────

def test_load_config_reads_mapping(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("gates:\n  - name: a\n    cmd: 'true'\n")
    cfg = ag.load_config(p)
    assert cfg == {"gates": [{"name": "a", "cmd": "true"}]}


def test_load_config_empty_file_is_empty_dict(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("")  # yaml.safe_load -> None -> {}
    assert ag.load_config(p) == {}


def test_load_config_rejects_non_mapping(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="gate config must be a mapping with a 'gates' list"):
        ag.load_config(p)


def test_load_config_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(OSError):
        ag.load_config(tmp_path / "nope.yaml")


# ── load_and_merge ───────────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_merge_concatenates_in_file_order(tmp_path: Path):
    a = _write(tmp_path, "a.yaml", "gates:\n  - {name: a, cmd: 'true'}\n")
    b = _write(tmp_path, "b.yaml", "gates:\n  - {name: b, cmd: 'true'}\n")
    merged = ag.load_and_merge([a, b])
    assert [g["name"] for g in merged["gates"]] == ["a", "b"]


def test_merge_skips_files_with_no_gates(tmp_path: Path):
    a = _write(tmp_path, "a.yaml", "gates:\n  - {name: a, cmd: 'true'}\n")
    b = _write(tmp_path, "b.yaml", "other: 1\n")
    merged = ag.load_and_merge([a, b])
    assert [g["name"] for g in merged["gates"]] == ["a"]


def test_merge_wraps_non_list_gates_as_single_element(tmp_path: Path):
    # A scalar 'gates' must arrive as one element so validate_config flags it,
    # rather than being .extend()-ed character by character.
    a = _write(tmp_path, "a.yaml", "gates: notalist\n")
    merged = ag.load_and_merge([a])
    assert merged["gates"] == ["notalist"]


# ── validate_config ──────────────────────────────────────────────────────────

def test_validate_accepts_well_formed():
    cfg = {"gates": [{"name": "a", "cmd": "true"}]}
    assert ag.validate_config(cfg) == []


def test_validate_rejects_missing_gates():
    assert ag.validate_config({}) == ["config.gates must be a non-empty list"]


def test_validate_rejects_empty_gates_list():
    assert ag.validate_config({"gates": []}) == ["config.gates must be a non-empty list"]


def test_validate_rejects_non_list_gates():
    assert ag.validate_config({"gates": "x"}) == ["config.gates must be a non-empty list"]


def test_validate_flags_non_mapping_gate():
    errs = ag.validate_config({"gates": ["x"]})
    assert errs == ["gates[0] must be a mapping"]


def test_validate_continues_past_non_mapping_gate():
    # A non-mapping gate must not stop the loop (continue, not break): a later
    # malformed gate is still reported.
    errs = ag.validate_config({"gates": ["x", {"name": "b"}]})
    assert errs == ["gates[0] must be a mapping", "gates[1] missing cmd"]


def test_validate_flags_missing_name_and_cmd():
    errs = ag.validate_config({"gates": [{}]})
    assert "gates[0] missing name" in errs
    assert "gates[0] missing cmd" in errs


def test_validate_reports_correct_index():
    errs = ag.validate_config({"gates": [{"name": "a", "cmd": "true"}, {"name": "b"}]})
    assert errs == ["gates[1] missing cmd"]


# ── _uses_files / _substitute ────────────────────────────────────────────────

def test_uses_files_true_when_token_present():
    assert ag._uses_files({"gates": [{"cmd": "check --files {files}"}]}) is True


def test_uses_files_false_when_absent():
    assert ag._uses_files({"gates": [{"cmd": "check"}]}) is False


def test_uses_files_handles_missing_cmd():
    assert ag._uses_files({"gates": [{}]}) is False


def test_substitute_replaces_token_with_space_joined_files():
    out = ag._substitute({"name": "a", "cmd": "c {files}"}, ["x.py", "y.py"])
    assert out["cmd"] == "c x.py y.py"


def test_substitute_leaves_non_token_cmd_untouched():
    gate = {"name": "a", "cmd": "c"}
    out = ag._substitute(gate, ["x.py"])
    assert out["cmd"] == "c"


def test_substitute_does_not_mutate_input():
    gate = {"name": "a", "cmd": "c {files}"}
    ag._substitute(gate, ["x.py"])
    assert gate["cmd"] == "c {files}"  # original unchanged


# ── run_gate ─────────────────────────────────────────────────────────────────

def test_run_gate_pass_on_exit_zero():
    r = ag.run_gate({"name": "ok", "cmd": "true"}, Path("."), 5)
    assert r["passed"] is True
    assert r["exit"] == 0


def test_run_gate_records_name_and_cmd():
    r = ag.run_gate({"name": "ok", "cmd": "true"}, Path("."), 5)
    assert r["name"] == "ok"
    assert r["cmd"] == "true"


def test_run_gate_oserror_is_127(tmp_path: Path):
    # A nonexistent cwd makes subprocess.run raise FileNotFoundError (OSError)
    # before the shell starts — the distinct branch from a shell-reported 127.
    missing = tmp_path / "does-not-exist"
    r = ag.run_gate({"name": "a", "cmd": "true"}, missing, 5)
    assert r["exit"] == 127
    assert r["passed"] is False
    assert "could not run" in r["output_tail"]


def test_run_gate_fail_on_nonzero():
    r = ag.run_gate({"name": "no", "cmd": "exit 5"}, Path("."), 5)
    assert r["passed"] is False
    assert r["exit"] == 5


def test_run_gate_mandatory_defaults_true():
    r = ag.run_gate({"name": "a", "cmd": "true"}, Path("."), 5)
    assert r["mandatory"] is True


def test_run_gate_mandatory_explicit_false():
    r = ag.run_gate({"name": "a", "cmd": "true", "mandatory": False}, Path("."), 5)
    assert r["mandatory"] is False


def test_run_gate_origin_defaults_base():
    r = ag.run_gate({"name": "a", "cmd": "true"}, Path("."), 5)
    assert r["origin"] == "base"


def test_run_gate_records_origin():
    r = ag.run_gate({"name": "a", "cmd": "true", "origin": "contract"}, Path("."), 5)
    assert r["origin"] == "contract"


def test_run_gate_command_not_found_is_127():
    # OSError path: a bare nonexistent executable with shell=True still runs the
    # shell, so force OSError via an unrunnable cwd? Instead use a command the
    # shell reports as 127; shell returns 127 (not OSError) — assert that branch.
    r = ag.run_gate({"name": "a", "cmd": "this_cmd_does_not_exist_zzz"}, Path("."), 5)
    assert r["exit"] == 127
    assert r["passed"] is False


def test_run_gate_timeout_is_124():
    r = ag.run_gate({"name": "slow", "cmd": "sleep 5"}, Path("."), 1)
    assert r["exit"] == 124
    assert "timed out" in r["output_tail"]


def test_run_gate_captures_output_tail():
    r = ag.run_gate({"name": "a", "cmd": "printf hello"}, Path("."), 5)
    assert r["output_tail"] == "hello"


def test_run_gate_tail_truncated_to_limit():
    n = ag.OUTPUT_TAIL_BYTES + 50
    r = ag.run_gate({"name": "a", "cmd": f"printf 'x%.0s' $(seq 1 {n})"}, Path("."), 5)
    assert len(r["output_tail"]) == ag.OUTPUT_TAIL_BYTES


# ── evaluate ─────────────────────────────────────────────────────────────────

def _result(name, passed, mandatory=True, exit=0):
    return {"name": name, "passed": passed, "mandatory": mandatory,
            "exit": exit, "output_tail": ""}


def test_evaluate_no_mandatory_fails_closed():
    v = ag.evaluate([_result("a", True, mandatory=False)])
    assert v["accepted"] is False
    assert v["unmet"] == ["no mandatory gates — fail closed"]
    assert set(v) == {"accepted", "summary", "gates", "unmet"}
    assert v["summary"] == "no mandatory gates configured — refusing to auto-accept"
    assert v["gates"] == [_result("a", True, mandatory=False)]


def test_evaluate_all_mandatory_pass_accepts():
    results = [_result("a", True), _result("b", True)]
    v = ag.evaluate(results)
    assert v["accepted"] is True
    assert v["unmet"] == []
    assert set(v) == {"accepted", "summary", "gates", "unmet"}
    assert v["gates"] == results


def test_evaluate_one_mandatory_fail_rejects():
    v = ag.evaluate([_result("a", True), _result("b", False, exit=1)])
    assert v["accepted"] is False
    assert len(v["unmet"]) == 1
    assert "b exited 1" in v["unmet"][0]


def test_evaluate_advisory_fail_does_not_block():
    v = ag.evaluate([_result("a", True), _result("b", False, mandatory=False, exit=1)])
    assert v["accepted"] is True


def test_evaluate_summary_counts():
    v = ag.evaluate([_result("a", True), _result("b", False, exit=1),
                     _result("c", True, mandatory=False)])
    assert v["summary"] == "2/3 gates passed; 1/2 mandatory passed"


def test_evaluate_unmet_tail_clipped_to_160():
    long_tail = {"name": "a", "passed": False, "mandatory": True,
                 "exit": 1, "output_tail": "z" * 500}
    v = ag.evaluate([long_tail])
    # "a exited 1: " prefix + 160 chars of tail
    assert v["unmet"][0].endswith("z" * 160)
    assert "z" * 161 not in v["unmet"][0]


# ── _empty_diff_verdict ──────────────────────────────────────────────────────

def test_empty_diff_verdict_shape():
    v = ag._empty_diff_verdict("aaa", "bbb")
    assert v["accepted"] is False
    assert v["gates"] == []
    assert v["changed_files"] == []
    assert set(v) == {"accepted", "summary", "gates", "unmet", "changed_files"}
    assert "aaa" in v["summary"] and "bbb" in v["summary"]
    assert v["unmet"] == [
        "empty-diff: nothing changed (a build that changed nothing cannot be accepted)"
    ]


# ── run() — without git (no diff scoping) ────────────────────────────────────

def test_run_accepts_when_mandatory_pass(tmp_path: Path):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'true'}\n")
    verdict, code = ag.run([cfg], tmp_path, 5)
    assert code == ag.EXIT_ACCEPTED
    assert verdict["accepted"] is True
    assert verdict["changed_files"] is None  # unscoped


def test_run_rejects_when_mandatory_fail(tmp_path: Path):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'false'}\n")
    verdict, code = ag.run([cfg], tmp_path, 5)
    assert code == ag.EXIT_REJECTED
    assert verdict["accepted"] is False


def test_run_raises_on_invalid_config(tmp_path: Path):
    cfg = _write(tmp_path, "c.yaml", "gates: []\n")
    with pytest.raises(ValueError):
        ag.run([cfg], tmp_path, 5)


def test_run_raises_on_invalid_config_names_the_errors(tmp_path: Path):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a}\n")
    with pytest.raises(ValueError, match="invalid gate config"):
        ag.run([cfg], tmp_path, 5)


def test_run_raises_when_files_token_unscoped(tmp_path: Path):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'c {files}'}\n")
    with pytest.raises(ValueError,
                       match="a gate uses .files. but --diff-base/--diff-head were not given"):
        ag.run([cfg], tmp_path, 5)


def test_run_requires_both_diff_refs_for_scoping(tmp_path: Path):
    # scoped is `diff_base AND diff_head` — one ref alone must NOT scope, so a
    # {files} gate with only diff_base still raises the unscoped error.
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'c {files}'}\n")
    with pytest.raises(ValueError, match="--diff-base/--diff-head were not given"):
        ag.run([cfg], tmp_path, 5, diff_base="HEAD", diff_head=None)


# ── run() — with a real temp git repo (diff scoping + worktree) ──────────────

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def g(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "t")
    g("commit", "--allow-empty", "-q", "-m", "base")
    return tmp_path


def test_run_empty_diff_is_rejected(git_repo: Path):
    cfg = _write(git_repo, "c.yaml", "gates:\n  - {name: a, cmd: 'true'}\n")
    # Two distinct ref SPELLINGS of the same commit -> empty diff, but distinct
    # strings so the verdict must echo BOTH (catches base/head being dropped).
    verdict, code = ag.run([cfg], git_repo, 5, diff_base="HEAD", diff_head="@")
    assert code == ag.EXIT_REJECTED
    assert "empty diff" in verdict["summary"]
    assert "HEAD" in verdict["summary"]
    assert "@" in verdict["summary"]


def test_run_in_rev_worktree_evaluates_committed_tree(git_repo: Path):
    # Commit a config + a marker file, then gate `rev` in a throwaway worktree.
    _write(git_repo, "c.yaml", "gates:\n  - {name: a, cmd: 'test -f marker'}\n")
    (git_repo / "marker").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "marker"], cwd=git_repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo,
                          capture_output=True, text=True, check=True).stdout.strip()
    cfg = git_repo / "c.yaml"
    # Remove the marker from the WORKING tree: only the committed worktree of
    # `rev` still has it, so acceptance proves the gate ran against `rev`.
    (git_repo / "marker").unlink()
    verdict, code = ag.run([cfg], git_repo, 10, rev=head)
    assert code == ag.EXIT_ACCEPTED
    assert verdict["accepted"] is True


def test_run_scoped_substitutes_changed_files(git_repo: Path):
    (git_repo / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "foo.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add foo"], cwd=git_repo, check=True)
    # A gate that passes iff {files} expands to include foo.py.
    cfg = _write(git_repo, "c.yaml",
                 "gates:\n  - {name: a, cmd: 'echo {files} | grep -q foo.py'}\n")
    verdict, code = ag.run([cfg], git_repo, 5, diff_base="HEAD~1", diff_head="HEAD")
    assert code == ag.EXIT_ACCEPTED
    assert verdict["changed_files"] == ["foo.py"]


# ── main() — argv parsing + exit codes + JSON stdout ─────────────────────────

def test_main_accepted_prints_json_and_returns_zero(tmp_path: Path, capsys):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'true'}\n")
    code = ag.main(["--config", str(cfg), "--root", str(tmp_path)])
    assert code == ag.EXIT_ACCEPTED
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True


def test_main_rejected_returns_three(tmp_path: Path, capsys):
    cfg = _write(tmp_path, "c.yaml", "gates:\n  - {name: a, cmd: 'false'}\n")
    code = ag.main(["--config", str(cfg), "--root", str(tmp_path)])
    assert code == ag.EXIT_REJECTED


def test_main_bad_config_returns_usage(tmp_path: Path, capsys):
    cfg = _write(tmp_path, "c.yaml", "gates: []\n")
    code = ag.main(["--config", str(cfg), "--root", str(tmp_path)])
    assert code == ag.EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_main_missing_config_file_returns_usage(tmp_path: Path):
    code = ag.main(["--config", str(tmp_path / "nope.yaml"), "--root", str(tmp_path)])
    assert code == ag.EXIT_USAGE


def test_main_diff_scoping_passes_refs_through(git_repo: Path, capsys):
    # A {files} gate forces the scoping path: main must forward BOTH diff refs to
    # run() in the right slots, else this raises (usage) or mis-scopes.
    (git_repo / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "foo.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add foo"], cwd=git_repo, check=True)
    cfg = _write(git_repo, "c.yaml",
                 "gates:\n  - {name: a, cmd: 'echo {files} | grep -q foo.py'}\n")
    code = ag.main(["--config", str(cfg), "--root", str(git_repo),
                    "--diff-base", "HEAD~1", "--diff-head", "HEAD"])
    assert code == ag.EXIT_ACCEPTED
    out = json.loads(capsys.readouterr().out)
    assert out["changed_files"] == ["foo.py"]
