"""Regression for PNG cleanup crashing the definition gate before language dispatch.

Source: Transartica cleanup on 2026-09-27, PNG signature decoded as UTF-8.
The gate's documented scope is LANG_REGISTRY; source removals must still block.
"""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import deletion_gate_git as dgg

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
SOURCE = 'def emit(value):\n    return value + 1\n'


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Test')
    (tmp_path / 'image.png').write_bytes(PNG_SIGNATURE)
    (tmp_path / 'lib.py').write_text(SOURCE)
    (tmp_path / 'caller.py').write_text('from lib import emit\nprint(emit(3))\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'baseline')
    return tmp_path


@pytest.mark.parametrize('mode', [None, dgg.MODE_STAGED, dgg.MODE_WORKTREE])
@pytest.mark.parametrize('change', ['add', 'modify', 'delete', 'rename'])
def test_binary_changes_preserve_source_detection(repo: Path, mode, change: str):
    image = repo / 'image.png'
    if change == 'add':
        (repo / 'new.png').write_bytes(PNG_SIGNATURE)
        git(repo, 'add', '-N', 'new.png')  # Include the addition in an unstaged diff.
    elif change == 'modify':
        image.write_bytes(PNG_SIGNATURE + b'new')
    elif change == 'delete':
        image.unlink()
    else:
        image.rename(repo / 'renamed.png')
    (repo / 'lib.py').write_text('')
    base = git(repo, 'rev-parse', 'HEAD')
    if mode != dgg.MODE_WORKTREE:
        git(repo, 'add', '-A')
    if mode is None:
        git(repo, 'commit', '-qm', 'changed')
    with patch.object(dgg, 'post_content', wraps=dgg.post_content) as reader:
        removed, added = dgg.collect_definitions(str(repo), base, 'HEAD', mode)
    # Worktree reads previously replaced invalid bytes, hiding unnecessary binary I/O.
    assert all(call.args[2].endswith('.py') for call in reader.call_args_list)
    assert [(item.file, item.name) for item in removed] == [('lib.py', 'emit')]
    assert added == []


@pytest.mark.parametrize('reverse', [False, True])
def test_rename_across_language_boundary_keeps_the_source_side(repo: Path, reverse: bool):
    if reverse:
        (repo / 'note.txt').write_text(SOURCE)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'text source')
        git(repo, 'mv', 'note.txt', 'new.py')
    else:
        git(repo, 'mv', 'lib.py', 'note.txt')
    with patch.object(dgg, 'show_file', wraps=dgg.show_file) as before:
        with patch.object(dgg, 'post_content', wraps=dgg.post_content) as after:
            removed, added = dgg.collect_definitions(str(repo), 'HEAD', 'HEAD', dgg.MODE_STAGED)
    # Each supported side is read; the other side is outside the parser's contract.
    assert all(call.args[2].endswith('.py') for call in before.call_args_list + after.call_args_list)
    assert [item.name for item in (added if reverse else removed)] == ['emit']
    assert (removed if reverse else added) == []


@pytest.mark.parametrize('package', ['', 'plugins/zetetic-gates'])
@pytest.mark.parametrize('remove_source', [False, True])
def test_real_post_tool_hook_handles_binary_and_still_blocks_callers(repo: Path, package: str, remove_source: bool):
    (repo / 'image.png').unlink()
    if remove_source:
        (repo / 'lib.py').write_text('')
    hook = ROOT / package / 'hooks/post-tool-deletion-gate.py'
    result = subprocess.run([sys.executable, str(hook)], cwd=repo,
                            input='{"tool_name":"Bash"}', text=True, capture_output=True)
    assert result.returncode == (2 if remove_source else 0), result.stderr
    if remove_source:
        assert 'caller.py' in result.stderr
        assert 'BLOCK' in result.stderr
    assert 'UnicodeDecodeError' not in result.stderr
