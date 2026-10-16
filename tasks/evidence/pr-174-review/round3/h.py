"""Compare gate_targets.git_commands of origin/main vs review worktree head vs real bash/zsh (git shim).
Usage: python3 -I h.py cases.py"""
import importlib.util, os, re, shutil, subprocess, sys, tempfile
# Adapted from the round-2 reviewer's h.py: W is this checkout, and 'head' is
# its working tree (round-2 head 3931211 is kept as 'r2' for comparison).
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
    mods = {'main': load('gt_main', extract('origin/main')), 'r2': load('gt_r2', extract('3931211')),
            'head': load('gt_head', W + '/hooks/lib')}
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
    def shell(sh, cmd):
        env = dict(os.environ, PATH=shim + ':' + os.environ['PATH'], LC_ALL='C')
        try:
            p = subprocess.run([sh, '-c', cmd], cwd=run, env=env, capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 'TIMEOUT'
        return sorted(set(x for x in re.findall(r'SHIM-GIT (\w+)', p.stdout + p.stderr) if x in ('commit', 'push')))
    cases = []
    with open(sys.argv[1]) as f:
        exec(f.read())
    counts = {}
    for name, cmd in cases:
        m, r2, h = res(mods['main'], cmd), res(mods['r2'], cmd), res(mods['head'], cmd)
        b, z = shell('bash', cmd), shell('zsh', cmd)
        ran = set(b if isinstance(b, list) else []) | set(z if isinstance(z, list) else [])
        def gated(r): return r == 'REFUSE' or set(r) >= ran
        if ran and not gated(h):
            flag = 'FAIL-OPEN' + ('-REGRESSION' if gated(m) else '-PREEXISTING')
        elif not ran and h == 'REFUSE' and m != 'REFUSE':
            flag = 'NEW-REFUSE'
        elif ran and gated(h) and not gated(m):
            flag = 'FIXED'
        else:
            flag = 'ok'
        counts[flag] = counts.get(flag, 0) + 1
        print(f'{flag:22s} {name:30s} main={m!s:18s} r2={r2!s:18s} head={h!s:18s} bash={b!s:18s} zsh={z!s:18s} cmd={cmd!r}')
    print('COUNTS', counts)
finally:
    shutil.rmtree(TMP)
