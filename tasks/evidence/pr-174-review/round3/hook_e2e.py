"""End-to-end PreToolUse run of hooks/zetetic-gates.py at origin/main and at 3931211 on a consumer repo
with a staged strict-profile violation. Usage: python3 -I hook_e2e.py cases.py"""
import json, os, subprocess, sys, shutil, tempfile
# Adapted from the round-2 reviewer's hook_e2e.py: W is this checkout; 'head'
# is its working tree, 'r2' the round-2 head 3931211.
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
T = tempfile.mkdtemp(prefix='r174e2e-')
LITERAL = '2.741592'  # source: an unsourced literal the strict gate must block
try:
    roots = {}
    for label, rev in (('main', 'origin/main'), ('r2', '3931211')):
        d = os.path.join(T, label); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev], cwd=W, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        roots[label] = d
    roots['head'] = W
    cases = []
    with open(sys.argv[1]) as f:
        exec(f.read())
    for name, cmd in cases:
        for label, root in roots.items():
            c = os.path.join(T, 'consumer'); shutil.rmtree(c, ignore_errors=True)
            subprocess.run(['git', 'init', '-q', c], check=True)
            with open(c + '/.zetetic.conf', 'w') as f:
                f.write('ZETETIC_PROFILE=strict\n')
            with open(c + '/sample.py', 'w') as f:
                f.write('DELAY = ' + LITERAL + '\n')
            subprocess.run(['git', 'add', '.'], cwd=c, check=True)
            ev = {'hook_event_name': 'PreToolUse', 'cwd': c, 'tool_name': 'Bash', 'tool_input': {'command': cmd}}
            env = {k: v for k, v in os.environ.items() if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
            r = subprocess.run([sys.executable, root + '/hooks/zetetic-gates.py'], input=json.dumps(ev), text=True,
                               capture_output=True, cwd=c, env=env, stdin=None)
            out = (r.stderr + r.stdout).strip().replace('\n', ' | ').replace(LITERAL, '<literal>')
            print(f'{name:28s} {label:4s} exit={r.returncode} :: {out[:170]}')
finally:
    shutil.rmtree(T)
