"""Round-7 three-way end-to-end PreToolUse run of hooks/zetetic-gates.py at origin/main, 3aaeed4 and
888312b (each from `git archive` of REPO). Two consumers: `dirty` (strict profile, a staged
MAGIC_NUMBER violation: a gated commit is BLOCKED) and `clean` (strict profile, a clean staged file:
a gated commit passes). Exit 2 is split into REFUSED ("Cannot inspect ..." / "origin/main refused")
and BLOCKED (a gate ran and failed). Each case also runs under bash, zsh and czsh with a git shim.
Usage: [CONSUMERS=dirty,clean] python3 -I e2e7.py REPO cases.py"""
import json, os, re, subprocess, sys, shutil, tempfile
REPO = sys.argv[1]
# Round 8 (fixer): the columns r6 and r7 are the previous and the new head.
# e2e7.py was split into functions after the runs (nesting limit); its only
# output change is "bash=-" for "bash=" when no git ran.
# PREV (default 888312b, the round-7 head) and NEW (default WORKTREE = REPO's
# working tree) select them, so one script gives before (NEW=888312b,
# PREV=3aaeed4) and after (PREV=888312b, NEW=WORKTREE).
REVS = (('main', 'origin/main'), ('r6', os.environ.get('PREV', '888312bd488599ba6a569d137beb10355bebb39e')),
        ('r7', os.environ.get('NEW', 'WORKTREE')))
LITERAL = '2.741592'  # source: an unsourced literal the strict gate must block
CONSUMERS = os.environ.get('CONSUMERS', 'dirty,clean').split(',')
T = os.path.realpath(tempfile.mkdtemp(prefix='r174e7-'))
SHIM = os.path.join(T, 'shim')
CONSUMER = os.path.join(T, 'consumer')
WRAPS = {'none': ('', ''), 'pre': (": <<'Q'\nit's\nQ\n", ''), 'suf': ('', "\n: <<'Q'\nit's\nQ"),
         'ansi': ("echo $'\\''\n", '')}


def extract_roots():
    roots = {}
    for label, rev in REVS:
        if rev == 'WORKTREE':
            roots[label] = REPO
            continue
        d = os.path.join(T, label)
        os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev], cwd=REPO, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        roots[label] = d
    return roots


def make_shim():
    os.makedirs(SHIM, mode=0o700)
    fd = os.open(SHIM + '/git', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, 'w') as f:
        f.write('#!/bin/sh\nd=$PWD\nif [ "$1" = -C ]; then d=$(cd "$2" && pwd -P); shift 2; fi\necho "SHIM-GIT $d $1" >&2\n')


def shell_argv(sh, cmd):
    if sh != 'czsh':
        return [sh, '-c', cmd]
    q = "'" + cmd.replace("'", "'\\''") + "'"
    return ['/bin/zsh', '-c', 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL 2>/dev/null || true && eval ' + q + ' < /dev/null']


def shell_runs(sh, cmd):
    shutil.rmtree(CONSUMER, ignore_errors=True)
    os.makedirs(CONSUMER)
    env = dict(os.environ, PATH=SHIM + ':' + os.environ['PATH'], LC_ALL='C')
    try:
        p = subprocess.run(shell_argv(sh, cmd), cwd=CONSUMER, env=env, capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f'{sh}=TIMEOUT'
    got = sorted(set(v for _d, v in re.findall(r'SHIM-GIT (\S+) (commit|push)\b', p.stderr)))
    return f'{sh}={",".join(got) or "-"}'


def write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def hook_exit(root, consumer, cmd):
    shutil.rmtree(CONSUMER, ignore_errors=True)
    subprocess.run(['git', 'init', '-q', CONSUMER], check=True)
    write(CONSUMER + '/.zetetic.conf', 'ZETETIC_PROFILE=strict\n')
    write(CONSUMER + '/sample.py', 'DELAY = ' + LITERAL + '\n' if consumer == 'dirty' else 'x = 1\n')
    subprocess.run(['git', 'add', '.'], cwd=CONSUMER, check=True)
    ev = {'hook_event_name': 'PreToolUse', 'cwd': CONSUMER, 'tool_name': 'Bash', 'tool_input': {'command': cmd}}
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ZETETIC_', 'CLAUDE_', 'REDACTION_'))}
    r = subprocess.run([sys.executable, root + '/hooks/zetetic-gates.py'], input=json.dumps(ev), text=True,
                       capture_output=True, cwd=CONSUMER, env=env, timeout=300)
    out = r.stderr + r.stdout
    refused = re.search(r'Cannot inspect|origin/main refused|cannot be read|unexpected', out)
    kind = 'REFUSED' if refused else 'BLOCKED' if r.returncode == 2 else 'pass'
    return f'{r.returncode}:{kind}'


def main():
    roots = extract_roots()
    make_shim()
    clean = os.path.join(T, 'cleanrepo')
    subprocess.run(['git', 'init', '-q', clean], check=True)
    ns = {'cases': []}
    with open(sys.argv[2]) as fh:
        exec(fh.read(), ns)  # local, reviewer-written case file only
    wrap = os.environ.get('WRAP', 'none')
    pre, suf = WRAPS[wrap]
    for name, cmd in ns['cases']:
        cmd = pre + cmd.replace('{CLEAN}', clean) + suf
        ran = ' '.join(shell_runs(sh, cmd) for sh in ('bash', 'zsh', 'czsh'))
        print(f'{name:34s} WRAP={wrap} runs: {ran}  len={len(cmd)}', flush=True)
        for consumer in CONSUMERS:
            row = ' '.join(f'{label}={hook_exit(root, consumer, cmd)}' for label, root in roots.items())
            print(f'    {consumer:5s} ' + row, flush=True)


try:
    main()
finally:
    shutil.rmtree(T)
