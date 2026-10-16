"""Post-tool repository targets do not require obsolete patch preimages."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'gate_targets', Path(__file__).resolve().parents[1] / 'hooks/lib/gate_targets.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def event(repo, tool, **fields):
    return {'cwd': str(repo), 'tool_name': tool, 'tool_input': fields}


def test_shell_workdir_overrides_session_directory(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    result = module.post_directories(event(a, 'exec_command', cmd='rm victim.py', workdir=str(b)))
    assert result == [str(b)]


def test_absolute_edit_targets_other_project(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    result = module.post_directories(event(a, 'Edit', file_path=str(b / 'removed' / 'file.py')))
    assert str(b) in result


def test_patch_headers_cover_deleted_moved_and_added_files(tmp_path):
    a, b, c = [tmp_path / name for name in ('a', 'b', 'c')]
    for directory in (a, b, c):
        directory.mkdir()
    patch = '\n'.join([
        '*** Begin Patch', f'*** Delete File: {b}/removed/file.py',
        '*** Update File: local.py', f'*** Move to: {c}/moved.py',
        '@@', '-before', '+after', f'*** Add File: {b}/new.py', '+new',
        '*** End Patch'])
    result = module.post_directories(event(a, 'apply_patch', command=patch))
    assert set(result) == {str(a), str(b), str(c)}


def test_shell_cd_and_git_directory_targets(tmp_path):
    a, b, c = [tmp_path / name for name in ('a', 'b', 'c')]
    for directory in (a, b, c):
        directory.mkdir()
    command = f'cd {b} && rm victim.py; git -C {c} rm old.py'
    assert set(module.post_directories(event(a, 'Bash', command=command))) == {str(a), str(b), str(c)}


def test_missing_workdir_uses_nearest_existing_parent(tmp_path):
    result = module.post_directories(event(tmp_path, 'shell_command', command='rmdir nested',
                                           workdir=str(tmp_path / 'removed')))
    assert result == [str(tmp_path)]


def test_unrelated_heredoc_does_not_require_shell_tokenization(tmp_path):
    command = "python3 - <<'PY'\n# an unmatched ' inside a Python comment\nprint(1)\nPY"
    assert module.git_directories(command, str(tmp_path)) == []
    assert module.post_directories(event(tmp_path, 'Bash', command=command)) == [str(tmp_path)]


@pytest.mark.parametrize('executable', ['"git"', "'git'", '"/usr/bin/git"', "g'it'", '"/usr/bin/g"it'])
def test_quoted_executable_is_inspected(tmp_path, executable):
    assert module.git_directories(executable + ' commit -m fix', str(tmp_path)) == [str(tmp_path)]


def test_quoted_cd_reaches_post_target(tmp_path):
    target = tmp_path / 'other'
    target.mkdir()
    command = f'"cd" {target} && rm victim.py'
    assert str(target) in module.post_directories(event(tmp_path, 'Bash', command=command))


def test_quoted_git_verb_is_inspected(tmp_path):
    assert module.git_directories('git "commit" -m fix', str(tmp_path)) == [str(tmp_path)]


@pytest.mark.parametrize('command', ['echo git commit', 'git log --grep commit', "printf 'git commit'"])
def test_git_arguments_are_not_commit_commands(tmp_path, command):
    assert module.git_directories(command, str(tmp_path)) == []


@pytest.mark.parametrize('command', [
    'git --git-dir /other/.git commit', 'git --work-tree=/other commit',
    'GIT_DIR=/other/.git git commit', 'env GIT_WORK_TREE=/other git push',
    'GIT_INDEX_FILE=/other/index git commit',
])
def test_explicit_repository_selectors_refuse(tmp_path, command):
    with pytest.raises(ValueError, match='unsupported'):
        module.git_directories(command, str(tmp_path))


@pytest.mark.parametrize('command', [
    'GIT_DIR=/x git log', 'git --git-dir=/x status',
    'GIT_INDEX_FILE=/x git add -A', 'env GIT_WORK_TREE=/x git diff',
    'GIT_DIR=/x echo hello', 'echo GIT_DIR=/x',
    'git commit -m GIT_DIR=/x',
])
def test_selectors_are_only_special_in_the_command_prefix(tmp_path, command):
    expected = [str(tmp_path)] if command.startswith('git commit') else []
    assert module.git_directories(command, str(tmp_path)) == expected


@pytest.mark.parametrize('command', ['cd /tmp && echo "x', 'git status && echo "x'])
def test_malformed_post_shell_retains_event_directory(tmp_path, command):
    assert module.post_directories(event(tmp_path, 'Bash', command=command)) == [str(tmp_path)]


def test_git_commands_preserve_both_verbs(tmp_path):
    assert module.git_commands('git push; git commit', str(tmp_path)) == [
        (str(tmp_path), 'push'), (str(tmp_path), 'commit')]


# POSIX Shell Command Language §2.7.4 (Here-Document): the lines after the
# operator's line, up to the delimiter line, are data. A quoted delimiter
# turns off every expansion in them, so not even a $(...) there runs.
@pytest.mark.parametrize('command', [
    "mkdir -p /tmp/x && cat > f <<'EOF2'\nthe git hook won't run\nEOF2",
    'cat > f <<"EOF"\nthe git hook won\'t run\nEOF',
    "cat > f <<\\EOF\nthe git hook won't run\nEOF",
    "cat > f <<E'O'F\nthe git hook won't run\nEOF",
    "cat > f <<-'EOF'\n\tthe git hook won't run\n\tEOF",
    "cat <<'A' > a; cat <<'B' > b\ngit won't\nA\nit is git\nB",
    "cat > f <<'EOF'\nwon't $(git commit -m x)\nEOF",
    "cat > f 2<<'EOF'\nthe git hook won't run\nEOF",
    "cat > f <<'EOF'\nthe git hook won't run",
    "cat > f <<'EOF'\nwon't\nEOF \ngit commit -m x",
])
def test_quoted_heredoc_body_is_data(tmp_path, command):
    assert module.git_commands(command, str(tmp_path)) == []


def test_post_inspection_reads_commands_around_a_heredoc(tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    command = f"cd {other} && cat > f <<'EOF'\nthe git hook won't run\nEOF"
    assert str(other) in module.post_directories(event(tmp_path, 'Bash', command=command))


def outcome(command, base):
    try:
        return module.git_commands(command, base)
    except ValueError:
        return 'refused'


def test_gate_refuses_only_when_a_commit_or_push_may_be_hidden(tmp_path):
    """A lex failure refuses only if a commit or push survives heredoc removal."""
    base = str(tmp_path)
    commit, push = [(base, 'commit')], [(base, 'push')]
    expected = {
        "mkdir -p x && cat > f <<'EOF'\nthe git hook won't run\nEOF": [],
        'mkdir -p x && git commit -m x': commit,
        'echo "unterminated && git commit -m x': 'refused',
        "echo \"unterminated && g'it' pu'sh": 'refused',
        'echo "see the git log': [],
        "cat <<EOF\nthe git hook won't run\nEOF": [],
        'cat <<EOF\n$(git commit -m x)\nEOF': commit,
        "cat <<EOF\nwon't $(git commit -m x)\nEOF": 'refused',
        "cat > f <<'EOF'\nwon't\nEOF\ngit commit -m x": commit,
        "cat > f <<'EOF' && git commit -m x\nwon't\nEOF": commit,
        "cat > f <<-'EOF'\n\twon't\n\tEOF\n(git push)": push,
        "git commit -m \"$(cat <<'EOF'\nmsg won't\nEOF\n)\"": commit,
        "echo '<<EOF' && echo \"\nEOF\" && git push": push,
        "git commit <<< \"it's fine\"": commit,
        'echo $((1<<2))\n(git push)': push,
        "echo hi # it's git\ngit push": push,
        'mkdir x\ngit commit -m x': commit,
        'gi\\\nt commit -m x': commit,
    }
    assert {command: outcome(command, base) for command in expected} == expected
