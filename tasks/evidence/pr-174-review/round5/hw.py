"""Compare gate_targets.git_commands of origin/main vs review worktree head vs real bash/zsh (git shim).
Usage: python3 -I h.py cases.py"""
import importlib.util, os, re, shutil, subprocess, sys, tempfile
# Adapted from the round-4 reviewer's hw.py: W is this checkout, 'head' its working
# tree, 'r4' the round-4 head 981aab9; 'parser' is head with _flat_targets stubbed.
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
TMP = tempfile.mkdtemp(prefix='r174h-')
try:
    def extract(rev):
        d = os.path.join(TMP, rev.replace('/', '_')); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev, 'hooks/lib'], cwd=W, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        return d + '/hooks/lib'
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path + '/gate_targets.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    mods = {'main': load('gt_main', extract('origin/main')), 'head': load('gt_head', W + '/hooks/lib')}
    mods['headp'] = load('gt_headp', W + '/hooks/lib')
    mods['headp']._flat_targets = lambda c, b: []
    mods['proto'] = load('gt_r4', extract('981aab9'))
    shim, run = os.path.join(TMP, 'shim'), os.path.join(TMP, 'run')
    os.makedirs(shim); os.makedirs(run)
    with open(shim + '/git', 'w') as f:
        f.write('#!/bin/sh\necho "SHIM-GIT $1" >&2\n')
    os.chmod(shim + '/git', 0o700)
    def res(mod, cmd):
        try:
            return sorted(set(v for _d, v in mod.git_commands(cmd, '/tmp/base')))
        except ValueError as e:
            return 'REFUSE'
        except Exception as e:
            return 'CRASH:' + type(e).__name__
    def shell(sh, cmd):
        env = dict(os.environ, PATH=shim + ':' + os.environ['PATH'], LC_ALL='C')
        try:
            p = subprocess.run([sh, '-c', cmd], cwd=run, env=env, capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 'TIMEOUT'
        return sorted(set(x for x in re.findall(r'SHIM-GIT (\w+)', p.stdout + p.stderr) if x in ('commit', 'push')))
    cases = []
    for f in sys.argv[1:]:
        ns = {'cases': []}
        with open(f) as handle:
            exec(handle.read(), ns)
        tag = os.path.basename(os.path.dirname(f)) + '/' + os.path.basename(f)[:-3]
        cases += [(tag + ':' + n, c) for n, c in ns['cases']]
    WRAP = os.environ.get('WRAP', '')
    if WRAP == 'pre':
        cases = [(n, ": <<'Q'\nit's\nQ\n" + c) for n, c in cases]
    elif WRAP == 'suf':
        cases = [(n, c + "\n: <<'Q'\nit's\nQ") for n, c in cases]
    elif WRAP == 'ansi':
        cases = [(n, "echo $'\\''\n" + c) for n, c in cases]
    counts = {}
    for name, cmd in cases:
        m, h, hp = res(mods['main'], cmd), res(mods['head'], cmd), res(mods['headp'], cmd)
        pr = res(mods['proto'], cmd)
        b, z = shell('bash', cmd), shell('zsh', cmd)
        ran = set(b if isinstance(b, list) else []) | set(z if isinstance(z, list) else [])
        def gated(r): return r == 'REFUSE' or (isinstance(r, list) and set(r) >= ran)
        if ran and not gated(h):
            flag = 'FAIL-OPEN' + ('-REGRESSION' if gated(m) else '-PREEXISTING')
        elif not ran and h == 'REFUSE' and m != 'REFUSE':
            flag = 'NEW-REFUSE'
        elif ran and gated(h) and not gated(m):
            flag = 'FIXED'
        else:
            flag = 'ok'
        pflag = 'R4-FAIL-OPEN' if (ran and not gated(pr)) else 'R4-ok'
        flag = flag + '/' + pflag
        counts[flag] = counts.get(flag, 0) + 1
        print(f'{flag:22s} {name:30s} main={m!s:18s} head={h!s:18s} parser={hp!s:18s} r4={pr!s:14s} bash={b!s:18s} zsh={z!s:18s} cmd={cmd!r}')
    print('COUNTS', counts)
finally:
    shutil.rmtree(TMP)
