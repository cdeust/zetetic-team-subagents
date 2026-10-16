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
