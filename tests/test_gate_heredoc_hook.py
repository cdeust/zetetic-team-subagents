"""The packaged PreToolUse hook reads here-document bodies as data.

Source: POSIX Shell Command Language §2.7.4 (Here-Document).
"""
import importlib.util
import io
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
    """origin/main refused this (the apostrophe), and the gate keeps that
    refusal; without the apostrophe the commit reaches the commit gate."""
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, HEREDOC + '\ngit commit -m fix')
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'origin/main refused this command' in result.stderr
    plain = HEREDOC.replace("won't", 'will not') + '\ngit commit -m fix'
    result = run_bash_hook(package, consumer, plain)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'MAGIC_NUMBER' in result.stderr


# PR #174 review cases. An unquoted body is data except its expansions
# (§2.7.4), so its prose is neither refused nor read as commands; << inside
# ${...} or $[...] is not a here-document operator (§2.6.2), and a comment
# inside a body's $(...) or a ((...)) subshell does not hide the next line.
@pytest.mark.parametrize('command', [
    "cat > hook.sh <<EOF\n#!/bin/sh\n# don't git commit from here\necho $(date)\nEOF",
    "cat > run.sh <<EOF\nstamp=$(date +%s)\n# we can't git\x20push yet\nEOF\nchmod +x run.sh",
])
def test_unquoted_heredoc_prose_is_not_refused(package, consumer, command):
    result = run_bash_hook(package, consumer, command)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('command', [
    'echo ${x//<<} &&\ngit commit -m hi',
    'x=a; echo ${x/<</y} &&\ngit push',
    'echo $[1<<2] &&\ngit commit -m hi',
    'cat <<EOF\n$( # note\ngit commit -m x\n)\nEOF',
    '((echo a) # c\ngit commit -m x)',
    'cat <<EOF\n$(if true; then case x in a) echo;; esac; fi; git commit -m x)\nEOF',
    'echo $(echo a)#b; git commit -m x',
    "cat <<$'EOF'\nbody\nEOF\ngit commit -m x",
    'cat <<A; echo $(cat <<B\nb\nB\n)\na\nA\ngit commit -m x',
    'x;(git commit -m x)',
    'echo "$(echo &>/dev/null case)"; git commit -m x; echo ";esac)"',
    'echo "${x:-{}"; git commit -m x; echo "}"',
])
def test_commit_hidden_by_rewrite_reaches_commit_gate(package, consumer, command):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, command)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'MAGIC_NUMBER' in result.stderr


@pytest.mark.parametrize('command', [
    'a[1<<2]=x &&\ngit commit -m x', 'a[1<<2]=x &&\ngit commit -m x\n2]=x'])
def test_subscript_heredoc_is_refused_before_a_commit(package, consumer, command):
    """bash reads a[1<<2]= as a subscript and runs the commit; zsh reads a
    here-document that swallows it, ended or not. The gate refuses."""
    result = run_bash_hook(package, consumer, command)
    assert result.returncode == 2, result.stdout + result.stderr
    assert '<< inside a subscript' in result.stderr


def test_heredoc_that_never_ends_is_refused_before_a_commit(package, consumer):
    result = run_bash_hook(package, consumer, "cat <<EOF\nwe don't git commit here")
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'Here-document never ends' in result.stderr


def test_heredoc_pending_at_the_end_of_a_substitution_is_refused(package, consumer):
    """bash reads the lines after $(cat <<EOF) as its body, zsh as commands."""
    result = run_bash_hook(package, consumer, 'x="$(cat <<EOF)"\ncat <<Y\nEOF\ntrue; git commit -m x\nY')
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'here-document still pending' in result.stderr


# Round 5: with an apostrophe origin/main's lexer cannot read, the rewrite
# decides alone (Z1, Z2, Z7, and the pre-existing then-git form O1).
WRAPPED = ": <<'Q'\nit's\nQ\n"


@pytest.mark.parametrize('command', [
    'echo ${x:-{} <<EOF }\ngit commit -m x\nEOF',
    'echo ${x:-{} <<EOF }\ngit push\nEOF',
    'echo "$(case x { x) echo ;; })"; git commit -m x; echo ";esac)"',
    'if true; then git commit -m x; fi',
])
def test_wrapped_commit_is_blocked(package, consumer, command):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, WRAPPED + command)
    assert result.returncode == 2, result.stdout + result.stderr


def load_hook(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'hooks'))
    spec = importlib.util.spec_from_file_location('zetetic_gates_hook', ROOT / 'hooks/zetetic-gates.py')
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


@pytest.mark.parametrize('command, code', [('git commit -m x', 2), ('echo hi', None)])
def test_unexpected_exception_blocks_only_a_commit(monkeypatch, capsys, command, code):
    """Only exit 2 blocks a Claude Code tool call; any other failure lets it
    through, so an unexpected error must not wave a commit on."""
    hook = load_hook(monkeypatch)
    monkeypatch.setattr(hook, 'run', lambda _event: (_ for _ in ()).throw(RuntimeError('boom')))
    event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(event)))
    if code is None:
        with pytest.raises(RuntimeError):
            hook.main()
    else:
        assert hook.main() == code
        assert 'unexpected RuntimeError' in capsys.readouterr().err


@pytest.mark.parametrize('command', [
    'git -C {clean} commit -m y; if true; then git commit -m x; fi',
    'git -C {clean} commit -m "$(git commit -m x)"',
    'cat <<EOF\nhello\nEO\\\nF\ngit commit -m x\nEOF',
    'x=a(#b); git commit -m x',
    'cat <<${x:-{} a}\n${x:-{} a}\ngit commit -m x\n${x:-{}\n}',
])
def test_round6_wrapped_commit_is_blocked(package, consumer, tmp_path, command):
    clean = tmp_path / 'clean'
    subprocess.run(['git', 'init', '-q', str(clean)], check=True)
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, WRAPPED + command.replace('{clean}', str(clean)))
    assert result.returncode == 2, result.stdout + result.stderr


@pytest.mark.parametrize('command', [
    'git\tcommit -m x', 'git \\\ncommit -m x', 'git\\\n commit -m x', 'x=1\tgit\tpush'])
def test_unexpected_exception_blocks_tab_and_continuation_forms(monkeypatch, capsys, command):
    hook = load_hook(monkeypatch)
    monkeypatch.setattr(hook, 'run', lambda _event: (_ for _ in ()).throw(RuntimeError('boom')))
    event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(event)))
    assert hook.main() == 2


@pytest.mark.parametrize('command', [
    'cat =(echo a)#x; git commit -m x',
    'case a in (a)#x) echo IN;; esac; git commit -m x',
    'diff =(echo a)#x =(echo a) ; git push',
    'git status; x=git; y=comm; $x ${y}it -m m',
    'y=comm; git -c alias.c=${y}it c -m x',
])
def test_round7_wrapped_command_is_blocked(package, consumer, command):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    subprocess.run(['git', 'add', '.'], cwd=consumer, check=True)
    result = run_bash_hook(package, consumer, WRAPPED + command)
    assert result.returncode == 2, result.stdout + result.stderr
