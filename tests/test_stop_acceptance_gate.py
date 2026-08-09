"""Contract tests for hooks/stop-acceptance-gate.py.

A Stop hook that gets this wrong either freezes every session or silently stops
gating. It was at 0% coverage (issue #71).

The module's whole design is a two-tier policy, and the tests are organised
around proving both tiers AND the boundary between them:

* **WARN (default)** must never block. Every path through it ends in exit 0,
  and the red case writes to stderr rather than emitting a block decision. A
  heavy check shipped to every session that could block by default is the
  product-safety failure the docstring cites.
* **BLOCK (opt-in)** must block only under an `.abl-gate.json` marker and only
  on a genuine non-zero exit from the real gate.
* **Fail-open everywhere else.** Unreadable stdin, non-object JSON, a
  hand-edited marker, a missing or non-executable gate, a timeout, an OSError:
  each allows the turn to end. These are asserted one at a time because they
  reach exit 0 by different routes, and collapsing them would hide a
  regression that made one of them raise.

`allow`, `block` and `warn` are `NoReturn` (they `sys.exit`), so every test
drives them through `pytest.raises(SystemExit)` and asserts on the code plus
the captured streams.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "stop-acceptance-gate.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("stop_acceptance_gate", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load_hook()

# Captured before any fixture patches it: the `never_the_real_repo` autouse
# fixture replaces hook.repo_root for every test, so the tests OF repo_root
# itself have to reach the genuine implementation.
_REAL_REPO_ROOT = hook.repo_root


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def never_the_real_repo(tmp_path, monkeypatch):
    """Point every test at an empty tmp root, before anything else runs.

    Without this, a test that reaches `main()`'s WARN tier resolves
    `repo_root()` to THIS repository, finds the real executable
    `tools/acceptance-gate.sh`, and runs the real gate for up to
    WARN_TIMEOUT_S. That was measured at ~50s for one test, and worse, it made
    the assertion pass for the wrong reason: the hook allowed because the real
    gate happened to be green, not because the code under test decided to.

    An empty root has no `tools/acceptance-gate.sh`, so `main()` allows at the
    gate-missing check and never spawns anything. Tests that need a gate ask for
    `fake_repo`, which re-patches `repo_root` afterwards (rules/coding-standards
    §13.1 G3: deterministic and isolated, no shared fixed paths).
    """
    monkeypatch.setattr(hook, "repo_root", lambda: str(tmp_path / "_empty_root"))
    (tmp_path / "_empty_root").mkdir()
    # The BLOCK-everywhere opt-in (ABL_STOP_BLOCK) is set in the maintainer's
    # shell, and it runs before the WARN tier. Inheriting it would silently
    # rewrite what every WARN-tier test measures — a test must not depend on
    # the environment of whoever runs it. Tests that exercise BLOCK set it
    # themselves.
    monkeypatch.delenv("ABL_STOP_BLOCK", raising=False)


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A tree with an executable gate script, wired as the hook's repo root."""
    tools = tmp_path / "tools"
    tools.mkdir()
    gate = tools / "acceptance-gate.sh"
    gate.write_text("#!/usr/bin/env bash\nexit 0\n")
    gate.chmod(0o755)
    monkeypatch.setattr(hook, "repo_root", lambda: str(tmp_path))
    monkeypatch.delenv("ABL_STOP_WARN", raising=False)
    return tmp_path


def _stdin(monkeypatch, payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))


def _run_main(monkeypatch, payload="{}"):
    _stdin(monkeypatch, payload)
    with pytest.raises(SystemExit) as excinfo:
        hook.main()
    return excinfo.value.code


# ── the three terminal signals ───────────────────────────────────────────────

def test_allow_exits_zero_and_says_nothing(capsys):
    """A Stop hook signals 'no objection' by exiting 0 silently."""
    with pytest.raises(SystemExit) as excinfo:
        hook.allow()
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_block_emits_a_block_decision_on_stdout(capsys):
    with pytest.raises(SystemExit) as excinfo:
        hook.block("because")
    assert excinfo.value.code == 0, "the hook signals via JSON, not via exit code"
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"decision": "block", "reason": "because"}


def test_warn_writes_to_stderr_and_does_not_block(capsys):
    with pytest.raises(SystemExit) as excinfo:
        hook.warn("heads up")
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert captured.err.strip() == "heads up"
    assert captured.out == "", "a warning must not emit a block decision"


def test_note_names_the_tool_and_the_exception(capsys):
    hook._note("thing failed", ValueError("detail"))
    err = capsys.readouterr().err
    assert "[acceptance-gate]" in err and "ValueError" in err and "detail" in err


# ── timeouts are bounds, not decoration ──────────────────────────────────────

def test_warn_tier_timeout_is_much_shorter_than_the_block_tier():
    """WARN runs opportunistically at turn end; it must degrade, not stall."""
    assert hook.WARN_TIMEOUT_S < hook.GATE_TIMEOUT_S
    assert hook.WARN_TIMEOUT_S > 0


# ── repo_root / has_changes ──────────────────────────────────────────────────

def test_repo_root_uses_git_toplevel(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="/repo\n"))
    assert _REAL_REPO_ROOT() == "/repo"


def test_repo_root_falls_back_to_cwd_when_git_output_is_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="\n"))
    assert _REAL_REPO_ROOT() == os.getcwd()


@pytest.mark.parametrize("exc", [OSError("no git"), subprocess.SubprocessError("x")])
def test_repo_root_falls_back_to_cwd_when_git_cannot_run(monkeypatch, exc):
    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _REAL_REPO_ROOT() == os.getcwd()


def test_has_changes_is_true_when_status_is_not_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=" M file\n"))
    assert hook.has_changes("/repo") is True


def test_has_changes_is_false_on_a_clean_tree(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="\n"))
    assert hook.has_changes("/repo") is False


def test_has_changes_is_false_when_git_cannot_run(monkeypatch):
    """Fail-open: an unknown tree state must not trigger the gate."""

    def _raise(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert hook.has_changes("/repo") is False


# ── gate_args ────────────────────────────────────────────────────────────────

def test_gate_args_uses_the_loop_config_by_default():
    args = hook.gate_args("/repo/tools/acceptance-gate.sh", "/repo", {})
    assert args[0] == "/repo/tools/acceptance-gate.sh"
    assert args[1:] == ["--root", "/repo", "--config", "/repo/memory/acceptance-gates.loop.yaml"]


def test_gate_args_honours_a_marker_config():
    args = hook.gate_args("/repo/tools/acceptance-gate.sh", "/repo", {"config": "custom.yaml"})
    assert args[4] == "/repo/custom.yaml"


def test_gate_args_passes_a_diff_range_when_both_ends_are_present():
    args = hook.gate_args("/repo/tools/acceptance-gate.sh", "/repo", {"diff_base": "a", "diff_head": "b"})
    assert args[-4:] == ["--diff-base", "a", "--diff-head", "b"]


@pytest.mark.parametrize(
    "cfg", [{"diff_base": "a"}, {"diff_head": "b"}, {"diff_base": "", "diff_head": "b"}]
)
def test_gate_args_omits_a_half_specified_diff_range(cfg):
    """Negative assertion: half a range is not a range."""
    assert "--diff-base" not in hook.gate_args("/repo/tools/acceptance-gate.sh", "/repo", cfg)


# ── run_gate ─────────────────────────────────────────────────────────────────

def test_run_gate_returns_the_real_exit_code_and_unmet_list(monkeypatch):
    payload = json.dumps({"unmet": ["tests", "coverage"]})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, payload))
    assert hook.run_gate(["g"], "/repo", 10) == (1, ["tests", "coverage"])


def test_run_gate_treats_non_json_output_as_no_unmet_criteria(monkeypatch, capsys):
    """Degraded, but NOT silent: the note is the signal, and it is asserted."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, "not json"))
    assert hook.run_gate(["g"], "/repo", 10) == (1, [])
    assert "was not JSON" in capsys.readouterr().err


def test_run_gate_is_quiet_when_the_output_parses(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, '{"unmet": []}'))
    hook.run_gate(["g"], "/repo", 10)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "exc", [OSError("cannot exec"), subprocess.TimeoutExpired("g", 1)]
)
def test_run_gate_returns_none_when_it_cannot_run(monkeypatch, exc):
    """None is the 'no verdict' signal; callers must allow on it."""

    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(subprocess, "run", _raise)
    assert hook.run_gate(["g"], "/repo", 10) is None


# ── verdict_reason ───────────────────────────────────────────────────────────

def test_verdict_reason_names_the_tool_and_exit_code():
    assert hook.verdict_reason("prefix", 3, []) == (
        "prefix (tools/acceptance-gate.sh exit 3)."
    )


def test_verdict_reason_lists_unmet_criteria():
    assert "Unmet: a; b" in hook.verdict_reason("p", 1, ["a", "b"])


def test_verdict_reason_caps_the_unmet_list_at_six():
    reason = hook.verdict_reason("p", 1, [f"g{i}" for i in range(20)])
    assert "g5" in reason and "g6" not in reason


# ── main: fail-open routes ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["", "   ", "not json", '{"unclosed":'])
def test_main_allows_on_unparseable_stdin(monkeypatch, raw, capsys):
    assert _run_main(monkeypatch, raw) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("raw", ["[]", "42", '"x"', "null", "true"])
def test_main_allows_on_valid_non_object_json(monkeypatch, raw):
    assert _run_main(monkeypatch, raw) == 0


def test_main_allows_when_stdin_read_raises(monkeypatch):
    class Exploding:
        def read(self):
            raise OSError("gone")

    monkeypatch.setattr(sys, "stdin", Exploding())
    with pytest.raises(SystemExit) as excinfo:
        hook.main()
    assert excinfo.value.code == 0


def test_main_allows_immediately_when_already_in_a_forced_continuation(
    monkeypatch, fake_repo
):
    """The loop bound: stop_hook_active means do not block again."""

    def _explode(*a, **k):
        raise AssertionError("must not run the gate during a forced continuation")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert _run_main(monkeypatch, {"stop_hook_active": True}) == 0


def test_main_allows_when_the_gate_script_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "repo_root", lambda: str(tmp_path))
    assert _run_main(monkeypatch, {}) == 0


def test_main_allows_when_the_gate_script_is_not_executable(
    monkeypatch, tmp_path
):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "acceptance-gate.sh").write_text("#!/usr/bin/env bash\n")
    (tools / "acceptance-gate.sh").chmod(0o644)
    monkeypatch.setattr(hook, "repo_root", lambda: str(tmp_path))
    assert _run_main(monkeypatch, {}) == 0


# ── main: BLOCK tier (opt-in) ────────────────────────────────────────────────

def _write_marker(root: Path, content):
    (root / ".abl-gate.json").write_text(
        content if isinstance(content, str) else json.dumps(content)
    )


def test_marker_present_and_gate_red_blocks(monkeypatch, fake_repo, capsys):
    _write_marker(fake_repo, {})
    payload = json.dumps({"unmet": ["tests failed"]})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, payload))
    assert _run_main(monkeypatch, {}) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "tests failed" in decision["reason"]
    assert "exit 1" in decision["reason"]


def test_marker_present_and_gate_green_allows(monkeypatch, fake_repo, capsys):
    _write_marker(fake_repo, {})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, '{"unmet": []}'))
    assert _run_main(monkeypatch, {}) == 0
    assert capsys.readouterr().out == "", "a green gate must not block"


def test_marker_present_but_gate_unrunnable_allows(monkeypatch, fake_repo, capsys):
    """A broken guard must not freeze the session, even in the blocking tier."""

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired("gate", 1)

    monkeypatch.setattr(subprocess, "run", _raise)
    _write_marker(fake_repo, {})
    assert _run_main(monkeypatch, {}) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("content", ["{not json}", "[]", '"str"', "42"])
def test_a_hand_edited_marker_fails_open(monkeypatch, fake_repo, content, capsys):
    _write_marker(fake_repo, content)

    def _explode(*a, **k):
        raise AssertionError("a malformed marker must not reach the gate")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert _run_main(monkeypatch, {}) == 0
    assert capsys.readouterr().out == ""


def test_block_tier_uses_the_long_timeout(monkeypatch, fake_repo):
    seen = {}

    def _run(args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _Proc(0, "{}")

    _write_marker(fake_repo, {})
    monkeypatch.setattr(subprocess, "run", _run)
    _run_main(monkeypatch, {})
    assert seen["timeout"] == hook.GATE_TIMEOUT_S


# ── main: WARN tier (default) ────────────────────────────────────────────────

def test_warn_tier_reports_a_red_gate_without_blocking(monkeypatch, fake_repo, capsys):
    """The central property: default-tier red is stderr, never a block decision."""
    monkeypatch.setattr(hook, "has_changes", lambda root: True)
    payload = json.dumps({"unmet": ["coverage"]})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, payload))
    assert _run_main(monkeypatch, {}) == 0
    captured = capsys.readouterr()
    assert captured.out == "", "WARN must never emit a block decision"
    assert "RED (non-blocking warning)" in captured.err
    assert "coverage" in captured.err
    assert "ABL_STOP_WARN=off" in captured.err, "the warning must say how to silence it"


def test_warn_tier_is_silent_when_the_gate_is_green(monkeypatch, fake_repo, capsys):
    monkeypatch.setattr(hook, "has_changes", lambda root: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, '{"unmet": []}'))
    assert _run_main(monkeypatch, {}) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_warn_tier_does_not_run_on_a_clean_tree(monkeypatch, fake_repo):
    """Pure chat turns stay cheap: no changes, no gate invocation."""
    monkeypatch.setattr(hook, "has_changes", lambda root: False)

    def _explode(*a, **k):
        raise AssertionError("the gate must not run on a clean tree")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert _run_main(monkeypatch, {}) == 0


@pytest.mark.parametrize("value", ["off", "OFF", "Off"])
def test_warn_tier_is_suppressible(monkeypatch, fake_repo, value):
    monkeypatch.setenv("ABL_STOP_WARN", value)

    def _explode(*a, **k):
        raise AssertionError("ABL_STOP_WARN=off must skip the gate entirely")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert _run_main(monkeypatch, {}) == 0


def test_warn_tier_allows_when_the_gate_cannot_run(monkeypatch, fake_repo, capsys):
    monkeypatch.setattr(hook, "has_changes", lambda root: True)

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired("gate", 1)

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _run_main(monkeypatch, {}) == 0
    assert capsys.readouterr().err == ""


def test_warn_tier_checks_the_committed_base_gate_set(monkeypatch, fake_repo):
    """WARN must not use the autonomous-loop variant of the gate config."""
    seen = {}

    def _run(args, **kwargs):
        seen["args"] = args
        seen["timeout"] = kwargs.get("timeout")
        return _Proc(0, "{}")

    monkeypatch.setattr(hook, "has_changes", lambda root: True)
    monkeypatch.setattr(subprocess, "run", _run)
    _run_main(monkeypatch, {})
    assert seen["args"][4].endswith("memory/acceptance-gates.yaml")
    assert "loop" not in seen["args"][2]
    assert seen["timeout"] == hook.WARN_TIMEOUT_S
