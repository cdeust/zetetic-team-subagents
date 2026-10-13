"""Subagent reflection: SubagentStop schedules it, Stop enforces it, lift needs evidence.

Covers hooks/subagent-stop-reflection.py, hooks/stop-reflection-gate.py and
tools/reflection_ledger.py. The hook scripts are loaded by path (hyphenated
names, hooks/ is not a package) and run in-process against a real throwaway git
repository; one test runs a script as a subprocess to prove its entry point.

Hindsight "configured" is a real http.server on an ephemeral port: the socket
is bound and listening when the server object exists, so no readiness wait is
needed. "Server down" is a port that was bound and then closed: connection
refused is immediate, not a timer. Nothing here sleeps or retries.
"""
from __future__ import annotations

import http.server
import importlib.util
import io
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "sess-A"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


start_hook = _load("subagent_stop_reflection", "hooks/subagent-stop-reflection.py")
stop_hook = _load("stop_reflection_gate", "hooks/stop-reflection-gate.py")
import reflection_ledger as ledger  # noqa: E402  (tools/ is put on sys.path by the hooks above)
import reflection_subagent  # noqa: E402


# -- fixtures ---------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture(autouse=True)
def no_real_hindsight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Default: Hindsight config absent, so no test can reach a real server."""
    config = tmp_path / "hindsight.json"
    monkeypatch.setenv("HINDSIGHT_CONFIG", str(config))
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_TOKEN", raising=False)
    return config


def _assistant(message_id: str, block: dict) -> str:
    return json.dumps({"type": "assistant", "message": {"id": message_id, "content": [block]}})


def make_transcript(tmp_path: Path, agent_id: str = "a1b2c3", meta: dict | None = None,
                    handback: str | None = "Done: fixed the bug in parser.py") -> Path:
    sub = tmp_path / "proj" / SESSION / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    transcript = sub / f"agent-{agent_id}.jsonl"
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "task"}}),
             _assistant("m1", {"type": "text", "text": "working on it"})]
    if handback is not None:
        lines.append(_assistant("m2", {"type": "tool_use", "name": "SubagentHandback",
                                       "input": {"message": handback}}))
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if meta is not None:
        (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return transcript


def event(repo: Path, transcript: Path | None, **extra) -> dict:
    base = {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "SubagentStop"}
    if transcript is not None:
        base["agent_transcript_path"] = str(transcript)
    base.update(extra)
    return base


def run_hook(module, payload: dict, monkeypatch: pytest.MonkeyPatch, capsys) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = module.main()
    out = capsys.readouterr()
    return code, out.out, out.err


def rows(repo: Path) -> list[dict]:
    return ledger.read_rows(ledger.ledger_path(str(repo)))


def write_hindsight_config(path: Path, repo: Path, api_url: str, opt_in: list[str] | None = None):
    path.write_text(json.dumps({
        "apiUrl": api_url, "optInOnly": True,
        "optInPaths": [str(repo)] if opt_in is None else opt_in,
        "mapPathToBank": {str(repo): "bank-x"}}), encoding="utf-8")


class _Recorder(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802  (http.server API)
        length = int(self.headers.get("Content-Length", "0"))
        self.server.received.append((self.path, json.loads(self.rfile.read(length))))
        self.server.auth.append(self.headers.get("Authorization"))
        self.send_response(self.server.status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def hindsight_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    server.received, server.auth, server.status = [], [], 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


def closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# -- (a) payload shapes -----------------------------------------------------

def test_payload_with_agent_type_records_pending_row(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta={"agentType": "from-meta", "description": "fix parser"})
    code, _, err = run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3",
                                              agent_type="zetetic-team-subagents:engineer"),
                            monkeypatch, capsys)
    assert code == 0
    (row,) = rows(repo)
    assert row["agent_id"] == "a1b2c3"
    assert row["agent_type"] == "zetetic-team-subagents:engineer"
    assert row["description"] == "fix parser"
    assert row["transcript_path"] == str(transcript)
    assert row["session_id"] == SESSION
    assert row["excerpt"] == "Done: fixed the bug in parser.py"
    assert "pending reflection recorded" in err
    assert not any("agent_type taken from meta.json" in n for n in row["notes"])


def test_payload_without_agent_type_falls_back_to_meta_json(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta={"agentType": "claude-code-guide", "description": "d"})
    _, _, err = run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    (row,) = rows(repo)
    assert row["agent_type"] == "claude-code-guide"
    assert "agent_type taken from meta.json" in row["notes"]
    assert "agent_type taken from meta.json" in err


def test_agent_id_and_type_recovered_from_the_transcript_file_alone(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, agent_id="zz9", meta={"agentType": "reviewer"})
    run_hook(start_hook, event(repo, None, transcript_path=str(transcript)), monkeypatch, capsys)
    (row,) = rows(repo)
    assert (row["agent_id"], row["agent_type"]) == ("zz9", "reviewer")
    assert "agent_id taken from the transcript file name" in row["notes"]
    assert not any("not identified" in n for n in row["notes"])


def test_no_agent_type_anywhere_is_recorded_as_unknown_and_said_so(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta=None)
    _, _, err = run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    (row,) = rows(repo)
    assert row["agent_type"] == "unknown"
    assert "agent_type absent from the payload and from meta.json" in err


def test_unidentifiable_event_writes_nothing_and_says_so(repo, monkeypatch, capsys):
    code, _, err = run_hook(start_hook, event(repo, None), monkeypatch, capsys)
    assert code == 0
    assert "cannot identify the subagent" in err
    assert rows(repo) == []


def test_final_message_falls_back_to_last_text_then_payload(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, handback=None)
    run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    assert rows(repo)[0]["excerpt"] == "working on it"
    empty = tmp_path / "empty"
    empty.mkdir()
    bare = make_transcript(empty, agent_id="b2", handback=None)
    bare.write_text("", encoding="utf-8")
    run_hook(start_hook, event(repo, bare, agent_id="b2", last_assistant_message="from payload"),
             monkeypatch, capsys)
    assert rows(repo)[1]["excerpt"] == "from payload"


def test_the_last_handback_wins_and_an_overlong_one_is_cut_with_a_marker(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, handback="first report")
    long_text = "x" * (reflection_subagent.MAX_EXCERPT_CHARS + 10)
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(_assistant("m3", {"type": "tool_use", "name": "SubagentHandback",
                                   "input": {"message": long_text}}) + "\n")
    run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3", agent_type="t"), monkeypatch, capsys)
    excerpt = rows(repo)[0]["excerpt"]
    assert excerpt.startswith("x" * reflection_subagent.MAX_EXCERPT_CHARS)
    assert excerpt.endswith(f"[... cut at {reflection_subagent.MAX_EXCERPT_CHARS} characters]")
    assert "first report" not in excerpt


def test_refiring_for_the_same_agent_does_not_duplicate(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path)
    payload = event(repo, transcript, agent_id="a1b2c3", agent_type="t")
    run_hook(start_hook, payload, monkeypatch, capsys)
    _, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert len(rows(repo)) == 1
    assert "already in the ledger" in err


def test_the_ledger_is_owner_only_because_rows_carry_transcript_excerpts(repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path)
    run_hook(start_hook, event(repo, transcript, agent_id="a1b2c3", agent_type="t"), monkeypatch, capsys)
    path = Path(ledger.ledger_path(str(repo)))
    assert path.stat().st_mode & 0o777 == 0o600


def test_outside_a_git_repo_the_missing_ledger_is_reported(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    transcript = make_transcript(tmp_path)
    code, _, err = run_hook(start_hook, event(plain, transcript, agent_id="a1b2c3", agent_type="t"),
                            monkeypatch, capsys)
    assert code == 0
    assert "ledger NOT written" in err


def test_hook_script_runs_as_a_subprocess(repo, tmp_path, no_real_hindsight):
    transcript = make_transcript(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "subagent-stop-reflection.py")],
        input=json.dumps(event(repo, transcript, agent_id="a1b2c3", agent_type="t")),
        capture_output=True, text=True, check=False,
        env={"HINDSIGHT_CONFIG": str(no_real_hindsight), "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0
    assert "pending reflection recorded" in proc.stderr
    assert len(rows(repo)) == 1


# -- (b) Hindsight: configured / not configured / down, each visible --------

@pytest.fixture
def fire(repo, tmp_path, monkeypatch, capsys):
    """fire(cwd=None): run the SubagentStop hook for one run, return its stderr."""
    def _fire(cwd=None):
        payload = event(cwd or repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="engineer")
        return run_hook(start_hook, payload, monkeypatch, capsys)[2]
    return _fire


@pytest.fixture
def configure(repo, no_real_hindsight):
    """configure(api_url, opt_in=None): write the Hindsight config for `repo`."""
    def _configure(api_url, opt_in=None):
        write_hindsight_config(no_real_hindsight, repo, api_url, opt_in)
    return _configure


def server_url(server) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def test_hindsight_configured_retains_with_agent_type_and_source_tags(
        repo, fire, configure, hindsight_server):
    configure(server_url(hindsight_server))
    err = fire()
    ((path, body),) = hindsight_server.received
    assert path == "/v1/default/banks/bank-x/memories"
    (item,) = body["items"]
    assert item["tags"] == ["agent_type:engineer", "source:subagent"]
    assert item["document_id"] == "subagent-a1b2c3"
    assert "Done: fixed the bug in parser.py" in item["content"]
    assert body["async"] is True and body["operation_id"]
    assert "hindsight retained" in err
    assert rows(repo)[0]["hindsight"]["status"] == "retained"
    assert rows(repo)[0]["hindsight"]["bank"] == "bank-x"


def test_hindsight_absent_config_is_said_on_stderr_and_in_the_ledger(repo, fire):
    err = fire()
    assert "hindsight not_configured: no Hindsight config at" in err
    assert rows(repo)[0]["hindsight"]["status"] == "not_configured"


def test_hindsight_config_without_this_cwd_is_not_configured(repo, tmp_path, fire, configure):
    configure(closed_port_url(), opt_in=[str(tmp_path / "other")])
    err = fire()
    assert "under no optInPaths entry" in err
    assert rows(repo)[0]["hindsight"]["status"] == "not_configured"


def test_hindsight_server_down_is_an_error_not_silence(repo, fire, configure):
    configure(closed_port_url())
    err = fire()
    assert "hindsight error:" in err and "unreachable" in err
    row = rows(repo)[0]
    assert row["hindsight"]["status"] == "error"
    assert row["agent_id"] == "a1b2c3"  # the pending entry survives the Hindsight failure


def test_hindsight_refusal_is_an_error_naming_the_http_status(repo, fire, configure, hindsight_server):
    hindsight_server.status = 500
    configure(server_url(hindsight_server))
    assert "hindsight error: HTTP 500" in fire()
    assert rows(repo)[0]["hindsight"]["status"] == "error"


def test_hindsight_token_from_the_environment_is_sent_as_a_bearer(
        fire, configure, hindsight_server, monkeypatch):
    configure("http://127.0.0.1:1")
    monkeypatch.setenv("HINDSIGHT_API_URL", server_url(hindsight_server))
    monkeypatch.setenv("HINDSIGHT_API_TOKEN", "tok-1")
    fire()
    assert hindsight_server.auth == ["Bearer tok-1"]


@pytest.mark.parametrize("config, expected", [
    ('{"optInOnly": false, "apiUrl": "http://x"}', "names no bank"),
    ('{"optInOnly": false, "mapPathToBank": "a-string"}', "names no bank"),
    ("[]", "not a JSON object"),
    ("{not json", "unreadable"),
])
def test_hindsight_incomplete_config_is_reported_not_guessed(fire, no_real_hindsight, config, expected):
    no_real_hindsight.write_text(config, encoding="utf-8")
    err = fire()
    assert "hindsight not_configured" in err and expected in err


def test_hindsight_bank_without_an_api_url_is_reported(repo, fire, no_real_hindsight):
    no_real_hindsight.write_text(json.dumps({"mapPathToBank": {str(repo): "b"}}), encoding="utf-8")
    assert "no apiUrl in the config" in fire()


def test_the_longest_matching_path_chooses_the_bank(repo, fire, no_real_hindsight, hindsight_server):
    nested = repo / "sub"
    nested.mkdir()
    no_real_hindsight.write_text(json.dumps({
        "apiUrl": server_url(hindsight_server),
        "mapPathToBank": {str(repo): "outer", str(nested): "inner"}}), encoding="utf-8")
    fire(cwd=nested)
    assert hindsight_server.received[0][0] == "/v1/default/banks/inner/memories"


def test_a_worktree_under_an_opted_in_repo_maps_to_its_bank(repo, fire, configure, hindsight_server):
    configure(server_url(hindsight_server))
    nested = repo / ".claude" / "worktrees" / "w"
    nested.mkdir(parents=True)
    fire(cwd=nested)
    assert hindsight_server.received[0][0] == "/v1/default/banks/bank-x/memories"


# -- (2) Stop enforcement and (3) lift --------------------------------------

@pytest.fixture
def schedule(repo, tmp_path, monkeypatch, capsys):
    """schedule(agent_id, session): run the SubagentStop hook for one engineer run."""
    def _schedule(agent_id="a1b2c3", session=SESSION):
        transcript = make_transcript(tmp_path, agent_id=agent_id)
        run_hook(start_hook, event(repo, transcript, agent_id=agent_id, agent_type="engineer",
                                   session_id=session), monkeypatch, capsys)
    return _schedule


def stop_event(repo: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "Stop", **extra}


def test_stop_blocks_while_pending_and_names_the_procedure(repo, monkeypatch, capsys, schedule):
    schedule()
    code, out, _ = run_hook(stop_hook, stop_event(repo), monkeypatch, capsys)
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    reason = decision["reason"]
    for needle in ("lesson-candidate", "agent_topic", "a1b2c3", "engineer", "--memory-id",
                   "reflection_ledger.py", "Quote the transcript lines"):
        assert needle in reason


def test_stop_allows_after_lift_with_a_memory_id(repo, monkeypatch, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(repo), "lift", "a1b2c3", "--memory-id", "4242"]) == 0
    assert "lifted a1b2c3 with Cortex memory 4242" in capsys.readouterr().out
    _, out, _ = run_hook(stop_hook, stop_event(repo), monkeypatch, capsys)
    assert out == ""
    lift_row = [r for r in rows(repo) if "lift" in r][0]
    assert lift_row["memory_id"] == 4242


def test_stop_is_not_reblocked_in_a_forced_continuation_but_says_so(repo, monkeypatch, capsys, schedule):
    schedule()
    _, out, err = run_hook(stop_hook, stop_event(repo, stop_hook_active=True), monkeypatch, capsys)
    assert out == ""
    assert "still pending" in err and "a1b2c3" in err


def test_another_sessions_pending_reflection_does_not_block_but_is_reported(repo, monkeypatch, capsys, schedule):
    schedule(session="sess-B")
    _, out, err = run_hook(stop_hook, stop_event(repo), monkeypatch, capsys)
    assert out == ""
    assert "1 pending reflection(s) belong to other sessions" in err


def test_stop_with_nothing_pending_or_no_repo_is_silent(repo, tmp_path, monkeypatch, capsys):
    assert run_hook(stop_hook, stop_event(repo), monkeypatch, capsys)[1:] == ("", "")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run_hook(stop_hook, stop_event(plain), monkeypatch, capsys)[1:] == ("", "")


def test_stop_lists_at_most_the_cap_and_points_at_the_list_command(repo, monkeypatch, capsys, schedule):
    for n in range(stop_hook.MAX_LISTED + 2):
        schedule(agent_id=f"ag{n}")
    reason = json.loads(run_hook(stop_hook, stop_event(repo), monkeypatch, capsys)[1])["reason"]
    assert f"{stop_hook.MAX_LISTED + 2} subagent reflection(s) pending" in reason
    assert "(+2 more" in reason and f"ag{stop_hook.MAX_LISTED + 1}" not in reason


@pytest.mark.parametrize("extra", [[], ["--memory-id", "0"], ["--memory-id", "-3"],
                                   ["--memory-id", "abc"], ["--memory-id", "1.5"]])
def test_lift_refuses_without_valid_evidence_and_leaves_the_ledger_untouched(repo, capsys, extra, schedule):
    schedule()
    before = ledger.ledger_path(str(repo))
    size = Path(before).stat().st_size
    assert ledger.main(["--cwd", str(repo), "lift", "a1b2c3", *extra]) == 2
    assert "refusing to lift without evidence" in capsys.readouterr().err
    assert Path(before).stat().st_size == size
    assert [r["agent_id"] for r in ledger.pending(before)] == ["a1b2c3"]


def test_a_boolean_is_not_a_memory_id(repo, schedule):
    schedule()
    with pytest.raises(ledger.LiftRefused):
        ledger.lift(ledger.ledger_path(str(repo)), "a1b2c3", True)


def test_lift_refuses_unknown_and_already_lifted_agents(repo, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(repo), "lift", "nope", "--memory-id", "7"]) == 2
    assert "no pending reflection for agent nope" in capsys.readouterr().err
    assert ledger.main(["--cwd", str(repo), "lift", "a1b2c3", "--memory-id", "7"]) == 0
    assert ledger.main(["--cwd", str(repo), "lift", "a1b2c3", "--memory-id", "8"]) == 2
    assert "already lifted" in capsys.readouterr().err


def test_list_command_prints_pending_entries(repo, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(repo), "list"]) == 0
    assert capsys.readouterr().out.startswith("a1b2c3\tengineer")


# -- registration -----------------------------------------------------------

def test_both_hooks_are_registered_for_their_events():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    def commands(event_name: str) -> str:
        return json.dumps(hooks[event_name])

    assert "subagent-stop-reflection.py" in commands("SubagentStop")
    assert "stop-reflection-gate.py" in commands("Stop")
