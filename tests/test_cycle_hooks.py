"""Per-task cycle ledger, end to end: the opener hook and the Stop/SubagentStop gate."""
from __future__ import annotations

import json

import pytest

from cycle_support import (CHECK, SESSION, call, edit_event, full_cycle, gate_hook, git_repo, open_hook,
                           run_hook, stop_event, write_transcript)
import cycle_ledger as cl
import gates_jsonl


@pytest.fixture(autouse=True)
def gate_on(monkeypatch):
    monkeypatch.delenv("ZETETIC_CYCLE_GATE", raising=False)


@pytest.fixture
def repo(tmp_path):
    return git_repo(tmp_path / "repo")


@pytest.fixture
def transcript(tmp_path):
    return tmp_path / "proj" / f"{SESSION}.jsonl"


@pytest.fixture
def fire(monkeypatch, capsys):
    """fire(hook, payload) -> (exit code, stdout, stderr)."""
    return lambda module, payload: run_hook(module, payload, monkeypatch, capsys)


def rows(repo):
    return gates_jsonl.read_rows(cl.ledger_path(str(repo)))


def open_task(fire, repo, transcript, **extra):
    write_transcript(transcript, [call("Edit", file_path=str(repo / "a.py"))])
    return fire(open_hook, edit_event(repo, str(repo / "a.py"), transcript, **extra))


def declare_all(repo, task_id):
    for stage, ref in (("check", {"command": CHECK}), ("refine", {"url": "https://github.com/o/r/issues/9"}),
                       ("benchmark", {"n/a": "no benchmark covers hooks"})):
        cl.declare(str(repo), task_id, stage, ref)


def test_an_edit_of_a_repo_file_opens_one_task_and_ignored_files_open_none(fire, repo, transcript):
    _, _, err = open_task(fire, repo, transcript)
    fire(open_hook, edit_event(repo, str(repo / "a.py"), transcript))
    fire(open_hook, edit_event(repo, str(repo / "scratch" / "n.md"), transcript))
    fire(open_hook, {**edit_event(repo, "x", transcript), "tool_name": "Read"})
    (task,) = rows(repo)
    assert "opened by main" in err
    assert (task["agent_id"], task["agent_type"], task["session_id"]) == (None, "main", SESSION)


def test_stop_blocks_with_every_missing_stage_and_how_to_prove_it(fire, repo, transcript):
    open_task(fire, repo, transcript)
    code, out, _ = fire(gate_hook, stop_event(repo, transcript))
    reason = json.loads(out)["reason"]
    assert code == 0 and json.loads(out)["decision"] == "block"
    for needle in ("check: declare", "recall:", "refine:", "investigate:", "verify:", "benchmark:",
                   "review:", "remember:", "cycle_ledger.py --cwd", rows(repo)[0]["open"]):
        assert needle in reason
    assert "  implement:" not in reason


def test_a_proven_task_closes_once_and_the_stop_is_allowed(fire, repo, transcript):
    open_task(fire, repo, transcript)
    declare_all(repo, rows(repo)[0]["open"])
    write_transcript(transcript, full_cycle(repo), append=True)
    _, out, err = fire(gate_hook, stop_event(repo, transcript))
    assert out == "" and "closed: every stage proven" in err
    fire(gate_hook, stop_event(repo, transcript))
    (close,) = [r for r in rows(repo) if "close" in r]
    assert close["window_end"] == transcript.stat().st_size
    assert close["evidence"]["refine"]["source"] == "declaration"


def test_the_next_task_does_not_reuse_the_previous_tasks_evidence(fire, repo, transcript):
    test_a_proven_task_closes_once_and_the_stop_is_allowed(fire, repo, transcript)
    write_transcript(transcript, [call("Edit", file_path=str(repo / "b.py"))], append=True)
    fire(open_hook, edit_event(repo, str(repo / "b.py"), transcript))
    _, out, _ = fire(gate_hook, stop_event(repo, transcript))
    assert "recall:" in json.loads(out)["reason"]


def test_forced_continuation_is_not_reblocked_but_reported(fire, repo, transcript):
    open_task(fire, repo, transcript)
    _, out, err = fire(gate_hook, stop_event(repo, transcript, stop_hook_active=True))
    assert out == "" and "still unproven" in err and "recall" in err


@pytest.fixture
def switch_off(monkeypatch):
    monkeypatch.setenv("ZETETIC_CYCLE_GATE", "off")


@pytest.mark.usefixtures("switch_off")
def test_the_emergency_switch_closes_the_task_as_bypassed_once(fire, repo, transcript):
    open_task(fire, repo, transcript)
    _, out, err = fire(gate_hook, stop_event(repo, transcript))
    fire(gate_hook, stop_event(repo, transcript))
    (bypass,) = [r for r in rows(repo) if r.get("bypass")]
    assert out == "" and "closed as bypassed" in err
    assert bypass["close"] == rows(repo)[0]["open"] and "review" in bypass["missing"]
    assert len(rows(repo)) == 2  # the second stop found no open task: nothing appended


def test_other_sessions_tasks_do_not_block_but_are_counted(fire, repo, transcript):
    open_task(fire, repo, transcript, session_id="sess-other")
    _, out, err = fire(gate_hook, stop_event(repo, transcript))
    assert out == "" and "1 open task(s) belong to other sessions or agents" in err


def test_unattributed_tasks_block_the_main_agent_and_say_why(fire, repo, transcript):
    _, _, err = open_task(fire, repo, transcript, session_id="")
    assert "unattributed" in err
    _, out, _ = fire(gate_hook, stop_event(repo, transcript))
    assert "recorded without a session_id" in json.loads(out)["reason"]
    _, out, _ = fire(gate_hook, stop_event(repo, transcript, session_id=None))
    assert "carries no session_id" in json.loads(out)["reason"]


def test_a_subagent_task_is_judged_on_the_subagents_own_transcript(fire, repo, tmp_path, transcript):
    agent_t = tmp_path / "proj" / SESSION / "subagents" / "agent-ag7.jsonl"
    write_transcript(agent_t, [call("Edit", file_path=str(repo / "a.py"))])
    fire(open_hook, edit_event(repo, str(repo / "a.py"), transcript, agent_id="ag7", agent_type="engineer"))
    write_transcript(transcript, full_cycle(repo))  # the parent's proof is not the subagent's
    sub_stop = {**stop_event(repo, transcript), "hook_event_name": "SubagentStop", "agent_id": "ag7",
                "agent_type": "engineer", "agent_transcript_path": str(agent_t)}
    assert fire(gate_hook, stop_event(repo, transcript))[1] == ""
    _, out, _ = fire(gate_hook, sub_stop)
    assert "engineer" in json.loads(out)["reason"]
    declare_all(repo, rows(repo)[0]["open"])
    write_transcript(agent_t, full_cycle(repo), append=True)
    assert fire(gate_hook, sub_stop)[1] == ""
    (sub_close,) = [r for r in rows(repo) if "close" in r]
    assert sub_close["transcript_path"] == str(agent_t)
    fire(open_hook, edit_event(repo, str(repo / "b.py"), transcript))
    assert [r for r in rows(repo) if "open" in r][-1]["window_start"] == 0  # not the subagent's end


def test_an_unattributed_task_is_judged_on_its_own_transcript_not_this_sessions(fire, repo, tmp_path, transcript):
    orphan_t = tmp_path / "proj" / "lost.jsonl"
    write_transcript(orphan_t, [call("Edit", file_path=str(repo / "a.py"))])
    fire(open_hook, edit_event(repo, str(repo / "a.py"), orphan_t, session_id=""))
    orphan_t.unlink()
    write_transcript(transcript, full_cycle(repo))  # this session's proof is not the orphan's
    declare_all(repo, rows(repo)[0]["open"])
    _, out, _ = fire(gate_hook, stop_event(repo, transcript))
    assert "unreadable" in json.loads(out)["reason"] and str(orphan_t) in json.loads(out)["reason"]
    assert not [r for r in rows(repo) if "close" in r]


def test_an_unreadable_transcript_proves_nothing_and_blocks(fire, repo, transcript):
    open_task(fire, repo, transcript)
    _, out, _ = fire(gate_hook, stop_event(repo, transcript.with_name("gone.jsonl")))
    assert "unreadable" in json.loads(out)["reason"]


@pytest.mark.parametrize("stdin", ["not json", "[1]"])
def test_malformed_payloads_are_reported_never_fatal(stdin, monkeypatch, capsys):
    import io
    import sys
    for hook in (open_hook, gate_hook):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        assert hook.main() == 0
    err = capsys.readouterr().err
    assert "not JSON" in err or "not a JSON object" in err


def test_outside_a_repository_nothing_is_opened_or_enforced(fire, tmp_path, transcript):
    plain = tmp_path / "plain"
    plain.mkdir()
    write_transcript(transcript, [call("Edit", file_path=str(plain / "a.py"))])
    assert fire(open_hook, edit_event(plain, str(plain / "a.py"), transcript))[1:] == ("", "")
    assert fire(gate_hook, stop_event(plain, transcript))[1:] == ("", "")


def test_a_cwd_outside_any_repository_is_reported_when_the_file_is_in_one(fire, repo, tmp_path, transcript):
    plain = tmp_path / "plain"
    plain.mkdir()
    write_transcript(transcript, [call("Edit", file_path=str(repo / "a.py"))])
    _, _, err = fire(open_hook, edit_event(plain, str(repo / "a.py"), transcript))
    assert "will NOT enforce it" in err and len(rows(repo)) == 1


def test_hooks_are_registered_for_edits_stop_and_subagent_stop():
    from cycle_support import REPO_ROOT
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    commands = {event: json.dumps(hooks[event]) for event in ("PostToolUse", "Stop", "SubagentStop")}
    assert "post-edit-cycle-open.py" in commands["PostToolUse"]
    assert "stop-cycle-gate.py" in commands["Stop"] and "stop-cycle-gate.py" in commands["SubagentStop"]
