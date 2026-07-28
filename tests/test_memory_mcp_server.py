"""Contract tests for tools/memory-mcp-server.py.

This is the MCP surface in front of the memory tool: every agent's read and
write of `/memories/<scope>/<file>` is mapped to backend argv here. It was at 0%
coverage (issue #71) while being, with the credential denylist, the
highest-consequence Python in the repository.

What these tests pin:

1. **Argument mapping, per command.** A dropped or reordered argv element turns
   a `str_replace` into a different edit against the same file. Every command in
   both tool schemas gets a case, including the optional-argument branches that
   only appear when a field is present.
2. **Backend exit-code semantics.** The module documents three bands (0 success,
   1 contract error with the verbatim message on stdout, 2+ fatal with the
   message on stderr) and each maps to a different `isError` and text. These are
   asserted against a faked `subprocess.run` rather than the real backend, so
   the mapping is tested rather than the shell.
3. **JSON-RPC framing.** Parse errors, unknown methods, notifications without an
   id, and handler exceptions each have a defined response, and "silently
   dropped" is asserted as a negative (nothing written), not assumed.

`memory-mcp-server.py` has hyphens and `tools/` has no dotted path for it, so
it is loaded by path, as in tests/test_context_guard.py.
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
SERVER_PATH = REPO_ROOT / "tools" / "memory-mcp-server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("memory_mcp_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


srv = _load_server()


class _Completed:
    """Stand-in for subprocess.CompletedProcess with just what run_backend reads."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_run(monkeypatch):
    """Capture the argv run_backend would execute, and control its result."""
    captured = {}

    def _factory(returncode=0, stdout="", stderr="", raises=None):
        def _run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            if raises is not None:
                raise raises
            return _Completed(returncode, stdout, stderr)

        monkeypatch.setattr(subprocess, "run", _run)
        return captured

    return _factory


# ── JSON-RPC envelope builders ───────────────────────────────────────────────

def test_response_envelope_shape():
    assert srv._response(7, {"ok": True}) == {
        "jsonrpc": "2.0", "id": 7, "result": {"ok": True},
    }


def test_error_envelope_shape():
    assert srv._error(7, -32601, "nope") == {
        "jsonrpc": "2.0", "id": 7, "error": {"code": -32601, "message": "nope"},
    }


def test_write_msg_emits_one_newline_delimited_json_object(capsys):
    """The transport contract: newline-delimited, one object per line."""
    srv.write_msg({"a": 1})
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert json.loads(out) == {"a": 1}
    assert out.count("\n") == 1


def test_write_msg_does_not_escape_non_ascii():
    """ensure_ascii=False: a memory holding non-ASCII must round-trip readably."""
    buf = io.StringIO()
    original, sys.stdout = sys.stdout, buf
    try:
        srv.write_msg({"text": "café"})
    finally:
        sys.stdout = original
    assert "café" in buf.getvalue()


# ── Environment inheritance ──────────────────────────────────────────────────

def test_inherit_env_defaults_the_agent_id_when_unset(monkeypatch):
    """Audit attribution is mandatory; an absent id becomes 'unknown', not empty."""
    monkeypatch.delenv("MEMORY_AGENT_ID", raising=False)
    assert srv._inherit_env()["MEMORY_AGENT_ID"] == "unknown"


def test_inherit_env_preserves_an_explicit_agent_id(monkeypatch):
    monkeypatch.setenv("MEMORY_AGENT_ID", "engineer")
    assert srv._inherit_env()["MEMORY_AGENT_ID"] == "engineer"


def test_inherit_env_forwards_the_rest_of_the_environment(monkeypatch):
    monkeypatch.setenv("MEMORY_ROOT", "/tmp/isolated")
    assert srv._inherit_env()["MEMORY_ROOT"] == "/tmp/isolated"


# ── run_backend: the three documented exit bands ─────────────────────────────

def test_backend_exit_0_is_success_and_returns_stdout(fake_run):
    fake_run(returncode=0, stdout="contents")
    assert srv.run_backend(["view", "/memories/x"]) == ("contents", False)


def test_backend_exit_1_returns_the_verbatim_contract_error(fake_run):
    """Spec §4.5: exit 1 puts the verbatim error string on stdout."""
    fake_run(returncode=1, stdout="Error: path outside /memories", stderr="noise")
    text, is_error = srv.run_backend(["view", "/etc/passwd"])
    assert is_error and text == "Error: path outside /memories"


def test_backend_exit_1_falls_back_to_stderr_when_stdout_is_empty(fake_run):
    fake_run(returncode=1, stdout="", stderr="acl denied")
    assert srv.run_backend(["create", "/memories/x", "y"]) == ("acl denied", True)


def test_backend_exit_2_is_fatal_and_prefers_stderr(fake_run):
    fake_run(returncode=2, stdout="partial", stderr="fatal: disk full")
    assert srv.run_backend(["create", "/memories/x", "y"]) == (
        "fatal: disk full", True,
    )


def test_backend_exit_2_falls_back_to_stdout_when_stderr_is_empty(fake_run):
    fake_run(returncode=2, stdout="partial", stderr="")
    assert srv.run_backend(["scopes"]) == ("partial", True)


def test_backend_failure_with_no_output_still_names_the_exit_code(fake_run):
    """Negative assertion on silence: a failure must never surface empty text."""
    fake_run(returncode=9, stdout="", stderr="")
    text, is_error = srv.run_backend(["scopes"])
    assert is_error and "9" in text


def test_backend_oserror_is_reported_not_raised(fake_run):
    """An unexecutable backend must become a tool error, not crash the server."""
    fake_run(raises=OSError("no such file"))
    text, is_error = srv.run_backend(["scopes"])
    assert is_error and "could not execute backend" in text


def test_backend_is_invoked_through_bash_with_the_mapped_argv(fake_run):
    captured = fake_run(returncode=0, stdout="ok")
    srv.run_backend(["view", "/memories/a/b.md"])
    assert captured["cmd"] == ["bash", srv.BACKEND_CMD, "view", "/memories/a/b.md"]
    assert captured["env"]["MEMORY_AGENT_ID"]


# ── _map_memory: the memory_20250818 command surface ─────────────────────────

@pytest.mark.parametrize(
    "params,expected",
    [
        ({"command": "view", "path": "/memories/a"}, ["view", "/memories/a"]),
        (
            {"command": "view", "path": "/memories/a", "view_range": [1, 20]},
            ["view", "/memories/a", "1", "20"],
        ),
        (
            {"command": "create", "path": "/memories/a", "file_text": "body"},
            ["create", "/memories/a", "body"],
        ),
        ({"command": "create", "path": "/memories/a"}, ["create", "/memories/a", ""]),
        (
            {"command": "str_replace", "path": "/m/a", "old_str": "x", "new_str": "y"},
            ["str_replace", "/m/a", "x", "y"],
        ),
        (
            {"command": "str_replace", "path": "/m/a"},
            ["str_replace", "/m/a", "", ""],
        ),
        (
            {"command": "insert", "path": "/m/a", "insert_line": 4, "insert_text": "t"},
            ["insert", "/m/a", "4", "t"],
        ),
        ({"command": "insert", "path": "/m/a"}, ["insert", "/m/a", "0", ""]),
        ({"command": "delete", "path": "/m/a"}, ["delete", "/m/a"]),
        (
            {"command": "rename", "old_path": "/m/a", "new_path": "/m/b"},
            ["rename", "/m/a", "/m/b"],
        ),
    ],
)
def test_map_memory_argv(params, expected):
    assert srv._map_memory(params) == expected


@pytest.mark.parametrize(
    "view_range", [None, [], [1], [1, 2, 3]],
)
def test_map_memory_ignores_a_malformed_view_range(view_range):
    """Only an exact pair is a range; anything else views the whole file."""
    params = {"command": "view", "path": "/m/a", "view_range": view_range}
    assert srv._map_memory(params) == ["view", "/m/a"]


@pytest.mark.parametrize("cmd", [None, "", "nonsense", "SEARCH"])
def test_map_memory_returns_none_for_an_unknown_command(cmd):
    assert srv._map_memory({"command": cmd}) is None


# ── _map_extensions: the memory_extensions command surface ───────────────────

@pytest.mark.parametrize(
    "params,expected",
    [
        ({"command": "search", "query": "q"}, ["search", "q"]),
        ({"command": "search"}, ["search", ""]),
        (
            {"command": "search", "query": "q", "scope": "proj", "limit": 5,
             "regex": True},
            ["search", "q", "--scope", "proj", "--limit", "5", "--regex"],
        ),
        ({"command": "search", "query": "q", "regex": False}, ["search", "q"]),
        ({"command": "scopes"}, ["scopes"]),
        ({"command": "preamble"}, ["preamble"]),
        ({"command": "sync-status"}, ["sync-status"]),
        ({"command": "drain-sync"}, ["drain-sync"]),
        ({"command": "drain-sync", "limit": 3}, ["drain-sync", "--limit", "3"]),
        ({"command": "commit-sync", "job_id": "j1"}, ["commit-sync", "j1"]),
        ({"command": "commit-sync"}, ["commit-sync", ""]),
        ({"command": "release-sync", "job_id": "j1"}, ["release-sync", "j1"]),
        ({"command": "ttl-sweep"}, ["ttl-sweep"]),
        ({"command": "ttl-sweep", "dry_run": True}, ["ttl-sweep", "--dry-run"]),
        ({"command": "ttl-sweep", "dry_run": False}, ["ttl-sweep"]),
        ({"command": "audit"}, ["audit"]),
        ({"command": "audit", "since": "2026-01-01"}, ["audit", "--since", "2026-01-01"]),
        ({"command": "rethink", "path": "/m/a", "file_text": "t"},
         ["rethink", "/m/a", "t"]),
        ({"command": "rethink", "path": "/m/a", "file_text": "t", "expected_sha": "ab"},
         ["rethink", "/m/a", "t", "ab"]),
        ({"command": "sha", "path": "/m/a"}, ["sha", "/m/a"]),
        ({"command": "sha"}, ["sha", ""]),
    ],
)
def test_map_extensions_argv(params, expected):
    assert srv._map_extensions(params) == expected


@pytest.mark.parametrize("cmd", [None, "", "view", "unknown"])
def test_map_extensions_returns_none_for_an_unknown_command(cmd):
    assert srv._map_extensions({"command": cmd}) is None


# ── _tool_result ─────────────────────────────────────────────────────────────

def test_tool_result_omits_is_error_on_success():
    """Negative assertion: absence of isError IS the success signal."""
    assert srv._tool_result("ok", False) == {
        "content": [{"type": "text", "text": "ok"}],
    }


def test_tool_result_sets_is_error_on_failure():
    assert srv._tool_result("bad", True)["isError"] is True


# ── Handlers ─────────────────────────────────────────────────────────────────

def test_initialize_advertises_the_protocol_version_and_tools_capability():
    result = srv.handle_initialize(1, {})["result"]
    assert result["protocolVersion"] == srv.PROTOCOL_VERSION
    assert result["serverInfo"] == srv.SERVER_INFO
    assert "tools" in result["capabilities"]


def test_tools_list_advertises_both_tools():
    tools = srv.handle_tools_list(1, {})["result"]["tools"]
    assert [t["name"] for t in tools] == ["memory", "memory_extensions"]


def test_tools_call_routes_memory_to_the_backend(fake_run):
    captured = fake_run(returncode=0, stdout="file contents")
    resp = srv.handle_tools_call(
        1, {"name": "memory", "arguments": {"command": "view", "path": "/m/a"}}
    )
    assert captured["cmd"][-2:] == ["view", "/m/a"]
    assert resp["result"]["content"][0]["text"] == "file contents"
    assert "isError" not in resp["result"]


def test_tools_call_routes_extensions_to_the_backend(fake_run):
    captured = fake_run(returncode=0, stdout="SCOPE ...")
    srv.handle_tools_call(1, {"name": "memory_extensions",
                              "arguments": {"command": "scopes"}})
    assert captured["cmd"][-1] == "scopes"


def test_tools_call_accepts_the_input_key_as_well_as_arguments(fake_run):
    captured = fake_run(returncode=0, stdout="ok")
    srv.handle_tools_call(1, {"name": "memory",
                              "input": {"command": "delete", "path": "/m/a"}})
    assert captured["cmd"][-2:] == ["delete", "/m/a"]


def test_tools_call_with_no_arguments_at_all_reports_an_unknown_command(fake_run):
    fake_run(returncode=0, stdout="")
    resp = srv.handle_tools_call(1, {"name": "memory"})
    assert resp["result"]["isError"] is True


@pytest.mark.parametrize("tool", ["memory", "memory_extensions"])
def test_tools_call_reports_an_unknown_command_without_touching_the_backend(
    tool, monkeypatch
):
    """A mapping failure must not reach the shell at all."""

    def _explode(*a, **k):
        raise AssertionError("backend must not be invoked for an unknown command")

    monkeypatch.setattr(subprocess, "run", _explode)
    resp = srv.handle_tools_call(1, {"name": tool, "arguments": {"command": "zzz"}})
    assert resp["result"]["isError"] is True
    assert "zzz" in resp["result"]["content"][0]["text"]


def test_tools_call_on_an_unknown_tool_is_a_method_not_found_error():
    resp = srv.handle_tools_call(1, {"name": "not_a_tool"})
    assert resp["error"]["code"] == -32601
    assert "not_a_tool" in resp["error"]["message"]


def test_backend_error_surfaces_as_an_is_error_tool_result(fake_run):
    fake_run(returncode=1, stdout="Error: scope not writable by this agent")
    resp = srv.handle_tools_call(
        1, {"name": "memory", "arguments": {"command": "create", "path": "/m/a"}}
    )
    assert resp["result"]["isError"] is True
    assert "not writable" in resp["result"]["content"][0]["text"]


# ── main loop ────────────────────────────────────────────────────────────────

def _run_main(monkeypatch, capsys, lines: str):
    monkeypatch.setattr(sys, "stdin", io.StringIO(lines))
    srv.main()
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_main_answers_initialize(monkeypatch, capsys):
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    responses = _run_main(monkeypatch, capsys, line + "\n")
    assert responses[0]["result"]["protocolVersion"] == srv.PROTOCOL_VERSION


def test_main_skips_blank_lines(monkeypatch, capsys):
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    responses = _run_main(monkeypatch, capsys, "\n  \n" + line + "\n\n")
    assert len(responses) == 1


def test_main_reports_a_parse_error_with_a_null_id(monkeypatch, capsys):
    responses = _run_main(monkeypatch, capsys, "{not json}\n")
    assert responses[0]["error"]["code"] == -32700
    assert responses[0]["id"] is None


def test_main_reports_method_not_found_for_a_request(monkeypatch, capsys):
    line = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "nope"})
    responses = _run_main(monkeypatch, capsys, line + "\n")
    assert responses[0]["error"]["code"] == -32601


def test_main_silently_drops_a_notification(monkeypatch, capsys):
    """JSON-RPC: a request without an id gets no response. Asserted as silence."""
    line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert _run_main(monkeypatch, capsys, line + "\n") == []


def test_main_converts_a_handler_exception_into_an_internal_error(
    monkeypatch, capsys
):
    """A crash in a handler must become a JSON-RPC error, not kill the loop."""

    def _boom(req_id, params):
        raise RuntimeError("handler exploded")

    monkeypatch.setitem(srv._HANDLERS, "initialize", _boom)
    line = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "initialize"})
    responses = _run_main(monkeypatch, capsys, line + "\n")
    assert responses[0]["error"]["code"] == -32603
    assert "handler exploded" in responses[0]["error"]["message"]


def test_main_keeps_serving_after_a_bad_line(monkeypatch, capsys):
    """The loop is long-lived; one malformed message must not end the session."""
    good = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"})
    responses = _run_main(monkeypatch, capsys, "{bad}\n" + good + "\n")
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"]["protocolVersion"] == srv.PROTOCOL_VERSION


def test_main_treats_a_null_params_as_empty(monkeypatch, capsys):
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": None})
    responses = _run_main(monkeypatch, capsys, line + "\n")
    assert "result" in responses[0]
