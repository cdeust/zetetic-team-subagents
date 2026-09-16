#!/usr/bin/env python3
"""Host-neutral gate entry point. Source: docs/shared-host-gates.md."""

import json
import os
from pathlib import Path
import subprocess
import sys

from lib.host_events import HostEventError, normalize_event
from lib.gate_targets import git_directories, post_directories

ROOT = Path(__file__).resolve().parents[1]


def invoke(name, event):
    """Run a bundled checker against the event's working directory."""
    path = ROOT / 'hooks' / name
    if 'redaction' in name and not os.access(ROOT / 'tools/redaction-checker.sh', os.X_OK):
        raise HostEventError('Bundled redaction checker is missing or not executable')
    command = [sys.executable if path.suffix == '.py' else 'bash', str(path)]
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT))
    env.setdefault('ZETETIC_PROFILE', 'strict')
    env['REDACTION_STOP_BLOCK'] = 'on'
    result = subprocess.run(command, input=json.dumps(event), text=True,
                            capture_output=True, cwd=event.get('cwd') or os.getcwd(),
                            env=env)
    if result.returncode:
        raise HostEventError(result.stderr.strip() or result.stdout.strip()
                             or f'{name} failed ({result.returncode})')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    return result.stdout.strip()


def before(event):
    """Adapt edits once, then use the same checks for both hosts."""
    context = []
    for normalized in normalize_event(event):
        name = normalized.get('tool_name', '')
        invoke('pre-tool-secret-shield.py', normalized)
        if name in ('Edit', 'Write'):
            for script in ('pre-tool-claim-gate.sh', 'pre-edit-layer-check.sh',
                           'pre-tool-deletion-gate.py'):
                output = invoke(script, normalized)
                context.extend([output] if output else [])
        if name == 'Bash':
            command = normalized['tool_input'].get('command', '')
            for directory in git_directories(command, normalized.get('cwd') or os.getcwd()):
                # Target parser confirmed commit/push; avoid interpreting its
                # quoting again in legacy shell guards. Both verbs run these checks.
                gated = {**normalized, 'cwd': directory,
                         'tool_input': {'command': 'git commit'}}
                invoke('pre-commit-zetetic.sh', gated)
        if name.startswith('mcp__codex_apps__github_'):
            normalized = {**normalized, 'tool_name': name.replace('mcp__codex_apps__github_', 'mcp__github__', 1)}
        if name == 'Bash' or name.startswith('mcp__'):
            invoke('pre-tool-redaction-gate.py', normalized)
    if context:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                      'additionalContext': '\n'.join(context)}}
    return {}


def run(event):
    kind = event.get('hook_event_name', '')
    if kind == 'PreToolUse':
        return before(event)
    if kind == 'PostToolUse':
        name = event.get('tool_name', '')
        if name in ('apply_patch', 'Edit', 'Write', 'Bash', 'exec_command', 'shell_command'):
            for directory in post_directories(event):
                invoke('post-tool-deletion-gate.py', {**event, 'tool_name': 'Bash', 'cwd': directory})
        return {}
    if kind in ('Stop', 'SubagentStop'):
        output = invoke('stop-redaction-gate.py', event)
        return json.loads(output) if output else {}
    if kind == 'SessionStart':
        policy = (ROOT / 'rules/gates-policy.md').read_text()
        policy += '\nFull rules: ' + str(ROOT / 'rules/coding-standards.md')
        return {'hookSpecificOutput': {'hookEventName': kind,
                                      'additionalContext': policy}}
    return {}


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise HostEventError('hook input must be a JSON object')
        print(json.dumps(run(event)))
        return 0
    except (HostEventError, OSError, ValueError) as error:
        print(f'Zetetic gates: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
