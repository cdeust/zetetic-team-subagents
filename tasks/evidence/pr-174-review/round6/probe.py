"""Directory-aware probe: main vs head (af57ea7) targets vs real bash/zsh git invocations (dir, verb).
Usage: [WRAP=pre|suf|ansi] python3 -I probe.py cases.py..."""
import importlib.util, os, re, shutil, subprocess, sys, tempfile, time
# Adapted from the round-5 reviewer's probe.py: W is this checkout and head is its
# working tree.
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
TMP = os.path.realpath(tempfile.mkdtemp(prefix='r174p-'))
try:
    def extract(rev):
        d = os.path.join(TMP, rev.replace('/', '_')); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev, 'hooks/lib'], cwd=W, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        return d + '/hooks/lib'
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path + '/gate_targets.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    M, H = load('gt_main', extract('origin/main')), load('gt_head', W + '/hooks/lib')
    shim, run = os.path.join(TMP, 'shim'), os.path.join(TMP, 'run')
    os.makedirs(shim); os.makedirs(run); os.makedirs(os.path.join(run, 'clean'))
    with open(shim + '/git', 'w') as f:
        f.write('#!/bin/sh\nd=$PWD\nif [ "$1" = -C ]; then d=$(cd "$2" && pwd -P); shift 2; fi\necho "SHIM-GIT $d $1" >&2\n')
    os.chmod(shim + '/git', 0o700)
    def res(mod, cmd):
        try:
            return sorted(set(mod.git_commands(cmd, run)))
        except ValueError:
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
        return sorted(set(re.findall(r'SHIM-GIT (\S+) (commit|push)\b', p.stdout + p.stderr)))
    def short(r):
        if isinstance(r, str): return r
        return [(os.path.relpath(d, run), v) for d, v in r]
    cases = []
    for f in sys.argv[1:]:
        ns = {'cases': []}
        with open(f) as fh:
            exec(fh.read(), ns)
        tag = os.path.basename(f)[:-3]
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
        cmd = cmd.replace('{CLEAN}', os.path.join(run, 'clean'))  # adapted: decoy repo, as in e2e5.py
        t = time.time(); h = res(H, cmd); dt = time.time() - t
        m = res(M, cmd)
        b, z = shell('bash', cmd), shell('zsh', cmd)
        ran = set(b if isinstance(b, list) else []) | set(z if isinstance(z, list) else [])
        def gated(r): return r == 'REFUSE' or (isinstance(r, list) and set(r) >= ran)
        if isinstance(h, str) and h.startswith('CRASH'):
            flag = 'HEAD-CRASH'
        elif ran and not gated(h):
            flag = 'FAIL-OPEN' + ('-REGRESSION' if gated(m) else '-PREEXISTING')
        elif not ran and h == 'REFUSE' and m != 'REFUSE':
            flag = 'NEW-REFUSE'
        elif ran and gated(h) and not gated(m):
            flag = 'FIXED'
        else:
            flag = 'ok'
        counts[flag] = counts.get(flag, 0) + 1
        print(f'{flag:24s} {name:34s} main={short(m)!s:22s} head={short(h)!s:22s} bash={short(b)!s:22s} zsh={short(z)!s:22s} cmd={cmd!r}')
    print('COUNTS', counts)
finally:
    shutil.rmtree(TMP)
