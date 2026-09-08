"""Contract tests for hooks/pre-tool-redaction-gate.py — the PreToolUse
redaction gate on outbound prose (commit messages, PR and issue bodies,
GitHub MCP comment bodies). tools/redaction_gate.py owns the mechanism; this
hook owns the extraction and the exit-code contract.

The module is loaded by path: the file name has hyphens and `hooks/` is not a
package. Same technique as tests/test_pre_tool_deletion_gate.py.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "pre-tool-redaction-gate.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("pre_tool_redaction_gate", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_hook()

DASH = "The build is fast — very fast."


def _bash_event(command: str, cwd: str = "") -> dict:
    return {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}}


def _run_main(monkeypatch, event) -> int:
    raw = event if isinstance(event, str) else json.dumps(event)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    return gate.main()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("REDACTION_STOP_BLOCK", raising=False)
    monkeypatch.delenv("REDACTION_STOP_WARN", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)


# ── verb detection ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("command,expected", [
    ("git commit -m x", {"git"}),
    ("git -C /tmp commit -m x", {"git"}),
    ("cd a && git commit -am x", {"git"}),
    ("gh pr create --title t --body b", {"gh"}),
    ("gh issue comment 3 --body b", {"gh"}),
    ("gh release create v1 --notes n", {"gh"}),
    ("git commit -m x && gh pr create --body b", {"git", "gh"}),
    ("ls -la", set()),
    ("echo 'git commit'", set()),
    ("git commit-tree HEAD", set()),
    ("gh pr view 1", set()),
])
def test_verbs_in(command, expected):
    assert gate.verbs_in(command) == expected


# ── prose extraction ─────────────────────────────────────────────────────────

def test_git_message_flags():
    assert gate.prose_from_command('git commit -m "first" -m "second"', "") == "first\nsecond"
    assert gate.prose_from_command("git commit --message=inline", "") == "inline"


def test_git_no_verify_short_flag_is_not_a_prose_flag():
    assert gate.prose_from_command('git commit -n -m "msg"', "") == "msg"


def test_gh_inline_flags():
    out = gate.prose_from_command('gh pr create -t "Title" --body "Body" --notes n', "")
    assert out.split("\n") == ["Title", "Body", "n"]


def test_body_file_read_relative_to_cwd(tmp_path):
    (tmp_path / "notes.md").write_text("from the file\n")
    out = gate.prose_from_command("gh pr comment 1 --body-file notes.md", str(tmp_path))
    assert out == "from the file\n"
    out = gate.prose_from_command("git commit -F notes.md", str(tmp_path))
    assert out == "from the file\n"


def test_body_file_equals_form_and_missing_file(tmp_path):
    (tmp_path / "n.md").write_text("x")
    assert gate.prose_from_command("gh pr create --body-file=n.md", str(tmp_path)) == "x"
    assert gate.prose_from_command("gh pr create --body-file missing.md", str(tmp_path)) == ""
    assert gate.read_body_file("-", str(tmp_path)) == ""


def test_heredoc_body_stays_inside_the_quoted_token():
    cmd = 'git commit -m "$(cat <<\'EOF\'\nfeat: delve\nEOF\n)"'
    assert "feat: delve" in gate.prose_from_command(cmd, "")


def test_unbalanced_quote_falls_back_to_raw_command():
    cmd = 'git commit -m "unterminated'
    assert gate.prose_from_command(cmd, "") == cmd


def test_no_prose_flags_yields_nothing():
    assert gate.prose_from_command("git commit --amend --no-edit", "") == ""
    assert gate.prose_from_command("ls", "") == ""


def test_prose_from_mcp_joins_string_fields_only():
    tin = {"body": "b", "title": "t", "commit_message": 3, "other": "ignored", "text": " "}
    assert gate.prose_from_mcp(tin) == "b\nt"


def test_prose_of_dispatch():
    assert gate.prose_of(_bash_event('git commit -m "m"')) == "m"
    assert gate.prose_of({"tool_name": "mcp__github__add_issue_comment",
                          "tool_input": {"body": "b"}}) == "b"
    assert gate.prose_of({"tool_name": "Read", "tool_input": {"body": "b"}}) == ""
    assert gate.prose_of({"tool_name": "Bash", "tool_input": {"command": 7}}) == ""
    assert gate.prose_of({"tool_name": "Bash", "tool_input": []}) == ""


# ── main: exit-code contract ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["[]", "42", "null", "not json", "", "   "])
def test_main_fails_open_on_bad_payloads(monkeypatch, capsys, raw):
    assert _run_main(monkeypatch, raw) == 0
    assert capsys.readouterr().err == ""


def test_main_silent_without_prose(monkeypatch, capsys):
    assert _run_main(monkeypatch, _bash_event("ls -la")) == 0
    assert capsys.readouterr().err == ""


def test_main_warns_by_default(monkeypatch, capsys):
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 0
    err = capsys.readouterr().err
    assert "line 1 EM_DASH" in err and "non-blocking" in err


def test_main_blocks_under_env_opt_in(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_BLOCK", "on")
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 2
    err = capsys.readouterr().err
    assert "EM_DASH" in err and "this command is about to publish" in err


def test_main_blocks_under_marker(monkeypatch, capsys, tmp_path):
    (tmp_path / ".redaction-gate.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 2
    assert "EM_DASH" in capsys.readouterr().err


def test_main_mcp_subject_names_the_tool(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_BLOCK", "on")
    event = {"tool_name": "mcp__github__add_issue_comment",
             "tool_input": {"body": "Great question! " + DASH}}
    assert _run_main(monkeypatch, event) == 2
    err = capsys.readouterr().err
    assert "mcp__github__add_issue_comment call is about to publish" in err
    assert "PUFFERY" in err and "EM_DASH" in err


def test_main_warn_silenced(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_WARN", "off")
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 0
    assert capsys.readouterr().err == ""


def test_main_clean_message_is_silent(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_BLOCK", "on")
    assert _run_main(monkeypatch, _bash_event('git commit -m "fix: read the file"')) == 0
    assert capsys.readouterr().err == ""


def test_main_fails_open_without_the_shared_module(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_BLOCK", "on")
    monkeypatch.setattr(gate, "_load_gate", lambda: None)
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 0


def test_main_fails_open_without_a_checker(monkeypatch, capsys):
    monkeypatch.setenv("REDACTION_STOP_BLOCK", "on")
    module = gate._load_gate()
    monkeypatch.setattr(module, "resolve_checker", lambda _anchor: "")
    assert _run_main(monkeypatch, _bash_event(f'git commit -m "{DASH}"')) == 0
