"""(round 6: W/HEAD -> review-174-r6 / 3aaeed4; adds czsh = Claude Code zsh invocation)
End-to-end PreToolUse run of hooks/zetetic-gates.py at origin/main and at af57ea7 on a consumer repo
with a staged strict-profile violation; {CLEAN} is replaced by a sibling clean repo (a decoy target).
Each case is also run under bash and zsh with a git shim to show which git verbs/dirs really run.
Usage: python3 -I e2e5.py cases.py"""
import json, os, re, subprocess, sys, shutil, tempfile
# Adapted from the round-6 reviewer's script: W is this checkout (git toplevel);
# HEAD=<rev> in the environment selects a commit, default WORKTREE = W's working tree.
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
HEAD = os.environ.get('HEAD', 'WORKTREE')
LITERAL = '2.741592'  # source: an unsourced literal the strict gate must block
T = os.path.realpath(tempfile.mkdtemp(prefix='r174e6-'))
try:
    roots = {}
    for label, rev in (('main', 'origin/main'), ('head', HEAD)):
        if rev == 'WORKTREE':
            roots[label] = W
            continue
        d = os.path.join(T, label); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev], cwd=W, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        roots[label] = d
    shim = os.path.join(T, 'shim'); os.makedirs(shim)
    with open(shim + '/git', 'w') as f:
        f.write('#!/bin/sh\nd=$PWD\nif [ "$1" = -C ]; then d=$(cd "$2" && pwd -P); shift 2; fi\necho "SHIM-GIT $d $1" >&2\n')
    os.chmod(shim + '/git', 0o700)
    clean = os.path.join(T, 'clean')
    subprocess.run(['git', 'init', '-q', clean], check=True)
    ns = {'cases': []}
    with open(sys.argv[1]) as fh:
        exec(fh.read(), ns)
    for name, cmd in ns['cases']:
        cmd = cmd.replace('{CLEAN}', clean)
        c = os.path.join(T, 'consumer')
        ran = []
        for sh in ('bash', 'zsh', 'czsh'):
            shutil.rmtree(c, ignore_errors=True); os.makedirs(c); os.makedirs(c + '/clean', exist_ok=True)
            env = dict(os.environ, PATH=shim + ':' + os.environ['PATH'], LC_ALL='C')
            q = "'" + cmd.replace("'", "'\\''") + "'"
            argv = ['/bin/zsh', '-c', 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL 2>/dev/null || true && eval ' + q + ' < /dev/null'] if sh == 'czsh' else [sh, '-c', cmd]
            p = subprocess.run(argv, cwd=c, env=env, capture_output=True, text=True, timeout=10,
                               stdin=subprocess.DEVNULL)
            got = sorted(set((os.path.relpath(d, T), v) for d, v in re.findall(r'SHIM-GIT (\S+) (commit|push)\b', p.stderr)))
            ran.append(f'{sh}={got}')
        print(f'{name:32s} runs: {" ".join(ran)}   cmd={cmd!r}')
        for label, root in roots.items():
            shutil.rmtree(c, ignore_errors=True)
            subprocess.run(['git', 'init', '-q', c], check=True)
            with open(c + '/.zetetic.conf', 'w') as f: f.write('ZETETIC_PROFILE=strict\n')
            with open(c + '/sample.py', 'w') as f: f.write('DELAY = ' + LITERAL + '\n')
            subprocess.run(['git', 'add', '.'], cwd=c, check=True)
            ev = {'hook_event_name': 'PreToolUse', 'cwd': c, 'tool_name': 'Bash', 'tool_input': {'command': cmd}}
            env = {k: v for k, v in os.environ.items() if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
            r = subprocess.run([sys.executable, root + '/hooks/zetetic-gates.py'], input=json.dumps(ev), text=True,
                               capture_output=True, cwd=c, env=env)
            out = (r.stderr + r.stdout).strip().replace('\n', ' | ').replace(LITERAL, '<literal>')
            print(f'    {label:4s} exit={r.returncode} :: {out[:150]}')
finally:
    shutil.rmtree(T)
