"""Resolve simple git command targets without executing the supplied command.

Source: POSIX shell command lists; hooks/lib/git-command-cwd.py supplies the
existing git flag and cd resolution helpers. hooks/lib/shell_text.py first
removes here-document data and comments and turns newlines into separators
(POSIX Shell Command Language §2.7.4 Here-Document, §2.3, §2.9.3). A command
that still cannot be lexed is refused only when its text may hold a git
commit or push: anything else cannot reach the commit and push gates.
"""
import importlib.util
import os
import re
from pathlib import Path
import shlex


def _load(module, filename):
    spec = importlib.util.spec_from_file_location(module, Path(__file__).with_name(filename))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


git_cwd = _load('git_command_cwd', 'git-command-cwd.py')
shell_text = _load('shell_text', 'shell_text.py')
_GIT = re.compile(r'\bgit\s')
# Where origin/main refused, any word git left in the rewritten text refuses:
# origin/main's own predicate is \bgit\s on the raw text, and a word git
# (x=git, $x) can still run as a command once a verb is built at run time.
_GIT_WORD = re.compile(r'\bgit\b')
_VERB = re.compile(r'\b(?:commit|push)\b')
# source: one flat shlex pass is quadratic in a token's length (216 KB took
# 3.2 s, 108 KB 1.0 s on 2026-10-16); 128 KiB keeps both readings near 3 s.
MAX_COMMAND = 131072
_PUNCTUATION = ';&|(){}'
_OPERATORS = re.compile(r'&&|\|\||;;&|;;|;&|\|&|[;&|(){}]')
_TERMINATORS = {';;': ';', ';&': ';', ';;&': ';', '|&': '|'}


def _mentions_command(command, words):
    # Conservative candidate filter only; shlex below decides real tokens.
    return re.search(r'\b(?:' + words + r')\s', shell_text.unquoted(command))


def _tokens(command):
    """Lex text from shell_text.shell_lines. Every # left there is inside
    quotes, an expansion or a word, never a comment, so none is stripped.
    shlex returns a run of operator characters as one token (`};`, `;(`,
    `)&&`); each run is split into the operators the shell reads (§2.10.1),
    and the case terminators ;; ;& ;;& separate commands like ;."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.commenters = ''
    tokens = []
    for token in lexer:
        if not token or token.strip(_PUNCTUATION):
            tokens.append(token)
        else:
            tokens.extend(_TERMINATORS.get(op, op) for op in _OPERATORS.findall(token))
    return tokens


def _uninspectable(command, error):
    """Refuse a command that cannot be read only if it may commit or push."""
    if may_commit_or_push(command):
        raise ValueError(f'Cannot inspect shell quoting before git validation: {error}') from error
    return []


def may_commit_or_push(text):
    """True when text, quotes removed, may hold a git commit or push."""
    text = shell_text.unquoted(text)
    first = _GIT.search(text)
    # A verb after the first git: the same as git\s.*(commit|push), linear.
    return bool(first and _VERB.search(text, first.end()))


def _flat_targets(command, base):
    """The reading origin/main used: the raw command lexed as one flat line
    (shlex, # comments). None when it cannot lex the command, where
    origin/main refused it; a git selector origin/main refused (GIT_DIR=,
    --git-dir) raises the same ValueError here."""
    if not _mentions_command(command, 'git'):
        return []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    return _walk(tokens, base)


def git_commands(command, base):
    """Commit and push targets of command. Where origin/main's flat reading
    succeeds its targets are added. Where it refused (only commands whose
    text matches the word git followed by a blank), the command is refused whenever its rewritten
    text still holds the word git: this refuses only where origin/main did,
    and spares only commands whose every git is here-document data or a
    comment."""
    if len(command) > MAX_COMMAND:
        return _uninspectable(command, ValueError(f'command longer than {MAX_COMMAND} characters'))
    flat = _flat_targets(command, base)
    refused, flat = flat is None, flat or []
    try:
        rewritten = shell_text.shell_lines(command)
    except ValueError as error:
        if refused:
            raise ValueError(f'origin/main refused this command, and it cannot be read: {error}') from error
        return _uninspectable(command, error) or flat
    if len(rewritten) > MAX_COMMAND:
        return _uninspectable(command, ValueError(f'rewritten command longer than {MAX_COMMAND} characters'))
    if refused and _GIT_WORD.search(shell_text.unquoted(rewritten)):
        raise ValueError('Cannot inspect shell quoting before git validation: '
                         'origin/main refused this command and git is still in it')
    if not _mentions_command(rewritten, 'git'):
        return flat
    try:
        tokens = _tokens(rewritten)
    except ValueError as error:
        return _uninspectable(rewritten, error) or flat
    targets = _walk(tokens, base)
    return targets + [target for target in flat if target not in targets]


def _walk(tokens, base):
    """The commit and push targets of a token list split at separators."""
    current, segment, targets = os.path.abspath(base), [], []
    for token in [*tokens, ';']:
        if token not in git_cwd.SEPARATORS:
            segment.append(token)
            continue
        directory, verb = _git_command(segment, current)
        target = (directory, verb) if verb in {'commit', 'push'} else None
        if target and target not in targets:
            targets.append(target)
        if token in {'&&', ';'}:
            current = git_cwd._cd_target(segment, current) or current
        segment = []
    return targets


def git_directories(command, base):
    return list(dict.fromkeys(directory for directory, _verb in git_commands(command, base)))

def _direct_tokens(tokens):
    remaining = list(tokens)
    while remaining:
        token = remaining[0]
        if token in {'command', 'env', 'sudo'} or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', token):
            remaining.pop(0)
        else:
            break
    return remaining


def _git_command(tokens, base, *, validate=True):
    """Identify a direct git command and its first verb, never argument text."""
    direct = _direct_tokens(tokens)
    prefix = tokens[:len(tokens) - len(direct)]
    unsupported = any(re.match(r'^(?:GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE)=', token) for token in prefix)
    tokens = direct
    if not tokens or os.path.basename(tokens[0]) != 'git':
        return None, None
    current, index = base, 1
    valued = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'}
    while index < len(tokens):
        token = tokens[index]
        if token.split('=', 1)[0] in {'--git-dir', '--work-tree'}:
            unsupported = True
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
            if unsupported and validate and token in {'commit', 'push'}:
                raise ValueError('Explicit Git repository/index selectors are unsupported; use git -C')
            if unsupported:
                return None, token
            return current, token
    return None, None


def _shell_directories(command, base):
    try:
        command = shell_text.shell_lines(command)
    except ValueError:
        return []
    if not _mentions_command(command, 'git|cd'):
        return []
    try:
        tokens = _tokens(command)
    except ValueError:
        # Post-tool inspection retains the known event directory. An invalid
        # shell command supplies no reliable additional directory targets.
        return []
    current, segment, result = base, [], []
    for token in [*tokens, ';']:
        if token not in git_cwd.SEPARATORS:
            segment.append(token)
            continue
        target, _verb = _git_command(segment, current, validate=False)
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
