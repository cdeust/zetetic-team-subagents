"""Resolve simple git command targets without executing the supplied command.

Source: POSIX shell command lists; hooks/lib/git-command-cwd.py supplies the
existing git flag and cd resolution helpers. hooks/lib/shell_text.py first
removes here-document data and comments and turns newlines into separators
(POSIX Shell Command Language §2.7.4 Here-Document, §2.3, §2.9.3). A command
origin/main refused is refused when the rewrite cannot read it, or when the
word git is in its rewritten text or in a span the rewrite dropped other
than a here-document body (see git_commands); anything else follows the
rewrite.
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


def mentions_git(text):
    """True when text, quotes removed, holds the word git."""
    return bool(_GIT_WORD.search(shell_text.unquoted(text)))


def _refuse_if_git(text, reason):
    """Raise when text holds the word git: the rule applied wherever
    origin/main refused, or may have refused, the command."""
    if mentions_git(text):
        raise ValueError(f'Cannot inspect shell quoting before git validation: {reason}')


# A command position (POSIX §2.9: the first word of a simple command, after a
# separator, an opening ( { `, a case pattern's ) or a reserved word); the
# words that run their arguments as a command (prefixes, with zsh's
# precommand modifiers noglob nocorrect -); the commands that build a command
# line at run time from their input (xargs, parallel).
_POSITION = re.compile(r'(?:^|[\n;&|({`!]|\b(?:then|do|else|elif|if|while|until|time)\b)[ \t]*', re.M)
# With case in the text, a ) may end a pattern: it is a position too (not
# otherwise, where $(date) $x would make $x a command name).
_CASE_POSITION = re.compile(r'(?:^|[\n;&|(){`!]|\b(?:then|do|else|elif|if|while|until|time)\b)[ \t]*', re.M)
_WORD = re.compile(r'[^\s;&|<>]*')
_ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\s]*\])?\+?=')
# A redirection before the command name (§2.7: [n]op word), skipped with its
# target; a target holding $, a backtick or ( (process substitution) counts
# as built, since it may run a command.
_REDIRECTION = re.compile(r'[0-9]*(?:<<<|<<-?|<>|>>|>&|<&|>\||<|>)[ \t]*([^\s;&|<>]*)[ \t]*')
_PREFIXES = {'command', 'env', 'sudo', 'doas', 'exec', 'builtin', 'nohup', 'nice', 'time',
             'timeout', 'stdbuf', 'setsid', 'eval', 'coproc', 'noglob', 'nocorrect', '-'}
_BUILDERS = {'xargs', 'parallel'}
_SIMPLE_COMMAND = re.compile(r'[^\n;&|]*')
_BRACE_EXPANSION = re.compile(r'\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}')
# Every built word or builder holds one of these: a text without them is spared in one pass.
_CANDIDATE = re.compile(r'[$`*?\[{]|\b(?:xargs|parallel)\b')


def _built_word(word):
    """True when the shell builds the word at run time: an expansion ($,
    backtick), pathname expansion (* ? [) or brace expansion."""
    return bool(re.search(r'[$`*?]', word) or ('[' in word and word not in {'[', '[['})
                or _BRACE_EXPANSION.search(word))


def _built_at(text, index):
    """(built, end): whether the command name at index is built at run time,
    and the end of the text examined. Assignment prefixes are skipped; after
    a prefix word every later word of the simple command counts."""
    while True:
        redirection = _REDIRECTION.match(text, index)
        if redirection and redirection.end() > index:
            if re.search(r'[$`(]', redirection.group(1)):
                return True, redirection.end()
            index = redirection.end()
            continue
        word = _WORD.match(text, index).group()
        if _ASSIGNMENT.match(word):
            index = _skip_blanks(text, index + len(word))
            continue
        if word in _PREFIXES:
            rest = _SIMPLE_COMMAND.match(text, index + len(word))
            words = [w for w in rest.group().split() if not w.startswith('-')]
            built = re.search(r'[$`]', rest.group()) or any(_built_word(w) or w in _BUILDERS for w in words)
            return bool(built), rest.end()
        return _built_word(word) or word in _BUILDERS, index + len(word)


def _skip_blanks(text, index):
    while index < len(text) and text[index] in ' \t':
        index += 1
    return index


def builds_command_name(text):
    """True when text, quotes removed, holds a command name the shell builds
    at run time (x=gi; ${x}t, $(printf gi)t, `echo gi`t, gi?, {gi,}t, or a
    word after eval, exec, env ... that holds $ or a backtick), or a command
    that builds its command line from input (xargs). Linear: each character
    is examined by one position match and at most one word or rest scan,
    because positions inside text already examined are skipped."""
    text = shell_text.unquoted(text)
    if not _CANDIDATE.search(text):
        return False
    examined = 0
    positions = _CASE_POSITION if re.search(r'\bcase\b', text) else _POSITION
    for position in positions.finditer(text):
        if position.end() < examined:
            continue
        built, examined = _built_at(text, position.end())
        if built:
            return True
    return False


def _refuse_if_built(text, reason):
    """Raise when text holds a command name built at run time: applied
    where origin/main refused, next to _refuse_if_git."""
    if builds_command_name(text):
        raise ValueError(f'Cannot inspect shell quoting before git validation: {reason}')


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
    succeeds its targets are added. Where it refused (the word git followed
    by a blank, and shlex cannot lex), the command is refused when the
    rewrite cannot read it, or when the word git is in the rewritten text or
    in any span the rewrite dropped other than here-document bodies, or when
    either holds a command name built at run time (builds_command_name).
    Every return path below applies that rule first (round8, round9
    analysis.txt):
    1 too long: refused when the word git is anywhere in the raw text. This
      holds wherever origin/main could refuse (its filter, git followed by a
      blank, implies the word git), so no built-name check is needed there.
    2, 3 unreadable: refused when origin/main refused; else when it may commit.
    4 origin/main refused and git, or a built command name, is in the live
      or dropped text: refused.
    5 rewritten too long, 6 no git left, 7 unlexable, 8 targets: origin/main
      refused only without either there, so these follow the rewrite."""
    if len(command) > MAX_COMMAND:
        _refuse_if_git(command, f'command longer than {MAX_COMMAND} characters')
        return []
    flat = _flat_targets(command, base)
    refused, flat = flat is None, flat or []
    try:
        rewritten, dropped = shell_text.read(command)
    except ValueError as error:
        if refused:
            raise ValueError(f'origin/main refused this command, and it cannot be read: {error}') from error
        return _uninspectable(command, error) or flat
    if refused:
        _refuse_if_git(rewritten + '\n' + dropped, 'origin/main refused this command and git is still in it')
        _refuse_if_built(rewritten + '\n' + dropped, 'origin/main refused this command and it builds a command name')
    if len(rewritten) > MAX_COMMAND:
        return _uninspectable(command, ValueError(f'rewritten command longer than {MAX_COMMAND} characters')) or flat
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
