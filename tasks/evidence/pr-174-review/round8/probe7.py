"""Round-7 three-way probe: git_commands of origin/main, 3aaeed4 (round-6 head) and 888312b
(round-7 head), each loaded from `git archive` of REPO, against the git commit/push really run
by bash, zsh and czsh (= /bin/zsh -c 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL ... && eval CMD < /dev/null',
the Claude Code Bash tool invocation on this machine) with a git shim on PATH.
Flags vs main: FAIL-OPEN-REGRESSION (main gated, r7 not, a shell ran git), FAIL-OPEN-PREEXISTING,
FIXED, NEW-REFUSE (no shell ran git, r7 REFUSE, main not), HEAD-CRASH, ok.
Flags vs r6: R7-WEAKER (r6 gated, r7 not, a shell ran), R7-REFUSE-COST (no shell ran, r7 REFUSE, r6 not),
R7-REFUSE-FIX (a shell ran, r7 REFUSE, r6 not gated).
flatEq: whether (main raised ValueError) == (r7 _flat_targets is None or raises).
Usage: [WRAP=none|pre|suf|ansi|gitpre] python3 -I probe7.py REPO cases.py..."""
import importlib.util, os, re, shutil, subprocess, sys, tempfile, time
REPO = sys.argv[1]
# Round 8 (fixer): the columns r6 and r7 are the previous and the new head.
# PREV (default 888312b, the round-7 head) and NEW (default WORKTREE = REPO's
# working tree) select them, so one script gives before (NEW=888312b,
# PREV=3aaeed4) and after (PREV=888312b, NEW=WORKTREE).
REVS = (('main', 'origin/main'), ('r6', os.environ.get('PREV', '888312bd488599ba6a569d137beb10355bebb39e')),
        ('r7', os.environ.get('NEW', 'WORKTREE')))
TMP = os.path.realpath(tempfile.mkdtemp(prefix='r174p7-'))
try:
    def extract(rev):
        if rev == 'WORKTREE':
            spec = importlib.util.spec_from_file_location('gt_worktree', REPO + '/hooks/lib/gate_targets.py')
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
        d = os.path.join(TMP, rev.replace('/', '_')); os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev, 'hooks/lib'], cwd=REPO, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        spec = importlib.util.spec_from_file_location('gt_' + rev[:7].replace('/', '_'), d + '/hooks/lib/gate_targets.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    MOD = {label: extract(rev) for label, rev in REVS}
    shim, run = os.path.join(TMP, 'shim'), os.path.join(TMP, 'run')
    os.makedirs(shim, mode=0o700); os.makedirs(run); os.makedirs(os.path.join(run, 'clean'))
    fd = os.open(shim + '/git', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, 'w') as f:
        f.write('#!/bin/sh\nd=$PWD\nif [ "$1" = -C ]; then d=$(cd "$2" && pwd -P); shift 2; fi\necho "SHIM-GIT $d $1" >&2\n')

    def res(mod, cmd):
        try:
            return sorted(set(mod.git_commands(cmd, run)))
        except ValueError:
            return 'REFUSE'
        except Exception as e:  # report, never hide
            return 'CRASH:' + type(e).__name__

    def flat_refused(mod, cmd):
        try:
            return mod._flat_targets(cmd, run) is None
        except ValueError:
            return True

    def shell(sh, cmd):
        env = dict(os.environ, PATH=shim + ':' + os.environ['PATH'], LC_ALL='C')
        if sh == 'czsh':
            q = "'" + cmd.replace("'", "'\\''") + "'"
            argv = ['/bin/zsh', '-c', 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL 2>/dev/null || true && eval ' + q + ' < /dev/null']
        else:
            argv = [sh, '-c', cmd]
        try:
            p = subprocess.run(argv, cwd=run, env=env, capture_output=True, text=True, timeout=20,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 'TIMEOUT'
        return sorted(set(re.findall(r'SHIM-GIT (\S+) (commit|push)\b', p.stdout + p.stderr)))

    def short(r):
        return r if isinstance(r, str) else [(os.path.relpath(d, run), v) for d, v in r]

    cases = []
    for f in sys.argv[2:]:
        ns = {'cases': []}
        with open(f) as fh:
            exec(fh.read(), ns)  # local, reviewer-written case files only
        tag = os.path.basename(f)[:-3]
        cases += [(tag + ':' + n, c) for n, c in ns['cases']]
    WRAP = os.environ.get('WRAP', 'none')
    wraps = {'none': ('', ''), 'pre': (": <<'Q'\nit's\nQ\n", ''), 'suf': ('', "\n: <<'Q'\nit's\nQ"),
             'ansi': ("echo $'\\''\n", ''), 'gitpre': (": <<'Q'\nit's git\nQ\n", '')}
    pre, suf = wraps[WRAP]
    counts, counts6 = {}, {}
    for name, cmd in cases:
        cmd = pre + cmd.replace('{CLEAN}', os.path.join(run, 'clean')) + suf
        r = {}
        for label, mod in MOD.items():
            t = time.time(); r[label] = res(mod, cmd); r[label + '_t'] = time.time() - t
        sh = {s: shell(s, cmd) for s in ('bash', 'zsh', 'czsh')}
        ran = set()
        for v in sh.values():
            if isinstance(v, list): ran |= set(v)
        def gated(x): return x == 'REFUSE' or (isinstance(x, list) and set(x) >= ran)
        m, h6, h = r['main'], r['r6'], r['r7']
        if isinstance(h, str) and h.startswith('CRASH'): flag = 'HEAD-CRASH'
        elif ran and not gated(h): flag = 'FAIL-OPEN' + ('-REGRESSION' if gated(m) else '-PREEXISTING')
        elif not ran and h == 'REFUSE' and m != 'REFUSE': flag = 'NEW-REFUSE'
        elif ran and gated(h) and not gated(m): flag = 'FIXED'
        else: flag = 'ok'
        if ran and gated(h6) and not gated(h): f6 = 'R7-WEAKER'
        elif not ran and h == 'REFUSE' and h6 != 'REFUSE': f6 = 'R7-REFUSE-COST'
        elif ran and h == 'REFUSE' and not gated(h6): f6 = 'R7-REFUSE-FIX'
        else: f6 = 'same'
        main_raised = m == 'REFUSE'
        try:
            eq = main_raised == flat_refused(MOD['r7'], cmd)
        except Exception as e:
            eq = 'CRASH:' + type(e).__name__
        counts[flag] = counts.get(flag, 0) + 1
        counts6[f6] = counts6.get(f6, 0) + 1
        print(f'{flag:22s} {f6:15s} {name:34s} main={short(m)!s} r6={short(h6)!s} r7={short(h)!s} ' +
              ' '.join(f'{k}={short(v)!s}' for k, v in sh.items()) +
              f' flatEq={eq} t7={r["r7_t"]:.2f} cmd={cmd!r}', flush=True)
    print('COUNTS-vs-main', counts)
    print('COUNTS-vs-r6', counts6)
finally:
    shutil.rmtree(TMP)
