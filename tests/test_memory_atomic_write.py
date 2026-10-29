"""Memory writes flush their own file without a system-wide sync dependency."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def atomic_write(target, content, tools):
    environment = {**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        [
            "bash",
            "-euc",
            'source "$1"; atomic_write "$2" "$3"',
            "atomic-write-test",
            str(ROOT / "tools/lib/memory-guards.sh"),
            str(target),
            content,
        ],
        env=environment,
        text=True,
        capture_output=True,
    )


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def test_write_preserves_exact_bytes_without_flushing_unrelated_disks(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "sync", 'echo "global sync must not run" >&2\nexit 73\n')
    target = tmp_path / "memory with spaces.md"
    target.write_text("old content")
    content = "description: mémoire\n\nnew content\n"
    result = atomic_write(target, content, tools)
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == content.encode()
    assert not list(tmp_path.glob("*.tmp.*"))


def test_failed_file_flush_keeps_the_previous_memory(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "python3", 'echo "file flush failed" >&2\nexit 71\n')
    target = tmp_path / "memory.md"
    target.write_text("previous complete memory")
    result = atomic_write(target, "new memory", tools)
    assert result.returncode == 71
    assert "file flush failed" in result.stderr
    assert target.read_text() == "previous complete memory"
