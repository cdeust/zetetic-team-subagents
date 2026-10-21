"""Compare git_commands of origin/main, e67eaf3 and the worktree against real
bash (and zsh) with a git shim. Usage: python3 cmp.py cases.py
Each version's hooks/lib is extracted from git into a temp dir removed at exit."""
import importlib.util, os, re, shutil, subprocess, sys, tempfile
WT = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                    cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
TMP = tempfile.mkdtemp(prefix='pr174r2-')
try:
    def extract(rev):
        d = os.path.join(TMP, rev.replace('/', '_'))
        os.makedirs(d)
        a = subprocess.run(['git', 'archive', rev, 'hooks/lib'], cwd=WT, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', d], input=a, check=True)
        return d + '/hooks/lib'
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path + '/gate_targets.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    mods = {'main': load('gt_main', extract('origin/main')),
            'e67': load('gt_e67', extract('e67eaf3')),
            'new': load('gt_new', WT + '/hooks/lib')}
    shim, run = os.path.join(TMP, 'shim'), os.path.join(TMP, 'run')
    os.makedirs(shim); os.makedirs(run)
    with open(shim + '/git', 'w') as f:
        f.write('#!/bin/sh\necho "SHIM-GIT $1"\n')
    os.chmod(shim + '/git', 0o700)  # owner-only: the shells run as this user
    def res(mod, cmd):
        try:
            return sorted(v for _d, v in mod.git_commands(cmd, '/tmp/base'))
        except ValueError:
            return 'REFUSE'
    def shell(sh, cmd):
        env = dict(os.environ, PATH=shim + ':' + os.environ['PATH'], LC_ALL='C')
        p = subprocess.run([sh, '-c', cmd], cwd=run, env=env, capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
        out = re.findall(r'SHIM-GIT (\w+)', p.stdout + p.stderr)
        return sorted(x for x in out if x in ('commit', 'push'))
    cases = []
    with open(sys.argv[1]) as f:
        exec(f.read())
    bad = 0
    for name, cmd in cases:
        r = {k: res(m, cmd) for k, m in mods.items()}
        b, z = shell('bash', cmd), shell('zsh', cmd)
        new = r['new']
        if b and new != 'REFUSE' and not set(b) <= set(new):
            flag = 'FAIL-OPEN'; bad += 1
        elif not b and new == 'REFUSE' and r['main'] != 'REFUSE':
            flag = 'NEW-REFUSE'
        elif not b and new not in ('REFUSE', []):
            flag = 'EXTRA'
        else:
            flag = 'ok'
        print(f'{flag:10s} {name:28s} main={r["main"]!s:12s} e67={r["e67"]!s:12s} new={new!s:12s} bash={b!s:12s} zsh={z!s:12s} cmd={cmd!r}')
    print('new FAIL-OPEN vs bash:', bad)
finally:
    shutil.rmtree(TMP)
