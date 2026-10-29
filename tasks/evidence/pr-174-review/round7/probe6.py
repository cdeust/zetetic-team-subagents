"""Directory-aware probe: origin/main vs head (3aaeed4) git_commands targets vs real git invocations
(dir, verb) under bash, zsh and claude-zsh (/bin/zsh -c 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL ... && eval CMD < /dev/null').
Flags: FAIL-OPEN-REGRESSION = main gated (REFUSE or superset of the dirs/verbs run), head did not.
Usage: [WRAP=pre|suf|ansi] python3 -I probe6.py cases.py..."""
import importlib.util, os, re, shutil, subprocess, sys, tempfile, time
# Adapted from the round-6 reviewer's script: W is this checkout (git toplevel);
# HEAD=<rev> in the environment selects a commit, default WORKTREE = W's working tree.
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
HEAD = os.environ.get('HEAD', 'WORKTREE')
TMP = os.path.realpath(tempfile.mkdtemp(prefix='r174p6-'))
try:
    def extract(rev):
        d = os.path.join(TMP, rev.replace('/', '_')); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev, 'hooks/lib'], cwd=W, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        return d + '/hooks/lib'
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path + '/gate_targets.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    M, H = load('gt_main', extract('origin/main')), load('gt_head', W + '/hooks/lib' if HEAD == 'WORKTREE' else extract(HEAD))
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
        if sh == 'czsh':
            q = "'" + cmd.replace("'", "'\\''") + "'"
            argv = ['/bin/zsh', '-c', 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL 2>/dev/null || true && eval ' + q + ' < /dev/null']
        else:
            argv = [sh, '-c', cmd]
        try:
            p = subprocess.run(argv, cwd=run, env=env, capture_output=True, text=True,
                               timeout=20, stdin=subprocess.DEVNULL)
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
    elif WRAP == 'gitpre':
        cases = [(n, ": <<'Q'\nit's git\nQ\n" + c) for n, c in cases]
    counts = {}
    for name, cmd in cases:
        cmd = cmd.replace('{CLEAN}', os.path.join(run, 'clean'))
        t = time.time(); h = res(H, cmd); dt = time.time() - t
        m = res(M, cmd)
        sh = {s: shell(s, cmd) for s in ('bash', 'zsh', 'czsh')}
        ran = set()
        for v in sh.values():
            if isinstance(v, list): ran |= set(v)
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
        print(f'{flag:22s} {name:30s} main={short(m)!s:18s} head={short(h)!s:18s} ' +
              ' '.join(f'{k}={short(v)!s}' for k, v in sh.items()) + f' t={dt:.2f} cmd={cmd!r}')
    print('COUNTS', counts)
finally:
    shutil.rmtree(TMP)
