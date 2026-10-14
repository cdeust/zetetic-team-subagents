"""The boot sections of hooks/session-start.sh run in parallel, joined in order.

Measured 2026-10-14: the sequential hook took 11.6 s. Every section is a
separate tool, so the slowest one, not the sum, should set the startup time,
while the printed order stays the documented one.
"""

from pathlib import Path
import os
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DELAY_S = 1.0  # source: per-tool stub delay; 5 slow tools would cost 5 s sequentially
SLOW_TOOLS = (
    "difficulty-book-manager.sh",
    "memory-tool.sh",
    "worktree-manager.sh",
    "dev-symlink-doctor.sh",
    "session-store.sh",
)


def _plugin(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "hooks" / "session-start.sh").write_text(
        (ROOT / "hooks" / "session-start.sh").read_text()
    )
    for name in SLOW_TOOLS:
        tool = tmp_path / "tools" / name
        tool.write_text(f"#!/usr/bin/env bash\nsleep {DELAY_S}\necho \"out:{name}:$1\"\n")
        tool.chmod(0o755)
    return tmp_path


def test_sections_overlap_and_keep_their_order(tmp_path):
    plugin = _plugin(tmp_path)
    scratch = tmp_path / "tmpdir"
    scratch.mkdir()
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin), "TMPDIR": str(scratch)}
    start = time.monotonic()
    out = subprocess.run(
        ["bash", str(plugin / "hooks" / "session-start.sh")],
        input="{}", capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )
    elapsed = time.monotonic() - start
    assert out.returncode == 0
    assert elapsed < DELAY_S * 5  # sequential costs 7 stub-seconds; the longest job is 2
    headings = [
        "Difficulty Books", "Memory Scopes", "Agent Worktrees",
        "Worktree Sweep", "Dev Symlink Montage", "Session Cache",
    ]
    positions = [out.stdout.index(h) for h in headings]
    assert positions == sorted(positions)
    assert list(scratch.iterdir()) == []  # the EXIT trap removed the section files


def test_failing_section_leaves_the_others_and_exit_code(tmp_path):
    plugin = _plugin(tmp_path)
    (plugin / "tools" / "difficulty-book-manager.sh").write_text("#!/usr/bin/env bash\nexit 3\n")
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin)}
    out = subprocess.run(
        ["bash", str(plugin / "hooks" / "session-start.sh")],
        input="{}", capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )
    assert out.returncode == 0
    assert "(none)" in out.stdout
    assert "out:session-store.sh:load" in out.stdout
