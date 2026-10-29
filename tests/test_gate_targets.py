"""Post-tool repository targets do not require obsolete patch preimages."""
import importlib.util
import os
from pathlib import Path
import re
import shlex

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
    """A lex failure refuses only if a commit or push survives heredoc removal.
    Where origin/main refused (an unbalanced apostrophe in a body), a commit
    or push anywhere in the rewritten text is refused too (owner decision)."""
    base = str(tmp_path)
    commit, push = [(base, 'commit')], [(base, 'push')]
    expected = {
        "mkdir -p x && cat > f <<'EOF'\nthe git hook won't run\nEOF": [],
        'mkdir -p x && git commit -m x': commit,
        'echo "unterminated && git commit -m x': 'refused',
        "echo \"unterminated && g'it' pu'sh": 'refused',
        'echo "see the git log': 'refused',  # origin/main refused it; so does the gate
        "cat <<EOF\nthe git hook won't run\nEOF": [],
        'cat <<EOF\n$(git commit -m x)\nEOF': commit,
        # origin/main refused it (an unbalanced quote); so does the gate.
        "cat <<EOF\nwon't $(git commit -m x)\nEOF": 'refused',
        "cat > f <<'EOF'\nwon't\nEOF\ngit commit -m x": 'refused',
        "cat > f <<'EOF' && git commit -m x\nwon't\nEOF": 'refused',
        "cat > f <<-'EOF'\n\twon't\n\tEOF\n(git push)": 'refused',
        "git commit -m \"$(cat <<'EOF'\nmsg won't\nEOF\n)\"": commit,
        "echo '<<EOF' && echo \"\nEOF\" && git push": push,
        "git commit <<< \"it's fine\"": commit,
        'echo $((1<<2))\n(git push)': push,
        "echo hi # it's git\ngit push": push,
        'mkdir x\ngit commit -m x': commit,
        'gi\\\nt commit -m x': commit,
    }
    assert {command: outcome(command, base) for command in expected} == expected


# PR #174 review: the rewrite must never hide a commit or push the shell runs.
# POSIX §2.6.2: << inside ${...} is pattern or word text, not a here-document
# operator; bash $[...] and arithmetic ((...)) read << as a shift. §2.7.4: an
# unquoted here-document body is data except its expansions, and the commands
# in a $(...) there keep their comments (§2.3 rule 9). bash parse.y
# parse_arith_cmd: (( whose inner ) is not directly followed by ) opens two
# subshells, not arithmetic.
@pytest.mark.parametrize('command, verb', [
    ('echo ${x//<<} &&\ngit commit -m hi', 'commit'),
    ('x=a; echo ${x/<</y} &&\ngit push', 'push'),
    ('echo $[1<<2] &&\ngit commit -m hi', 'commit'),
    ('cat <<EOF\n$( # note\ngit commit -m x\n)\nEOF', 'commit'),
    ('((echo a) # c\ngit commit -m x)', 'commit'),
    ('echo ${x#<<} &&\ngit commit -m x', 'commit'),
    ('echo ${x:-<<} &&\ngit commit -m x', 'commit'),
    ('echo ${x:-${y//<<}} &&\ngit commit -m x', 'commit'),
    ("echo ${x:-'}'<<} &&\ngit commit -m x", 'commit'),
    ('echo ${x:-\\}<<} &&\ngit commit -m x', 'commit'),
    ('((git commit -m x) )', 'commit'),
    ('echo $[1+$[2<<1]] &&\ngit commit -m x', 'commit'),
    ('echo ${x:-$( # c\ngit commit -m x\n)}', 'commit'),
    ('echo $(( $( # c\ngit commit -m x\n) ))', 'commit'),
    ('$((echo a) # c\ngit commit -m x)', 'commit'),
    ('((1<<2)) &&\ngit commit -m x', 'commit'),
    ('cat <<EOF\n${x:-$( # c\ngit commit -m x\n)}\nEOF', 'commit'),
    ('cat <<EOF\n$(( $( # c\ngit commit -m x\n) ))\nEOF', 'commit'),
    ('cat <<EOF\n$(case x in a) git commit -m x;; esac)\nEOF', 'commit'),
    ('cat <<EOF\n`git commit -m x`\nEOF', 'commit'),
])
def test_rewrite_keeps_every_commit_the_shell_runs(tmp_path, command, verb):
    assert outcome(command, str(tmp_path)) == [(str(tmp_path), verb)]


@pytest.mark.parametrize('command', [
    "cat > hook.sh <<EOF\n#!/bin/sh\n# don't git commit from here\necho $(date)\nEOF",
    "cat > run.sh <<EOF\nstamp=$(date +%s)\n# we can't git\x20push yet\nEOF\nchmod +x run.sh",
    "cat > f <<EOF\nit's $(date) and we don't git commit\nEOF",
    "cat > f <<EOF\n${HOME}: don't git commit, it's `date`\nEOF",
    "cat > f <<EOF\n$((1<<2)) commits; don't git commit\nEOF",
])
def test_unquoted_heredoc_prose_is_data(tmp_path, command):
    assert outcome(command, str(tmp_path)) == []


def test_nested_expansions_are_rewritten_once(monkeypatch):
    """An expansion that is not arithmetic is read again as commands; without
    reuse each nesting level doubles the work (2**14 here)."""
    calls = []
    span = module.shell_text._span
    monkeypatch.setattr(module.shell_text, '_span', lambda *a: calls.append(a) or span(*a))
    module.shell_text.shell_lines('$((' * 14 + 'a')
    assert len(calls) < 2000


@pytest.mark.parametrize('tail, expected', [
    ('git commit -m x', 'refused'), ('echo hi', [])])
def test_nesting_beyond_the_recursion_limit_is_refused_only_for_git(tmp_path, tail, expected):
    assert outcome('$(( ' * 2000 + tail, str(tmp_path)) == expected


# PR #174 review, round 2: further ways the rewrite hid a commit that bash or
# zsh runs (raw evidence: tasks/evidence/pr-174-review/round2/).
# §2.9.4.3: case opens wherever a command may start, also after then, do, !
# and {, so its pattern's ) does not end the $(...) holding it. §2.3 rule 9:
# # begins a comment only at the start of a word, not right after $(...),
# $((...)), <(...) or a removed backslash-newline. §2.7.4: the delimiter is
# the word after quote removal and line joining ($'EOF', $"EOF", EO\<newline>F
# all end at EOF), and a $(...) reads its own here-documents.
@pytest.mark.parametrize('command', [
    'cat <<EOF\n$(if true; then case x in a) echo;; esac; fi; git commit -m x)\nEOF',
    'cat <<EOF\n$(! case x in a) echo;; esac; git commit -m x)\nEOF',
    'cat <<EOF\n$(for i in 1; do case x in a) echo;; esac; done; git commit -m x)\nEOF',
    'cat <<EOF\n$({ case x in a) echo;; esac; }; git commit -m x)\nEOF',
    'echo $(echo a)#b; git commit -m x',
    'echo $((1))#b; git commit -m x',
    'cat <(echo a)#b; git commit -m x',
    'echo a\\\n#b; git commit -m x',
    "cat <<$'EOF'\nbody\nEOF\ngit commit -m x",
    'cat <<$"EOF"\nbody\nEOF\ngit commit -m x',
    'cat <<EO\\\nF\nbody\nEOF\ngit commit -m x',
    'cat <<\\\nEOF\nbody\nEOF\ngit commit -m x',
    "cat <<'E\\F'\nbody\nE\\F\ngit commit -m x",
    'cat <<A; echo $(cat <<B\nb\nB\n)\na\nA\ngit commit -m x',
    'cat <<EOF\n"$(git commit -m x)"\nEOF',
    "cat <<EOF\n'$(git commit -m x)'\nEOF",
])
def test_rewrite_keeps_commits_hidden_by_misread_syntax(tmp_path, command):
    assert outcome(command, str(tmp_path)) == [(str(tmp_path), 'commit')]


# shlex returns a run of operator characters as one token; the shell reads
# }; as } then ; (§2.10.1), and ;; ends a case item like ; ends a command.
@pytest.mark.parametrize('command', [
    '{ echo a; }; git commit -m x',
    '(echo a);git commit -m x',
    'x;(git commit -m x)',
    'true&&(git commit -m x)',
    'case x in a) echo;;esac;git commit -m x',
    "git -C '' commit -m x",
])
def test_operator_runs_separate_commands(tmp_path, command):
    assert outcome(command, str(tmp_path)) == [(str(tmp_path), 'commit')]


# A here-document whose delimiter line never comes swallows the rest of the
# command. The rewrite cannot always know what the shell takes for the
# operator (bash reads a[1<<2]= as a subscript, zsh as a here-document), so a
# body that runs to the end is refused when the command may commit or push.
@pytest.mark.parametrize('command, expected', [
    ('a[1<<2]=x &&\ngit commit -m x', 'refused'),
    ('a=([1<<2]=x) &&\ngit commit -m x', 'refused'),
    ("cat <<EOF\nwe don't git commit here", 'refused'),
    ("cat > f <<'EOF'\nwon't\nEOF \ngit commit -m x", 'refused'),
    ("cat <<EOF\nit's fine", []),
    # bash and zsh read the git line as body, but the flat reading gates it.
    ('let x=1<<2 &&\ngit commit -m x\n2', 'commit'),
])
def test_unterminated_heredoc_is_refused_only_for_git(tmp_path, command, expected):
    if expected == 'commit':
        expected = [(str(tmp_path), 'commit')]
    assert outcome(command, str(tmp_path)) == expected


# PR #174 review, round 3: bash (and mostly zsh) runs the git line in each of
# these; the round-2 rewrite read it as here-document data. A quote, $(...),
# ${...} or `...` is one unit: a " inside "$(...)" does not close the outer
# string (§2.2.3, §2.6.3); \' does not close $'...' (bash); the delimiter word
# <<$(echo) holds the whole $(echo) (§2.7.4). bash reads << in a[...]= as
# arithmetic and zsh as a here-document, so that is refused for git.
@pytest.mark.parametrize('command', [
    "echo $'\\' <<X ' \\';\ngit commit -m x\nX",                          # C1
    'echo "$(echo "<<X")";\ngit commit -m x\nX)',                         # C2
    'echo "$(echo "<<EOF ")";\ngit commit -m x\nEOF',                     # C4
    'v="$(printf "%s" "<<EOF ")" && echo "$v";\ngit push origin main\nEOF',  # C5
    'echo "$(echo "<<EOF ")";\ngit commit -m x\necho $\'it\\\'s\'\nEOF',   # C6
    'cat <<$(echo);\n$(echo)\ngit commit -m x\n$',                        # B1
    'cat <<${a;b};\n${a;b}\ngit commit -m x\n${a',                        # B2
    'a[1<<2]=x;\ngit commit -m hi;\n2]=x',                                # A1
    'a[1<<2]=x &&\ngit commit -m x\n2]=x',                                # A3
    'echo "$(echo "$(echo "<<EOF")")";\ngit commit -m x\nEOF',
    'cat <<$((1;2));\n$((1;2))\ngit commit -m x\n$',
    "cat <<$'E\\x4fF'\nEOF\ngit commit -m x\nE\\x4fF",
    "echo $'x\\'y' ; git commit -m x ; echo \\'",
    'echo `echo a #` ; git commit -m x',
    'echo $(echo case)#x; git commit -m y',
])
def test_units_keep_their_extent_so_no_git_line_is_hidden(tmp_path, command):
    result = outcome(command, str(tmp_path))
    assert result == 'refused' or {verb for _d, verb in result} & {'commit', 'push'}


# case is reserved only as the first word of a command (§2.4, §2.9.1). Missed
# there, its pattern's ) closes the $(...) early; counted as an argument, the
# $(...) stays open. Both hid the git command; bash runs it in each.
@pytest.mark.parametrize('command', [
    'cat <<EOF\n$(time -p case x in a) echo;; esac; git commit -m x)\nEOF',
    'cat <<EOF\n$(coproc case x in a) echo;; esac; git commit -m x)\nEOF',
    'cat <<EOF\n$(f() { case x in a) echo;; esac; }; git commit -m x)\nEOF',
    'cat <<EOF\n$(>/dev/null case x in a) echo;; esac; git commit -m x)\nEOF',
    'cat <<EOF\n$(2>/dev/null case x in a) echo;; esac; git commit -m x)\nEOF',
    'x=$(time -p case x in a) echo;; esac)#y; git commit -m x',
    'echo $(echo then case)#x; git commit -m y',
    'echo $(echo >&2 case)#x; git commit -m y',
    'echo $(echo >|/dev/null case)#x; git commit -m y',
])
def test_case_counts_only_in_command_position(tmp_path, command):
    result = outcome(command, str(tmp_path))
    assert result == 'refused' or {verb for _d, verb in result} & {'commit', 'push'}


@pytest.mark.parametrize('command', [
    'n="$(grep -c "<<EOF" /dev/null)"\ngit commit -m x',                  # U8
    "$'git' commit -m x",
])
def test_quoted_units_do_not_refuse_a_plain_commit(tmp_path, command):
    assert outcome(command, str(tmp_path)) == [(str(tmp_path), 'commit')]


# PR #174 review, round 4: bash (or zsh) runs git in each of these and the
# round-3 head returned []. case after &> or an assignment, esac right after
# in or split by a backslash-newline, a bare { inside ${...}, and a
# here-document still pending where a $(...) ends (bash reads the next lines
# as its body, zsh does not).
ROUND4 = [
    '((1))#a <<EOF\ngit commit -m x\nEOF',  # comment in bash and zsh; << kept would hide the commit
    'echo "$(echo &>/dev/null case)"; git commit -m x; echo ";esac)"',      # P1
    'echo "$(a=1 case)"; git commit -m x; echo ";esac)"',                   # P3
    'echo "$(case x in x) echo;; es\\\nac)"; git commit -m x; echo ";esac)"',  # P5
    'v="$(echo &>/dev/null case)"; git push; echo ";esac)"',                # P7
    'echo "$(case x in esac)"; git commit -m x; echo ";esac)"',             # P8
    'echo "${x:-{}"; git commit -m x; echo "}"',                            # R1
    'y="${x#{}"; git push; echo "}"',                                       # R5
    'echo "${x:-\'}"; git commit -m x; echo "\'}"',                        # R2
    'x="$(cat <<EOF)"\ncat <<Y\nEOF\ntrue; git commit -m x\nY',             # S1
    'x=$(cat <<EOF)\ncat <<Y\nEOF\nls && git push origin main\nY',          # S3
    'echo $(cat <<EOF)\ngit commit -m x\nEOF',
]


@pytest.mark.parametrize('command', ROUND4)
def test_round4_inputs_are_gated_or_refused(tmp_path, command):
    result = outcome(command, str(tmp_path))
    assert result == 'refused' or {verb for _d, verb in result} & {'commit', 'push'}


def test_a_shift_inside_arithmetic_in_a_subscript_is_gated(tmp_path):
    assert outcome('a[$((1<<2))]=x; git commit -m x', str(tmp_path)) == [(str(tmp_path), 'commit')]


def flat_reading(command, base):
    """origin/main 811818b's git_commands, verbatim in behaviour: the raw
    command lexed as one flat line, a lex failure being a refusal."""
    if not re.search(r'\bgit\s', command.replace("'", '').replace('"', '').replace('\\', '')):
        return []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|(){}')
    lexer.whitespace_split = True
    tokens = list(lexer)
    current, segment, targets = os.path.abspath(base), [], []
    for token in [*tokens, ';']:
        if token not in module.git_cwd.SEPARATORS:
            segment.append(token)
            continue
        directory, verb = module._git_command(segment, current)
        target = (directory, verb) if verb in {'commit', 'push'} else None
        if target and target not in targets:
            targets.append(target)
        if token in {'&&', ';'}:
            current = module.git_cwd._cd_target(segment, current) or current
        segment = []
    return targets


def corpus():
    """Every command string this module tests, plus ROUND4."""
    marks = [mark for value in list(globals().values())
             for mark in getattr(value, 'pytestmark', []) if mark.name == 'parametrize']
    rows = [row for mark in marks for row in mark.args[1]]
    items = [item for row in rows for item in (row if isinstance(row, tuple) else (row,))]
    return sorted(set(ROUND4) | {item for item in items if isinstance(item, str) and 'git' in item})


def test_targets_are_a_superset_of_the_flat_reading(tmp_path):
    """Wherever origin/main's flat reading succeeds, git_commands returns
    every target it found, or refuses the command."""
    base, checked = str(tmp_path), 0
    for command in corpus():
        try:
            flat = flat_reading(command, base)
        except ValueError:
            continue
        result = outcome(command, base)
        assert result == 'refused' or set(flat) <= set(result), command
        checked += 1
    assert checked >= 90  # source: 98 commands of this module lex flat on 2026-10-16


# PR #174 review, round 5. ZSH_SPLITS: zsh runs git where the rewrite read
# bash's grammar (an unquoted ${x:-{} that zsh ends at a later brace; zsh's
# case WORD { ... }). STILL_OPEN: forms the rewrite does not resolve, which
# origin/main also misses. WRAPPERS add a harmless apostrophe that
# origin/main's shlex cannot lex: there origin/main refused, so the rewrite
# alone decides, and it must gate or refuse.
ZSH_SPLITS = [
    'echo ${x:-{} <<EOF }\ngit commit -m x\nEOF',                               # Z1
    'echo ${x:-{} <<EOF }\ngit push\nEOF',                                      # Z2
    'y=${x#{} <<EOF }\ngit commit -m x\nEOF',                                   # Z3
    'echo "$(case x { x) echo ;; })"; git commit -m x; echo ";esac)"',          # Z7
]
STILL_OPEN = [
    'echo `git commit -m x`', 'if true; then git commit -m x; fi', 'nohup git push',
    'echo "$(git commit -m x)"', 'time -p git commit -m x', 'coproc git commit -m x',
]
WRAPPERS = {
    'pre': lambda command: ": <<'Q'\nit's\nQ\n" + command,
    'suf': lambda command: command + "\n: <<'Q'\nit's\nQ",
    'ansi': lambda command: "echo $'\\''\n" + command,
}


def gated_or_refused(result):
    return result == 'refused' or bool({verb for _d, verb in result} & {'commit', 'push'})


@pytest.mark.parametrize('command', ZSH_SPLITS)
def test_bash_and_zsh_disagreements_are_gated_or_refused(tmp_path, command):
    assert gated_or_refused(outcome(command, str(tmp_path)))


@pytest.mark.parametrize('wrap', sorted(WRAPPERS))
@pytest.mark.parametrize('command', ROUND4 + ZSH_SPLITS + STILL_OPEN)
def test_where_origin_main_refused_the_rewrite_gates_or_refuses(tmp_path, wrap, command):
    assert gated_or_refused(outcome(WRAPPERS[wrap](command), str(tmp_path)))


@pytest.mark.parametrize('command', ROUND4 + ZSH_SPLITS)
def test_the_rewrite_alone_gates_or_refuses(tmp_path, monkeypatch, command):
    monkeypatch.setattr(module, '_flat_targets', lambda _command, _base: [])
    assert gated_or_refused(outcome(command, str(tmp_path)))


@pytest.mark.parametrize('command', [
    "cat > f <<'EOF'\nthe git hook won't run\nEOF",
    "cat > hook.sh <<EOF\n#!/bin/sh\n# don't git commit from here\necho $(date)\nEOF",
    'echo "${JSON:-{}}" && echo done',
])
def test_a_flat_refusal_is_not_kept_without_a_commit_in_the_rewrite(tmp_path, command):
    assert outcome(command, str(tmp_path)) == []


@pytest.mark.parametrize('command', [
    ' '.join(['a['] * 4000) + '\ngit commit -m x',
    ' '.join(['(('] * 3000) + '; git commit -m x',
    'echo ' + '${x:-{} ' * 4000 + '; git commit -m x',
    'git commit -m x; ' + ' ; '.join(['esac'] * 20000),
    'git commit -m "' + 'x' * 140000 + '"',  # source: above MAX_COMMAND, 131072
])
def test_large_inputs_are_gated_or_refused(tmp_path, command):
    assert gated_or_refused(outcome(command, str(tmp_path)))


def test_large_input_without_git_is_not_refused(tmp_path):
    assert outcome('echo "' + 'x' * 140000 + '"', str(tmp_path)) == []


# PR #174 review, round 6. Under an apostrophe origin/main cannot lex, a
# decoy commit in another repository must not waive the refusal for a commit
# the rewrite cannot resolve (X1-X6); the rewrite must not drop text the
# shell runs (B1, B2: a backslash-newline joins body lines before the
# delimiter match; H3: zsh's a(#b) is one word; Y1: a heredoc word ${...}
# that zsh ends later). Each must be refused or gated.
DECOYS = [
    'git -C /tmp/clean commit -m y; if true; then git commit -m x; fi',     # X1
    'git -C /tmp/clean commit -m y; echo "$(git commit -m x)"',             # X2
    'git -C /tmp/clean commit -m y; echo `git commit -m x`',                # X3
    'git -C /tmp/clean commit -m y; nohup git push',                        # X4
    'git -C /tmp/clean commit -m y; bash -c "git commit -m x"',             # X5
    'git -C /tmp/clean commit -m "$(git commit -m x)"',                     # X6
]
REMOVALS = [
    'cat <<EOF\nhello\nEO\\\nF\ngit commit -m x\nEOF',                      # B1
    'cat <<EOF\nEOF\\\n\ngit commit -m x\nEOF',                             # B2
    'x=a(#b); git commit -m x',                                             # H3
    'echo a(|#b)(N); git commit -m x',                                      # H4
    'cat <<${x:-{} a}\n${x:-{} a}\ngit commit -m x\n${x:-{}\n}',            # Y1
]


@pytest.mark.parametrize('wrap', sorted(WRAPPERS))
@pytest.mark.parametrize('command', DECOYS)
def test_a_decoy_target_does_not_waive_the_refusal(tmp_path, wrap, command):
    assert outcome(WRAPPERS[wrap](command), str(tmp_path)) == 'refused'


@pytest.mark.parametrize('wrap', ['', *sorted(WRAPPERS)])
@pytest.mark.parametrize('command', REMOVALS)
def test_text_the_shell_runs_is_not_removed(tmp_path, wrap, command):
    command = WRAPPERS[wrap](command) if wrap else command
    result = outcome(command, str(tmp_path))
    assert result == 'refused' or (str(tmp_path), 'commit') in result


def test_a_quoted_delimiter_body_is_not_joined(tmp_path):
    command = "cat <<'EOF'\nhello\nEO\\\nF\ngit commit -m x\nEOF"
    assert outcome(command, str(tmp_path)) == []


@pytest.mark.parametrize('command', [
    '"$(' * 14 + 'echo ' + '\\' * 200 + ')"' * 14 + '; git commit -m x',
    '"${x:-' * 14 + '\\\\' * 100 + '}"' * 14 + '; git commit -m x',
    '"$(' * 40 + 'echo "a"' + ')"' * 40 + '; git commit -m x',
])
def test_nested_quoted_units_do_not_blow_up(tmp_path, command):
    """Each level used to re-escape the level inside it, about 4x per level."""
    assert gated_or_refused(outcome(command, str(tmp_path)))
    assert len(module.shell_text.shell_lines(command)) < 10 * len(command)


# Size bound of the rewrite (round 6). Per input character the rewrite emits
# at most: 3 for a newline (' ;\n'), 2 for a ( ('( '), 2 for a quote or
# backslash escaped inside $'...' or `...`, else 1; a "..." nested unit is
# copied without quotes, so nesting adds nothing. Hence len(rewritten) <= 4n.
# shlex then reads at most len(rewritten) characters; both are capped by
# MAX_COMMAND, past which a commit or push is refused.
BOUND_SHAPES = [
    '\n' * 5000 + 'git commit -m x',
    '(' * 3000 + 'git commit -m x' + ')' * 3000,
    "echo $'" + "\\'" * 3000 + "'; git commit -m x",
    'echo `' + '"\\' * 3000 + '`; git commit -m x',
    '"$(' * 14 + 'echo ' + '\\' * 200 + ')"' * 14 + '; git commit -m x',
    '"${x:-' * 14 + '\\\\' * 100 + '}"' * 14 + '; git commit -m x',
    'cat <<EOF\n' + '$(echo "a")\n' * 2000 + 'EOF\ngit commit -m x',
]


@pytest.mark.parametrize('command', BOUND_SHAPES + corpus())
def test_rewritten_text_is_at_most_four_times_the_input(command):
    try:
        rewritten = module.shell_text.shell_lines(command)
    except ValueError:
        return
    assert len(rewritten) <= 4 * len(command) + 4


# PR #174 review, round 7. P*: zsh reads a #-group after ( or ) as one word
# and runs the git command after it; bash rejects these lines. I1, I4, A3:
# the commit verb is built at run time; origin/main refused these (they
# mention git and hold an apostrophe it cannot lex), so the gate refuses
# whenever the word git is left in the rewritten text.
PAREN_HASH = [
    'cat =(echo a)#x; git commit -m x',                                     # P1
    '[[ a == (a|b)#x ]]; git commit -m x',                                  # P2
    'case a in (a)#x) echo IN;; esac; git commit -m x',                     # P3
    'cat =(echo a)#x; git push',                                            # P5
    'case b in a|(b)#x) echo IN;; esac; git commit -m x',                   # P10
    '[[ a != (b)#x ]] && git commit -m x',                                  # P11
    'diff =(echo a)#x =(echo a) ; git push',                                # P12
]
BUILT_VERBS = [
    'git status; x=git; y=comm; $x ${y}it -m m',                            # I1
    'git status; $(printf gi)t $(printf com)mit -m m',                      # I4
    'y=comm; git -c alias.c=${y}it c -m x',                                 # A3
]


@pytest.mark.parametrize('wrap', ['', *sorted(WRAPPERS)])
@pytest.mark.parametrize('command', PAREN_HASH)
def test_a_hash_after_a_paren_hides_no_command(tmp_path, wrap, command):
    command = WRAPPERS[wrap](command) if wrap else command
    assert gated_or_refused(outcome(command, str(tmp_path)))


@pytest.mark.parametrize('wrap', sorted(WRAPPERS))
@pytest.mark.parametrize('command', BUILT_VERBS)
def test_where_origin_main_refused_a_git_word_refuses(tmp_path, wrap, command):
    assert outcome(WRAPPERS[wrap](command), str(tmp_path)) == 'refused'


@pytest.mark.parametrize('command, expected', [
    # I2: the only git followed by a blank is data, yet x=git runs it.
    (": <<'Q'\nit's git\nQ\nx=git; y=comm; $x ${y}it -m m", 'refused'),
    # The motivating prose: git only in data, no word git left.
    ("mkdir -p x && cat > f <<'EOF'\nthe git hook won't run\nEOF", []),
    # origin/main refused these; nothing can be read past the open quote.
    ("cat > f <<'EOF'\nthe git hook won't run", 'refused'),
    # Cost, as on origin/main: the word git is live, though no commit.
    ("cat <<'EOF'\ndon't\nEOF\ngit status", 'refused'),
])
def test_refusal_follows_origin_main_where_it_refused(tmp_path, command, expected):
    assert outcome(command, str(tmp_path)) == expected


def test_esac_look_back_reads_each_character_at_most_twice(monkeypatch):
    """Each esac reads back only to the previous word; before round 7 a run
    of more than 256 blanks made it re-read the whole text."""
    command = 'git commit -m x; ' + (' ' * 300 + 'esac ;') * 400
    scanned, word = [], module.shell_text._previous_word
    monkeypatch.setattr(module.shell_text, '_previous_word',
                        lambda text, index: scanned.append(word(text, index)[2]) or word(text, index))
    module.shell_text.shell_lines(command)
    assert len(scanned) == 400
    assert sum(scanned) <= 2 * len(command)


# PR #174 review, round 8. Where origin/main refused, the word git is looked
# for in the rewritten text and in every span the rewrite dropped except
# here-document bodies (comments, here-document operators and delimiter
# words), so no comment misreading in either shell can hide a git: zsh reads
# <->#x, <1-9>#x, (b|#x) and (b| #x) as words (S10-S21p); bash rejects them.
DROPPED_SPANS = [
    '[[ 5 == <->#x ]]; git commit -m x',                                    # S10
    'case 5 in <1-9>#x) echo IN;; esac; git commit -m x',                   # S11
    '[[ a == (b|#x) ]]; git commit -m x',                                   # S12
    'case a in (b|#x) echo IN;; esac; git commit -m x',                     # S13
    'ls <->#x 2>/dev/null; git commit -m x',                                # S16
    '[[ a == (b| #x) ]]; git commit -m x',                                  # S17
    '[[ a == (<->|#x) ]]; git commit -m x',                                 # S19
    'x=<->#x; git commit -m x',                                             # S21
    'x=<->#x; git push',                                                    # S21p
    "cat <<git\n$(x=gi; ${x}t commit -m m)\ngit",                            # S22
]
# The size caps return before the rewrite: verb built at run time (Z1, Z2).
SIZE_CAPS = [
    'git status; ' + '\n' * 45000 + 'x=git; y=comm; $x ${y}it -m m',       # Z1
    'git status; : ' + 'a ' * 66000 + '\nx=git; y=comm; $x ${y}it -m m',   # Z2
]


@pytest.mark.parametrize('wrap', sorted(WRAPPERS))
@pytest.mark.parametrize('command', DROPPED_SPANS + SIZE_CAPS)
def test_where_origin_main_refused_no_dropped_span_hides_git(tmp_path, wrap, command):
    assert outcome(WRAPPERS[wrap](command), str(tmp_path)) == 'refused'


def test_a_comment_before_a_heredoc_operator_keeps_the_commit_live(tmp_path):
    """Comments are tested, not kept: kept, '<<EOF' would make the commit data."""
    assert outcome('echo a # <<EOF\ngit commit -m x\nEOF', str(tmp_path)) == [(str(tmp_path), 'commit')]


def test_dropped_spans_are_comments_and_heredoc_operators_only():
    rewritten, dropped = module.shell_text.read("cat <<'E' # note\nbody git\nE\necho a # c git")
    assert dropped.split('\n') == ["<<'E'", '# note', '# c git']
    assert 'body' not in rewritten + dropped


# Every return path of git_commands (round8/analysis.txt): the rule "where
# origin/main refused and the word git is there, refuse" holds on each.
W = ": <<'Q'\nit's\nQ\n"
BUILT = 'x=git; y=comm; $x ${y}it -m m'


@pytest.mark.parametrize('path, command, expected', [
    ('1 input over cap, git', 'git status; : ' + 'a ' * 66000 + '\n' + BUILT, 'refused'),
    ('1 input over cap, no git', 'echo ' + 'a ' * 66000, []),
    ('2 unreadable, main refused', W + 'cat <<EOF\ngit status', 'refused'),
    ('3 unreadable, main lexed, commit', 'cat <<EOF\ngit commit -m x', 'refused'),
    ('3 unreadable, main lexed, no commit', 'cat <<EOF\nhello', []),
    ('4 main refused, git live', W + 'git status; ' + BUILT, 'refused'),
    ('4 main refused, git in a comment', W + 'echo a # git status', 'refused'),
    ('4 main refused, git only in data', "cat <<'E'\nit's git\nE\necho ok", []),
    ('5 rewritten over cap, commit', 'git commit -m x' + '\n' * 45000, 'refused'),
    ('5 rewritten over cap, no git', 'echo x' + '\n' * 45000, []),
    ('6 no git left', 'echo git', []),
    ('7 unlexable rewrite, main lexed', 'git commit -m "$(echo "a)"', 'refused'),
    ('8 targets', 'git commit -m x', 'commit'),
])
def test_every_return_path_applies_the_refusal_rule(tmp_path, path, command, expected):
    result = outcome(command, str(tmp_path))
    if expected == 'commit':
        assert result == [(str(tmp_path), 'commit')], path
    else:
        assert result == expected, path


def test_a_body_comment_does_not_overwrite_a_command_comment():
    """The body of an unquoted here-document is read as its own text: a
    comment at the same index there must not replace the command's."""
    command = "abcdefg #git\ncat <<E\n$(echo  #c\n)\nE"  # # at index 8 of each text
    _rewritten, dropped = module.shell_text.read(command)
    assert '#git' in dropped.split('\n')


# PR #174 review, round 9. Where origin/main refused, a command name built at
# run time refuses too: with git only in here-document data, x=gi; ${x}t
# commit (I2d) runs git commit in bash and zsh, and no word git is left.
BUILT_NAMES = [
    'x=gi; ${x}t commit -m m',                                              # I2d
    '$(printf gi)t commit -m m',                                            # N1
    '`echo gi`t commit -m m',                                               # N2
    'x=gi; exec ${x}t commit -m m',                                         # N3
    'x=gi; true && ${x}t commit -m m',                                      # N4
    'x=gi; if true; then ${x}t commit -m m; fi',                            # N5
    'x=gi; A=1 ${x}t commit -m m',                                          # N6
    'x=gi; env -i PATH="$PATH" ${x}t commit -m m',                          # N7
    "x=gi; sh -c 'x=gi; ${x}t commit -m m'",                                # N8
    '/usr/bin/gi? commit -m m',                                             # N9
    '{gi,}t commit -m m',                                                   # N10
    'echo gi | xargs -I@ @t commit -m m',                                   # N11
    'x=gi; >/dev/null ${x}t commit -m m',                                   # N14
    'x=gi; case a in a) ${x}t commit -m m;; esac',                          # N15
    'x=gi; noglob ${x}t commit -m m',                                       # N16
    'x=gi; - ${x}t commit -m m',                                            # N17
    'x=gi; cat <(${x}t commit -m m)',                                       # N18
]
DATA_GIT = {
    'pre': lambda command: ": <<'Q'\nit's git\nQ\n" + command,
    'suf': lambda command: command + "\n: <<'Q'\nit's git\nQ",
}


@pytest.mark.parametrize('wrap', sorted(DATA_GIT))
@pytest.mark.parametrize('command', BUILT_NAMES)
def test_where_origin_main_refused_a_built_command_name_refuses(tmp_path, wrap, command):
    assert outcome(DATA_GIT[wrap](command), str(tmp_path)) == 'refused'


@pytest.mark.parametrize('command', [
    'echo $x',
    '[[ $x == y ]] && echo ok',
    'case $x in a) echo a;; esac',
    'for f in *.py; do echo "$f"; done',
    'gh pr create --title t --body "$(cat b.md)"',
    'x=$(date); echo "$x" > f',
    '[ -f a ] && echo b',
    '{ echo a; echo b; } > f',
    'echo "$(date) $x"',
    'echo a > "$f"',
])
def test_a_built_argument_is_not_a_built_command_name(tmp_path, command):
    assert outcome(DATA_GIT['pre'](command), str(tmp_path)) == []


@pytest.mark.parametrize('command, expected', [
    ('git status; : ' + 'a ' * 66000 + '\nx=gi; ${x}t commit -m m', 'refused'),
    (': ' + 'a ' * 66000 + '\nx=gi; ${x}t commit -m m', []),
])
def test_the_input_cap_refuses_wherever_origin_main_could_refuse(tmp_path, command, expected):
    """Over 128 KiB the word git anywhere refuses: origin/main could refuse
    only text holding git and a blank, so a built name needs no own check."""
    assert outcome(command, str(tmp_path)) == expected


def test_each_character_is_examined_by_at_most_one_word_scan(monkeypatch):
    """Positions inside text already examined are skipped: the scans are
    disjoint, so the cost is linear in the text."""
    text = ('then env A=1 then time { a; }; ' * 2000) + '$x'
    spans, built_at = [], module._built_at
    monkeypatch.setattr(module, '_built_at',
                        lambda t, i: spans.append((i, built_at(t, i)[1])) or built_at(t, i))
    assert module.builds_command_name(text)
    assert all(end <= start for (_s, end), (start, _e) in zip(spans, spans[1:]))
