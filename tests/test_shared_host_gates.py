"""Real packaged hooks run against disposable consumer projects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=['full', 'standalone'])
def package(request, tmp_path):
    if request.param == 'full':
        return ROOT
    target = tmp_path / 'installed'
    shutil.copytree(ROOT / 'plugins/zetetic-gates', target)
    return target


@pytest.fixture
def consumer(tmp_path):
    return repository(tmp_path / 'consumer')


def repository(path):
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    (path / '.zetetic.conf').write_text('ZETETIC_PROFILE=strict\n')
    return path


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)


def invoke(package, consumer, kind, extra_env=None, **fields):
    event = dict(hook_event_name=kind, cwd=str(consumer), **fields)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(package / 'hooks/zetetic-gates.py')],
                          input=json.dumps(event), text=True, capture_output=True,
                          cwd=consumer, env=env)


@pytest.mark.parametrize('executable', ['git', '"git"', "'git'", '"/usr/bin/git"', "g'it'", '"/usr/bin/g"it'])
@pytest.mark.parametrize('verb', ['commit -m fix', 'push', '"commit" -m fix', "'push'"])
def test_staged_source_blocks(package, consumer, verb, executable):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': executable + ' ' + verb})
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'MAGIC_NUMBER' in result.stderr


def test_staged_craft_blocks(package, consumer):
    (consumer / '.craftsmanship.conf').write_text("FILE_MAX=5\nTEST_FILE_RE='^tests/'\n")
    (consumer / 'sample.py').write_text('\n'.join(f'item_{i} = None' for i in range(10)))
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': 'git commit -m fix'})
    assert result.returncode == 2, result.stdout + result.stderr


@pytest.mark.parametrize('kind', ['Stop', 'SubagentStop'])
def test_prose_blocks_by_default(package, consumer, kind):
    result = invoke(package, consumer, kind,
                    last_assistant_message="It's worth noting this change.")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['decision'] == 'block'


def test_clean_prose_passes(package, consumer):
    result = invoke(package, consumer, 'Stop', last_assistant_message='The tests pass.')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout).get('decision') != 'block'


@pytest.mark.parametrize('host', ['claude', 'codex'])
def test_edit_hint_parity(package, consumer, host):
    fields = dict(tool_name='Write', tool_input={'file_path': str(consumer / 'new.py'),
                                                'content': 'MAX_RETRIES = 12345\n'})
    if host == 'codex':
        fields = dict(tool_name='apply_patch', tool_input={'command':
                      '*** Begin Patch\n*** Add File: new.py\n+MAX_RETRIES = 12345\n*** End Patch'})
    result = invoke(package, consumer, 'PreToolUse', **fields)
    assert result.returncode == 0, result.stderr
    assert 'provenance' in json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
    assert not (consumer / 'new.py').exists()


@pytest.mark.parametrize('tool,args', [
    ('Bash', {'command': 'cat .env'}),
    ('apply_patch', {'command': 'not a patch'}),
    ('Bash', {'command': 'gh pr create --body "In conclusion, this change works."'}),
    ('mcp__codex_apps__github_create_pull_request', {'body': 'In conclusion, this change works.'}),
])
def test_refused_actions(package, consumer, tool, args):
    result = invoke(package, consumer, 'PreToolUse', tool_name=tool, tool_input=args)
    assert result.returncode == 2, result.stdout + result.stderr


def test_clean_shell_passes(package, consumer):
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash', tool_input={'command': 'ls'})
    assert result.returncode == 0, result.stderr


def test_shared_policy_loaded(package, consumer):
    result = invoke(package, consumer, 'SessionStart')
    assert result.returncode == 0, result.stderr
    assert 'source-discipline' in json.loads(result.stdout)['hookSpecificOutput']['additionalContext']


@pytest.mark.parametrize('command', ['git -C {target} commit -m fix', 'cd {target} && git commit -m fix'])
def test_effective_commit_repository(package, consumer, tmp_path, command):
    target = repository(tmp_path / 'target')
    (target / 'sample.py').write_text('DELAY = 2.741592\n')
    git(target, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': command.format(target=target)})
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'MAGIC_NUMBER' in result.stderr


@pytest.mark.parametrize('host', ['exec_command', 'Write', 'apply_patch'])
def test_post_deletion_checks_target_repository(package, consumer, tmp_path, host):
    target = repository(tmp_path / 'other-repo')
    (target / 'lib.py').write_text('def emit(x):\n    return x\n')
    (target / 'caller.py').write_text('from lib import emit\nvalue = emit(None)\n')
    git(target, 'add', '.')
    git(target, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
    (target / 'lib.py').write_text('')
    inputs = {
        'exec_command': {'cmd': 'rm lib.py', 'workdir': str(target)},
        'Write': {'file_path': str(target / 'lib.py'), 'content': ''},
        'apply_patch': {'command': f'*** Begin Patch\n*** Delete File: {target}/lib.py\n*** End Patch'},
    }
    result = invoke(package, consumer, 'PostToolUse', tool_name=host, tool_input=inputs[host])
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'caller.py' in result.stderr


def test_sources_and_full_manifest_do_not_drift():
    subprocess.run([sys.executable, str(ROOT / 'scripts/sync-gates.py'), '--check'], check=True)
    manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
    canonical = json.loads((ROOT / 'hooks/hooks.json').read_text())
    assert manifest['hooks'] == canonical['hooks']


def test_codex_manifests_discover_gates():
    for root in (ROOT, ROOT / 'plugins/zetetic-gates'):
        manifest = json.loads((root / '.codex-plugin/plugin.json').read_text())
        hooks = json.loads((root / manifest['hooks']).read_text())['hooks']
        assert {'SessionStart', 'PreToolUse', 'PostToolUse', 'Stop', 'SubagentStop'} <= hooks.keys()


@pytest.mark.parametrize('command', ['echo git commit', 'git log --grep commit', "printf 'git commit'"])
def test_mentions_do_not_trigger_commit_gate(package, consumer, command):
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': command})
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('command', ['git --git-dir=/other/.git commit', 'GIT_DIR=/other/.git git commit'])
def test_explicit_git_repository_selector_refused(package, consumer, command):
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': command})
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'unsupported' in result.stderr


@pytest.mark.parametrize('command', [
    'GIT_DIR=/x git log', 'git --git-dir=/x status', 'GIT_INDEX_FILE=/x git add -A',
])
def test_other_git_verbs_allow_selectors(package, consumer, command):
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': command})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('command', ['cd /tmp && echo "x', 'git status && echo "x'])
def test_post_tool_malformed_quotes_do_not_crash(package, consumer, command):
    result = invoke(package, consumer, 'PostToolUse', tool_name='Bash',
                    tool_input={'command': command})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('profile', [None, 'standard', 'strict'])
def test_source_profile_is_declared(package, consumer, profile):
    config = consumer / '.zetetic.conf'
    if profile is None:
        config.unlink()
    else:
        config.write_text(f'ZETETIC_PROFILE={profile}\n')
    (consumer / 'sample.py').write_text('DELAY = 2.741592\n')
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': 'git commit -m fix'})
    assert result.returncode == (2 if profile == 'strict' else 0), result.stderr


@pytest.mark.parametrize('profile', ['standard', 'strict'])
def test_staged_prose_follows_declared_profile(package, consumer, profile):
    (consumer / '.zetetic.conf').write_text(f'ZETETIC_PROFILE={profile}\n')
    (consumer / 'README.md').write_text('We delve into this topic.\n')
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': 'git commit -m fix'})
    assert result.returncode == (2 if profile == 'strict' else 0), result.stderr


def test_checker_config_error_blocks(package, consumer):
    (consumer / '.craftsmanship.conf').write_text('if then\n')
    (consumer / 'sample.py').write_text('value = None\n')
    git(consumer, 'add', '.')
    result = invoke(package, consumer, 'PreToolUse', tool_name='Bash',
                    tool_input={'command': 'git commit -m fix'})
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'validation failed' in result.stderr


@pytest.mark.parametrize('filename', ['hooks/hooks.json', 'hooks/gates.json'])
@pytest.mark.parametrize('kind', ['PreToolUse', 'PostToolUse'])
def test_matchers_cover_secret_tools_and_skip_unrelated_tools(filename, kind):
    import re
    hooks = json.loads((ROOT / filename).read_text())['hooks']
    group = next(
        group for group in hooks[kind]
        if any('zetetic-gates.py' in hook['command'] for hook in group['hooks']))
    matcher = group['matcher']
    names = ['Bash', 'exec_command', 'apply_patch', 'Edit', 'Write']
    if kind == 'PreToolUse':
        names += ['Read', 'Grep', 'NotebookEdit', 'mcp__github__create_pull_request']
    for name in names:
        assert re.fullmatch(matcher, name)
    assert not re.fullmatch(matcher, 'TodoWrite')


def pushing_repository(consumer, test_body):
    """A committed source and test, then the source changed and a test added."""
    git(consumer, 'config', 'user.email', 't@t.t')
    git(consumer, 'config', 'user.name', 't')
    (consumer / 'src').mkdir()
    (consumer / 'tests').mkdir()
    (consumer / 'src/thing.py').write_text('def answer():\n    return 1\n')
    (consumer / 'tests/test_thing.py').write_text(
        'def test_answer_exists():\n    from src.thing import answer\n\n    assert answer()\n')
    git(consumer, 'add', '.')
    git(consumer, 'commit', '-qm', 'base')
    (consumer / 'src/thing.py').write_text('def answer():\n    return 42\n')
    (consumer / 'tests/test_new.py').write_text(test_body)
    return {'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']}


@pytest.mark.parametrize('host, field', [('Bash', 'command'), ('exec_command', 'cmd')])
@pytest.mark.parametrize('body, code, marker', [
    ('def test_truthy():\n    from src.thing import answer\n\n    assert answer()\n', 2, 'VACUOUS'),
    ('def test_is_42():\n    from src.thing import answer\n\n    assert answer() == 42\n', 0, ''),
])
def test_push_runs_fail_before_gate(package, consumer, host, field, body, code, marker):
    extra_env = pushing_repository(consumer, body)
    result = invoke(package, consumer, 'PreToolUse', extra_env, tool_name=host,
                    tool_input={field: 'git push'})
    assert result.returncode == code, result.stdout + result.stderr
    # A test that fails on the old tree is the quiet path: nothing relayed.
    assert ('VACUOUS' in result.stderr) == bool(marker), result.stderr
    assert result.stderr.count('BLOCKED') == (1 if marker else 0), result.stderr
