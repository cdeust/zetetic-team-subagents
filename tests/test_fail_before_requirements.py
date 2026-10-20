"""A missing pytest dependency must stop the fail-before suite, with the diagnostic."""
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
    assert 'cannot import pytest' in result.stderr
    assert 'FATAL: tools/dev-python.sh' in result.stderr
    assert 'SKIP:' not in result.stdout
