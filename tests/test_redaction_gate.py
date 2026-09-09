"""Contract tests for tools/redaction_gate.py — the mechanism shared by the
Stop and PreToolUse redaction gates (checker resolution, finding quotes, the
WARN/BLOCK opt-in). The hooks' own suites cover their event contracts; this
file pins the mechanism they both call.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from tools import redaction_gate as rg

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "hooks"


def _finding(n: int, rule: str = "EM_DASH", detail: str = "d") -> str:
    return f"<stdin>:{n}: {rule}: {detail}"


# ── resolve_checker ──────────────────────────────────────────────────────────

def test_resolve_checker_prefers_the_copy_beside_the_hook(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    found = rg.resolve_checker(str(HOOKS_DIR))
    assert Path(found) == REPO_ROOT / "tools" / "redaction-checker.sh"


def test_resolve_checker_falls_back_to_plugin_root(tmp_path, monkeypatch):
    tools = tmp_path / "plugin" / "tools"
    tools.mkdir(parents=True)
    checker = tools / "redaction-checker.sh"
    checker.write_text("#!/bin/sh\nexit 0\n")
    checker.chmod(checker.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugin"))
    bare = tmp_path / "bare" / "hooks"
    bare.mkdir(parents=True)
    assert rg.resolve_checker(str(bare)) == str(checker)


def test_resolve_checker_empty_when_nothing_executable(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "redaction-checker.sh").write_text("not executable")
    assert rg.resolve_checker(str(tmp_path / "hooks")) == ""


# ── run_checker ──────────────────────────────────────────────────────────────

def test_run_checker_returns_finding_lines_only(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    checker = rg.resolve_checker(str(HOOKS_DIR))
    findings = rg.run_checker(checker, "We leverage it.\nA plain line.\n")
    assert len(findings) == 1
    assert findings[0].startswith("<stdin>:1: BANNED_WORD")


def test_run_checker_clean_text_is_empty(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    checker = rg.resolve_checker(str(HOOKS_DIR))
    assert rg.run_checker(checker, "The suite passed.\n") == []


def test_run_checker_usage_error_is_no_findings(tmp_path, capsys):
    old = tmp_path / "old-checker.sh"
    old.write_text("#!/bin/sh\necho 'usage' >&2\nexit 2\n")
    old.chmod(old.stat().st_mode | stat.S_IXUSR)
    assert rg.run_checker(str(old), "We leverage it.") == []
    assert "rejected --stdin" in capsys.readouterr().err


def test_run_checker_unrunnable_is_no_findings(tmp_path, capsys):
    assert rg.run_checker(str(tmp_path / "missing.sh"), "text") == []
    assert "could not run" in capsys.readouterr().err


# ── quote_findings / reason_text ─────────────────────────────────────────────

def test_quote_findings_names_line_and_rule():
    quoted = rg.quote_findings([_finding(3, "WEASEL", "studies show")])
    assert quoted == "line 3 WEASEL: studies show"


def test_quote_findings_counts_the_overflow():
    many = [_finding(i) for i in range(1, rg.MAX_QUOTED + 4)]
    quoted = rg.quote_findings(many)
    assert quoted.count("line ") == rg.MAX_QUOTED
    assert quoted.endswith("+3 more")


def test_quote_findings_skips_lines_that_are_not_findings():
    assert rg.quote_findings(["noise", _finding(1)]) == "line 1 EM_DASH: d"


def test_reason_text_blocking_hands_back_the_eval():
    text = rg.reason_text([_finding(1)], True, "the commit message")
    assert text.startswith("Redaction gate: the commit message carries 1 candidate")
    assert "redaction.md" in text and "Rewrite it before sending" in text
    assert rg.MARKER_FILE in text and rg.BLOCK_ENV in text


def test_reason_text_warning_names_the_opt_in():
    text = rg.reason_text([_finding(1), _finding(2)], False, "the message being returned")
    assert text.startswith("⚠ Redaction gate: the message being returned carries 2")
    assert "non-blocking" in text and rg.WARN_ENV in text


# ── opt-in ───────────────────────────────────────────────────────────────────

def test_block_opt_in_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setenv(rg.BLOCK_ENV, "ON")
    assert rg.block_opt_in() is True


def test_block_opt_in_marker_at_repo_root(monkeypatch, tmp_path):
    monkeypatch.delenv(rg.BLOCK_ENV, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    assert rg.block_opt_in() is False
    (tmp_path / rg.MARKER_FILE).write_text("{}")
    assert rg.block_opt_in() is True


def test_warn_silenced(monkeypatch):
    monkeypatch.delenv(rg.WARN_ENV, raising=False)
    assert rg.warn_silenced() is False
    monkeypatch.setenv(rg.WARN_ENV, "off")
    assert rg.warn_silenced() is True


# ── repo_root ────────────────────────────────────────────────────────────────

def test_repo_root_in_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    assert Path(rg.repo_root()) == REPO_ROOT


def test_repo_root_outside_repo_is_cwd(monkeypatch, tmp_path):
    outside = tmp_path / "plain"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert Path(rg.repo_root()).resolve() == outside.resolve()


def test_repo_root_without_git_binary_is_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))  # no git anywhere on it
    assert Path(rg.repo_root()) == Path(os.getcwd())
