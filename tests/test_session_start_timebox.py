"""Regression: the portable watchdog of hooks/session-start.sh held the pipe open.

Without coreutils `timeout` (stock macOS), run_timeboxed backgrounded
`( sleep N; kill )` inheriting the caller's stdout. A reader such as `| sed`
or `$(...)` then waited for that sleep, so each timeboxed stage cost its whole
budget: measured 2026-10-14, session start took 38.6 s (8 + 4 + 15 + 10 s of
timeboxes) against a 5-10 s hook timeout, although each tool ran in under 0.2 s.
"""

from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "session-start.sh"
BUDGET_S = 10  # source: the timebox the sleep would otherwise cost in full


def _run(body):
    # `command -v` fails for timeout/gtimeout so the watchdog branch is taken
    # on every platform, not only where coreutils is absent.
    program = (
        "command() { return 1; }\n"
        + subprocess.run(
            ["sed", "-n", "/^run_timeboxed() {/,/^}/p", str(SCRIPT)],
            capture_output=True, text=True, check=True,
        ).stdout
        + body
    )
    start = time.monotonic()
    out = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=30)
    return out.stdout, time.monotonic() - start


def test_piped_stage_does_not_wait_for_the_watchdog():
    out, elapsed = _run(f"run_timeboxed {BUDGET_S} echo ok | sed 's/^/ /'")
    assert out == " ok\n"
    assert elapsed < BUDGET_S / 2


def test_command_substitution_does_not_wait_for_the_watchdog():
    out, elapsed = _run(f'x="$(run_timeboxed {BUDGET_S} echo ok)"; echo "$x"')
    assert out == "ok\n"
    assert elapsed < BUDGET_S / 2


def test_hung_command_is_still_killed_at_the_budget():
    _, elapsed = _run("run_timeboxed 1 sleep 30 | cat")
    assert 0.9 < elapsed < 5
