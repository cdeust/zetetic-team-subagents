"""Actual checker contracts against index content rather than unstaged edits."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'hooks/lib/staged_checks.py'
BAD_FUNCTION = 'def f(' + ','.join('abcde') + '):\n    return a\n'


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q', '--template=')
    return tmp_path


def run(repo):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(ZETETIC_PROFILE='strict', CRAFTSMANSHIP_PROFILE='standard')
    return subprocess.run([sys.executable, str(RUNNER), str(ROOT), str(repo)],
                          env=env, text=True, capture_output=True)


@pytest.mark.parametrize('case', [
    ('source file.py', BAD_FUNCTION, 'value = 1\n', 'PARAM_COUNT'),
    ('README.md', 'We delve into this topic.\n', 'Project documentation.\n', 'BANNED_WORD'),
])
def test_index_violation_blocks_clean_worktree(repo, case):
    filename, bad, good, marker = case
    path = repo / filename
    path.write_text(bad)
    git(repo, 'add', '--', filename)
    path.write_text(good)
    before = git(repo, 'diff', '--cached').stdout
    result = run(repo)
    assert result.returncode == 1, result.stderr + result.stdout
    assert marker in result.stdout
    assert path.read_text() == good
    assert git(repo, 'diff', '--cached').stdout == before


@pytest.mark.parametrize('filename,bad,good', [
    ('source file.py', BAD_FUNCTION, 'value = 1\n'),
    ('README.md', 'We delve into this topic.\n', 'Project documentation.\n'),
])
def test_index_clean_ignores_worktree_violation(repo, filename, bad, good):
    path = repo / filename
    path.write_text(good)
    git(repo, 'add', '--', filename)
    path.write_text(bad)
    result = run(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    assert path.read_text() == bad


def test_indexed_policy_preserved_despite_unstaged_override(repo):
    (repo / '.craftsmanship.conf').write_text('PARAM_MAX=4\n')
    (repo / 'source.py').write_text(BAD_FUNCTION)
    git(repo, 'add', '.')
    (repo / '.craftsmanship.conf').write_text('SEV_PARAM_COUNT=off\n')
    result = run(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'PARAM_COUNT' in result.stdout


def test_symlink_never_dereferenced_and_binary_unchanged(repo, tmp_path):
    external = tmp_path / 'external'
    external.write_text(BAD_FUNCTION)
    (repo / 'link.py').symlink_to(external)
    (repo / 'image.png').write_bytes(b'\x00\xffbinary')
    git(repo, 'add', '--', 'link.py', 'image.png')
    result = run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'symlink' in result.stdout
    assert (repo / 'link.py').is_symlink()
    assert (repo / 'image.png').read_bytes() == b'\x00\xffbinary'


def test_config_symlink_refuses(repo):
    (repo / 'policy').write_text('SEV_PARAM_COUNT=off\n')
    (repo / '.craftsmanship.conf').symlink_to('policy')
    git(repo, 'add', '.')
    result = run(repo)
    assert result.returncode == 2
    assert 'config' in result.stderr


def test_empty_index(repo):
    assert run(repo).returncode == 0
