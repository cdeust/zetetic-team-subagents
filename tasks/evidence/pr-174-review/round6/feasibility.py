"""Fermi check of the hook's worst time at the size cap: the full PreToolUse
hook on commands just under MAX_COMMAND whose cost is dominated by shlex
reading one long token (quadratic in its length). Usage: python3 -I feasibility.py"""
import json, os, subprocess, sys, tempfile, time
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
CAP = 131072  # source: hooks/lib/gate_targets.py MAX_COMMAND
shapes = {
    'one dq token at cap': 'git commit -m "' + 'x' * (CAP - 20) + '"',
    'one plain token at cap': 'git commit -m ' + 'x' * (CAP - 20),
    'many short words at cap': 'git commit -m "' + 'ab ' * ((CAP - 20) // 3) + '"',
}
with tempfile.TemporaryDirectory() as consumer:
    subprocess.run(['git', 'init', '-q', consumer], check=True)
    print('load', [round(x) for x in os.getloadavg()])
    for name, cmd in shapes.items():
        event = {'hook_event_name': 'PreToolUse', 'cwd': consumer, 'tool_name': 'Bash',
                 'tool_input': {'command': cmd}}
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
        t = time.time()
        r = subprocess.run([sys.executable, W + '/hooks/zetetic-gates.py'], input=json.dumps(event),
                           text=True, capture_output=True, cwd=consumer, env=env)
        print(f'{time.time() - t:7.2f}s len={len(cmd)} exit={r.returncode} {name}', flush=True)
