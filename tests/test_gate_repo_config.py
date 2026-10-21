"""This repository's own .zetetic/gate.json: valid, and its test map covers what drifts silently.

An affected-only gate is only as good as its map. These tests pin the two mappings that a one-file change
once got wrong: the files copied into plugins/zetetic-gates (scripts/sync-gates.py FILES, checked by a drift
test) and the gate's own modules.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import gate_config as cfg  # noqa: E402


def synced_files() -> list:
    tree = ast.parse((ROOT / "scripts" / "sync-gates.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FILES":
            return list(ast.literal_eval(node.value))
    raise AssertionError("scripts/sync-gates.py no longer defines FILES")


def selected_tests(changed: str) -> list:
    steps = cfg.plan(cfg.load(str(ROOT)), str(ROOT), [changed])
    return [t for s in steps if s.name.startswith("tests") for t in s.argv if t.startswith("tests/")]


def test_the_repository_declares_a_valid_config():
    assert cfg.declaration(str(ROOT)) == "config"


@pytest.mark.parametrize("path", synced_files())
def test_a_synced_file_selects_the_drift_tests(path):
    assert "tests/test_shared_host_gates.py" in selected_tests(path)


@pytest.mark.parametrize("path", sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "hooks" / "lib").glob("gate_*.py")))
def test_each_gate_module_selects_the_gate_tests(path):
    assert "tests/test_gate_async.py" in selected_tests(path)


def test_a_change_to_the_config_runs_everything():
    steps = cfg.plan(cfg.load(str(ROOT)), str(ROOT), [".zetetic/gate.json"])
    assert [s.name for s in steps][-1] == "tests-full"


def selected_checks(changed: str) -> list:
    return [s.name for s in cfg.plan(cfg.load(str(ROOT)), str(ROOT), [changed])]


@pytest.mark.parametrize("path", ["hooks/hooks.json", "hooks/gate-proof.py", "hooks/run-python.sh", ".claude-plugin/plugin.json",
                                  ".claude-plugin/marketplace.json", "docs/gate.md", "README.md", "CONTRIBUTING.md",
                                  "agents/genius/feynman.md", "skills/_index.md", "commands/_index.md", "tools/doc-count-check.sh"])
def test_a_change_that_can_move_a_documented_count_selects_doc_count_check(path):
    """PR #169 round 1: README/CONTRIBUTING said 24 hook registrations, the tree had 27, and the affected-only
    gate had selected neither doc-count-check nor the suite that runs it, so CI was the first to see it."""
    assert "doc-count" in selected_checks(path)


def test_the_documented_counts_match_the_tree():
    import subprocess
    out = subprocess.run(["bash", str(ROOT / "tools" / "doc-count-check.sh")], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
