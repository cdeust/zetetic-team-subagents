"""The boot sections of hooks/session-start.sh run in parallel, joined in order.

Measured 2026-10-14: the sequential hook took 11.6 s. Every section is a
separate tool, so the slowest one, not the sum, should set the startup time,
while the printed order stays the documented one.

Concurrency is proven by events, not by elapsed time: each stub tool announces
itself on a fifo and then blocks until the test releases it. Run one after the
other, the first tool would block for ever and the other four would never
announce themselves, so seeing all five announcements before any release
proves the five sections were alive at the same moment.
"""

from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SLOW_TOOLS = (
    "difficulty-book-manager.sh",
    "memory-tool.sh",
    "worktree-manager.sh",
    "dev-symlink-doctor.sh",
    "session-store.sh",
)
RELEASES = 32  # source: more release bytes than the 7 tool calls of one boot, so none can block


def _plugin(tmp_path, gated):
    (tmp_path / "tools").mkdir()
    shutil.copytree(ROOT / "hooks", tmp_path / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    for name in SLOW_TOOLS:
        tool = tmp_path / "tools" / name
        prelude = (f'echo {name} > "$START_FIFO"\nIFS= read -r -n 1 _ < "$GO_FIFO"\n' if gated else "")
        tool.write_text(f'#!/usr/bin/env bash\n{prelude}echo "out:{name}:$1"\n')
        tool.chmod(0o755)
    return tmp_path


def test_sections_overlap_and_keep_their_order(tmp_path):
    plugin = _plugin(tmp_path, gated=True)
    scratch = tmp_path / "tmpdir"
    scratch.mkdir()
    for name in ("start", "go"):
        os.mkfifo(tmp_path / name)
    # Held read-write, so the tools' open() never blocks and nothing sees EOF.
    start = os.fdopen(os.open(tmp_path / "start", os.O_RDWR), "r")
    go = os.open(tmp_path / "go", os.O_RDWR)
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin), "TMPDIR": str(scratch),
           "START_FIFO": str(tmp_path / "start"), "GO_FIFO": str(tmp_path / "go")}
    hook = subprocess.Popen(
        ["bash", str(plugin / "hooks" / "session-start.sh")],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, env=env, cwd=tmp_path,
    )
    announced = set()
    while len(announced) < len(SLOW_TOOLS):
        announced.add(start.readline().strip())  # blocks until a tool is running
    assert announced == set(SLOW_TOOLS)  # all five alive before any was released
    os.write(go, b"g" * RELEASES)
    out = hook.communicate()[0]
    assert hook.returncode == 0
    headings = [
        "Difficulty Books", "Memory Scopes", "Agent Worktrees",
        "Stale Worktrees and Branches", "Dev Symlink Montage", "Session Cache",
    ]
    positions = [out.index(h) for h in headings]
    assert positions == sorted(positions)
    assert list(scratch.iterdir()) == []  # the runner removed its section files


def test_failing_section_leaves_the_others_and_exit_code(tmp_path):
    plugin = _plugin(tmp_path, gated=False)
    (plugin / "tools" / "difficulty-book-manager.sh").write_text("#!/usr/bin/env bash\nexit 3\n")
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin)}
    out = subprocess.run(
        ["bash", str(plugin / "hooks" / "session-start.sh")],
        input="{}", capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert out.returncode == 0
    assert "(none)" in out.stdout
    assert "out:session-store.sh:load" in out.stdout
