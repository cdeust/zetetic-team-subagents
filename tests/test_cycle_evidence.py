"""Per-task cycle ledger: what a transcript proves (tools/cycle_evidence.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from cycle_support import CHECK, RECALL, REMEMBER, call, full_cycle, write_transcript
import cycle_evidence as ev

DECLS = {"check": {"kind": "command", "ref": CHECK},
         "refine": {"kind": "url", "ref": "https://github.com/o/r/issues/1"},
         "benchmark": {"kind": "n/a", "ref": "no measurable: a docs-only hook"}}


def task_file(path: str) -> bool:
    return "/repo/" in path


def verdict(tmp_path: Path, calls: list, decls: dict = DECLS) -> dict:
    transcript = write_transcript(tmp_path / "t.jsonl", calls)
    found, _ = ev.scan(str(transcript), 0)
    return ev.evaluate(found, decls, task_file)


def test_a_full_cycle_proves_every_stage(tmp_path):
    result = verdict(tmp_path, full_cycle(Path("/repo")))
    assert result["missing"] == []
    assert set(result["evidence"]) == set(ev.STAGES)
    assert result["evidence"]["check"] == {"source": "transcript", "detail": CHECK}
    assert result["evidence"]["refine"]["source"] == "declaration"
    assert result["evidence"]["benchmark"] == {"source": "declaration", "detail": "n/a: no measurable: a docs-only hook"}
    assert result["counts"] == {"edits": 1, "reviews": 1, "reopens": 0}


@pytest.mark.parametrize("dropped,stage", [(0, "recall"), (1, "investigate"), (4, "review"), (5, "remember")])
def test_each_transcript_stage_is_missing_without_its_call(tmp_path, dropped, stage):
    calls = full_cycle(Path("/repo"))
    del calls[dropped]
    assert verdict(tmp_path, calls)["missing"] == [stage]


def test_verify_needs_the_declared_command_to_exit_zero_after_the_last_edit(tmp_path):
    repo = Path("/repo")
    failing = full_cycle(repo)
    failing[3] = call("Bash", is_error=True, command=CHECK)
    assert verdict(tmp_path, failing)["missing"] == ["verify"]  # declared, not yet run green
    before_edit = [call("Bash", command=CHECK)] + [c for c in full_cycle(repo) if c["name"] != "Bash"]
    assert "verify" in verdict(tmp_path, before_edit)["missing"]
    no_result = full_cycle(repo)
    no_result[3] = call("Bash", is_error=None, command=CHECK)
    assert "verify" in verdict(tmp_path, no_result)["missing"]


def test_an_undeclared_check_leaves_check_and_verify_missing(tmp_path):
    decls = {k: v for k, v in DECLS.items() if k != "check"}
    assert verdict(tmp_path, full_cycle(Path("/repo")), decls)["missing"] == ["check", "verify"]


def test_refine_is_proven_by_the_refine_skill_and_benchmark_only_by_a_declaration(tmp_path):
    decls = {"check": DECLS["check"]}
    calls = [call("Skill", skill="refine-gate:refine")] + full_cycle(Path("/repo"))
    result = verdict(tmp_path, calls, decls)
    assert result["evidence"]["refine"] == {"source": "transcript", "detail": "Skill"}
    assert result["missing"] == ["benchmark"]


@pytest.mark.parametrize("skill, proven", [("refine-gate:refine", True), ("refine", True),
                                          ("x:unrefined-foo", False), ("refine-gate:refinement", False)])
def test_refine_is_the_refine_skill_by_exact_name(tmp_path, skill, proven):
    calls = [call("Skill", skill=skill)] + full_cycle(Path("/repo"))
    result = verdict(tmp_path, calls, {"check": DECLS["check"]})
    assert ("refine" not in result["missing"]) is proven


def test_an_edit_after_the_review_reopens_and_needs_a_new_review_and_run(tmp_path):
    repo = Path("/repo")
    calls = full_cycle(repo) + [call("Edit", file_path=str(repo / "b.py"))]
    result = verdict(tmp_path, calls)
    assert result["missing"] == ["verify", "review"]
    calls += [call("Bash", command=CHECK), call("Skill", skill="code-review")]
    result = verdict(tmp_path, calls)
    assert result["missing"] == []
    assert result["counts"] == {"edits": 2, "reviews": 2, "reopens": 1}


def test_edits_of_non_task_files_do_not_move_the_last_edit(tmp_path):
    calls = full_cycle(Path("/repo")) + [call("Write", file_path="/home/u/.claude/memory/x.md")]
    assert verdict(tmp_path, calls)["missing"] == []


def test_a_window_without_a_task_edit_proves_only_declarations(tmp_path):
    calls = [call(RECALL), call("Read", file_path="/repo/a.py"), call(REMEMBER)]
    result = verdict(tmp_path, calls)
    assert set(result["evidence"]) == {"refine", "benchmark"}
    assert result["counts"] == {"edits": 0, "reviews": 0, "reopens": 0}


def test_scan_starts_at_the_window_and_skips_torn_lines(tmp_path):
    transcript = write_transcript(tmp_path / "t.jsonl", [call("Read", file_path="/repo/a.py")])
    start = transcript.stat().st_size
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "assistant", "message": {"content": [{"type": "tool_use"\n')
    write_transcript(transcript, [call("Grep", pattern="x")], append=True)
    calls, end = ev.scan(str(transcript), start)
    assert [c["name"] for c in calls] == ["Grep"]
    assert end == transcript.stat().st_size


def test_scan_of_a_missing_transcript_raises_instead_of_proving_nothing(tmp_path):
    with pytest.raises(OSError):
        ev.scan(str(tmp_path / "absent.jsonl"), 0)


@pytest.mark.parametrize("case", [
    ("cat tools/a.py", True), ("sed -n 1,80p hooks/x.py", True), ("cd /r && grep -n foo a.py", True),
    ("python3 x.py | grep ok", True), ("git log --oneline -3", True), ("git diff --stat", True),
    ("python3 -m pytest -q", False), ("echo cat", False), ("sed -i '' s/a/b/ f", False),
    ("git status", False),
])
def test_investigation_through_bash_counts_only_for_reading_commands(case):
    command, reads = case
    assert ev._investigation(call("Bash", command=command)) is reads


@pytest.mark.parametrize("case", [
    ({"command": CHECK}, True), ({"command": f"  {CHECK}  "}, True),
    ({"command": f"cd /r/wt && {CHECK}"}, True), ({"command": f'cd "/r/my wt" && {CHECK}'}, True),
    ({"command": f"{CHECK} | tail -3"}, False), ({"command": f"{CHECK} || true"}, False),
    ({"command": f"echo {CHECK}"}, False), ({"command": f"{CHECK} -k one"}, False),
    ({"command": CHECK, "run_in_background": True}, False),
])
def test_verify_accepts_only_the_declared_check_run_as_the_whole_foreground_command(case):
    tool_input, proves = case
    assert ev.runs_check(call("Bash", **tool_input), CHECK) is proves


@pytest.mark.parametrize("case", [
    (call("Skill", skill="code-review"), True), (call("Skill", skill="zetetic:review"), True),
    (call("Agent", subagent_type="general-purpose", description="Review the diff",
          prompt="GENIUS: popper, feynman\nReview the diff."), True),
    (call("Agent", subagent_type="Plan", prompt="GENIUS: popper\nplease review this"), True),
    (call("Agent", subagent_type="general-purpose", description="Review the diff",
          prompt="no genius line here"), False),
    (call("Agent", subagent_type="general-purpose", description="Implement the parser",
          prompt="GENIUS: dijkstra\nImplement the parser."), False),
    (call("Agent", subagent_type="code-reviewer", prompt="review"), False),
    (call("Skill", skill="superpowers:receiving-code-review"), False),
    (call("Skill", skill="superpowers:requesting-code-review"), False),
    (call("Skill", skill="refine-gate:refine"), False),
])
def test_review_is_an_exact_review_skill_or_a_genius_pattern_review_agent(case):
    review_call, counts = case
    assert ev._review(review_call) is counts


def test_edited_paths_lists_each_edited_file_once():
    calls = [call("Edit", file_path="/repo/a.py"), call("Write", file_path="/repo/a.py"),
             call("NotebookEdit", notebook_path="/repo/n.ipynb"), call("Read", file_path="/repo/r.py")]
    assert ev.edited_paths(calls) == ["/repo/a.py", "/repo/n.ipynb"]
