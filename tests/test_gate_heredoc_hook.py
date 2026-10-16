"""The packaged PreToolUse hook reads here-document bodies as data.

Source: POSIX Shell Command Language §2.7.4 (Here-Document).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEREDOC = "mkdir -p notes && cat > notes/a.txt <<'EOF'\nthe git hook won't run\nEOF"


@pytest.fixture(params=['full', 'standalone'])
def package(request, tmp_path):
    if request.param == 'full':
        return ROOT
    target = tmp_path / 'installed'
    shutil.copytree(ROOT / 'plugins/zetetic-gates', target)
    return target


@pytest.fixture
def consumer(tmp_path):
    path = tmp_path / 'consumer'
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    (path / '.zetetic.conf').write_text('ZETETIC_PROFILE=strict\n')
    return path


def run_bash_hook(package, consumer, command):
    event = {'hook_event_name': 'PreToolUse', 'cwd': str(consumer),
             'tool_name': 'Bash', 'tool_input': {'command': command}}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
    return subprocess.run([sys.executable, str(package / 'hooks/zetetic-gates.py')],
                          input=json.dumps(event), text=True, capture_output=True,
                          cwd=consumer, env=env)


def test_heredoc_prose_is_not_refused(package, consumer):
    result = run_bash_hook(package, consumer, HEREDOC)
    assert result.returncode == 0, result.stdout + result.stderr


def test_commit_after_heredoc_reaches_commit_gate(package, consumer):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, HEREDOC + '\ngit commit -m fix')
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'MAGIC_NUMBER' in result.stderr
