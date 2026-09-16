"""A missing pytest dependency must fail the fail-before suite."""
import os
from pathlib import Path
import subprocess


def test_fail_before_suite_requires_pytest():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['bash', str(root / 'tools/tests/fail-before/run-tests.sh')],
        env=dict(os.environ, PYTHON_BIN='/usr/bin/false'),
        text=True,
        capture_output=True,
        cwd=root,
    )
    assert result.returncode == 1, result
    assert 'FATAL: pytest is not importable' in result.stdout
    assert 'SKIP:' not in result.stdout
