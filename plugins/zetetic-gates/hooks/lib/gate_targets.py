"""Resolve simple git command targets without executing the supplied command.

Source: POSIX shell command lists; hooks/lib/git-command-cwd.py supplies the
existing git flag and cd resolution helpers.
"""
import importlib.util
import os
import re
from pathlib import Path
import shlex

spec = importlib.util.spec_from_file_location(
    'git_command_cwd', Path(__file__).with_name('git-command-cwd.py'))
git_cwd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(git_cwd)


def _mentions_command(command, words):
    # Conservative candidate filter only; shlex below decides real tokens.
    # Removing quote characters also catches shell concatenation: g'it'.
    candidate = command.replace("'", '').replace('"', '').replace('\\', '')
    return re.search(r'\b(?:' + words + r')\s', candidate)


def git_directories(command, base):
    if not _mentions_command(command, 'git'):
        return []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|(){}')
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as error:
        raise ValueError('Cannot inspect shell quoting before git validation') from error
    current, segment, targets = os.path.abspath(base), [], []
    for token in [*tokens, ';']:
        if token not in git_cwd.SEPARATORS:
            segment.append(token)
            continue
        directory, verb = _git_command(segment, current)
        target = directory if verb in {'commit', 'push'} else None
        if target and target not in targets:
            targets.append(target)
        if token in {'&&', ';'}:
            current = git_cwd._cd_target(segment, current) or current
        segment = []
    return targets

def _direct_tokens(tokens):
    remaining = list(tokens)
    while remaining:
        token = remaining[0]
        if token in {'command', 'env', 'sudo'} or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', token):
            remaining.pop(0)
        else:
            break
    return remaining


def _git_command(tokens, base):
    """Identify a direct git command and its first verb, never argument text."""
    if any(re.match(r'^(?:GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE)=', token) for token in tokens):
        raise ValueError('Explicit Git repository/index environment selectors are unsupported; use git -C')
    tokens = _direct_tokens(tokens)
    if not tokens or os.path.basename(tokens[0]) != 'git':
        return None, None
    current, index = base, 1
    valued = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'}
    while index < len(tokens):
        token = tokens[index]
        if token.split('=', 1)[0] in {'--git-dir', '--work-tree'}:
            raise ValueError('Explicit Git repository selectors are unsupported; use git -C')
        if token in valued and index + 1 < len(tokens):
            if token == '-C':
                current = os.path.abspath(os.path.join(current, tokens[index + 1]))
            index += 2
        elif token.startswith('-C') and len(token) > 2:
            current = os.path.abspath(os.path.join(current, token[2:]))
            index += 1
        elif token.startswith('-'):
            index += 1
        else:
            return current, token
    return None, None


def _shell_directories(command, base):
    if not _mentions_command(command, 'git|cd'):
        return []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|(){}')
    lexer.whitespace_split = True
    current, segment, result = base, [], list(git_directories(command, base))
    for token in [*list(lexer), ';']:
        if token not in git_cwd.SEPARATORS:
            segment.append(token)
            continue
        target, _verb = _git_command(segment, current)
        if target:
            result.append(target)
        if token in {'&&', ';'}:
            target = git_cwd._cd_target(segment, current)
            if target:
                current = target
                result.append(target)
        segment = []
    return result


def _patch_paths(command):
    prefixes = ('*** Add File: ', '*** Update File: ', '*** Delete File: ', '*** Move to: ')
    paths = []
    for line in command.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                paths.append(line[len(prefix):])
    return paths


def _file_directories(event, base):
    tin, name = event.get('tool_input') or {}, event.get('tool_name')
    paths = []
    if name in ('Edit', 'Write') and tin.get('file_path'):
        paths.append(tin['file_path'])
    if name == 'apply_patch':
        paths.extend(_patch_paths(tin.get('command', '')))
    return [str((Path(base) / path).resolve().parent) for path in paths]


def post_directories(event):
    """Find existing inspection directories without reading obsolete preimages."""
    tin = event.get('tool_input') or {}
    base = event.get('cwd') or os.getcwd()
    workdir = tin.get('workdir') or tin.get('cwd') or base
    base = str((Path(base) / workdir).resolve())
    directories = [base, *_file_directories(event, base)]
    if event.get('tool_name') in ('Bash', 'exec_command', 'shell_command'):
        command = tin.get('cmd', tin.get('command', ''))
        directories.extend(_shell_directories(command, base))
    result = []
    for directory in directories:
        path = Path(directory)
        while not path.is_dir() and path != path.parent:
            path = path.parent
        if str(path) not in result:
            result.append(str(path))
    return result
