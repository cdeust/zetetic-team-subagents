"""Host event contracts: equivalent inputs without writing target files."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'host_events', Path(__file__).resolve().parents[1] / 'hooks/lib/host_events.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
normalize_event = module.normalize_event
HostEventError = module.HostEventError


def patch_event(tmp_path, body):
    return {'cwd': str(tmp_path), 'tool_name': 'apply_patch', 'tool_input': {
        'command': '*** Begin Patch\n' + body + '\n*** End Patch'}}


def test_update_matches_claude_without_writes(tmp_path):
    target = tmp_path / 'source.py'
    target.write_text('before\n')
    expected = {'cwd': str(tmp_path), 'tool_name': 'Edit', 'tool_input': {
        'file_path': str(target), 'old_string': 'before\n', 'new_string': 'after\n'}}
    actual = patch_event(tmp_path, '*** Update File: source.py\n@@\n-before\n+after')
    assert normalize_event(actual) == normalize_event(expected)
    assert target.read_text() == 'before\n'


def test_add_delete_move_multiple_hunks(tmp_path):
    (tmp_path / 'old.py').write_text('one\ntwo\nthree\nfour\n')
    (tmp_path / 'gone.py').write_text('gone\n')
    patch = '''*** Add File: new.py
+new
*** Delete File: gone.py
*** Update File: old.py
*** Move to: moved.py
@@ one
-two
+second
@@ three
-four
+fourth
*** End of File'''
    events = normalize_event(patch_event(tmp_path, patch))
    assert [e['tool_name'] for e in events] == ['Write', 'Edit', 'Edit', 'Write']
    assert events[-1]['tool_input']['content'] == 'one\nsecond\nthree\nfourth\n'
    assert (tmp_path / 'old.py').read_text() == 'one\ntwo\nthree\nfour\n'
    assert (tmp_path / 'gone.py').exists()
    assert not (tmp_path / 'moved.py').exists()
    assert not (tmp_path / 'new.py').exists()


@pytest.mark.parametrize('body', [
    '*** Update File: source.py\n@@\n-wrong\n+after',
    '*** Update File: source.py\n@@\n-before\n+after\n*** Unsupported',
    '*** Update File: missing.py\n@@\n-x\n+y',
    '*** Add File: source.py\n+overwrite', '*** Delete File: missing.py',
    '*** Update File: source.py\n@@ missing anchor\n-before\n+after',
    '*** Update File: source.py\n@@\n?bad', '*** Update File: source.py',
])
def test_invalid_patch_refuses_without_mutation(tmp_path, body):
    target = tmp_path / 'source.py'
    target.write_text('before\n')
    with pytest.raises(HostEventError):
        normalize_event(patch_event(tmp_path, body))
    assert target.read_text() == 'before\n'


def test_ambiguous_context_refuses(tmp_path):
    (tmp_path / 'a').write_text('same\nsame\n')
    with pytest.raises(HostEventError, match='ambiguous'):
        normalize_event(patch_event(tmp_path, '*** Update File: a\n@@\n-same\n+changed'))


@pytest.mark.parametrize('name,key', [('exec_command', 'cmd'), ('shell_command', 'command'), ('Bash', 'command')])
def test_shell_workdir(tmp_path, name, key):
    event = {'tool_name': name, 'cwd': '/ignored', 'tool_input': {key: 'git status', 'workdir': str(tmp_path)}}
    output = normalize_event(event)[0]
    assert output['tool_name'] == 'Bash'
    assert output['tool_input']['command'] == 'git status'
    assert output['cwd'] == str(tmp_path)


def test_unknown_tool_passes_through():
    event = {'tool_name': 'Read', 'tool_input': {'file_path': 'a'}}
    assert normalize_event(event) == [event]


@pytest.mark.parametrize('patch', ['', '*** Begin Patch\n*** End Patch', 'garbage'])
def test_malformed_envelope(tmp_path, patch):
    event = patch_event(tmp_path, '')
    event['tool_input']['command'] = patch
    with pytest.raises(HostEventError):
        normalize_event(event)


def test_initial_context_and_eof(tmp_path):
    (tmp_path / 'a').write_text('head\ntail\n')
    output = normalize_event(patch_event(tmp_path, '*** Update File: a\n head\n-tail\n+end\n*** End of File'))
    assert output[0]['tool_input']['new_string'] == 'head\nend\n'


def test_eof_refuses_nonterminal_context(tmp_path):
    (tmp_path / 'a').write_text('head\ntail\n')
    with pytest.raises(HostEventError):
        normalize_event(patch_event(tmp_path, '*** Update File: a\n@@\n-head\n+end\n*** End of File'))


def test_sequential_operations_use_prospective_state(tmp_path):
    events = normalize_event(patch_event(tmp_path, '*** Add File: a\n+first\n*** Update File: a\n@@\n-first\n+second'))
    assert events[1]['tool_input']['old_string'] == 'first\n'
    assert events[1]['tool_input']['new_string'] == 'second\n'
    assert not (tmp_path / 'a').exists()
