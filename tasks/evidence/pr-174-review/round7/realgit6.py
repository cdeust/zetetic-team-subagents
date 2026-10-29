"""Real git (no shim) in a throwaway repo with a bare fake remote: does each shell really commit/push?
Prints the parse-check exit (sh -n) and the effect (commit count, remote refs) per shell.
Usage: python3 -I realgit6.py"""
import os, shutil, subprocess, tempfile

W = ": <<'Q'\nit's\nQ\n"
CASES = [
    ('P1 wrapped commit', W + 'cat =(echo a)#x; git commit -qm x'),
    ('P2 wrapped commit', W + '[[ a == (a|b)#x ]]; git commit -qm x'),
    ('P3 wrapped commit', W + 'case a in (a)#x) echo IN;; esac; git commit -qm x'),
    ('P5 wrapped push', W + 'cat =(echo a)#x; git push -q origin HEAD:refs/heads/pwned'),
    ('I1 wrapped commit', W + 'git status >/dev/null; x=git; y=comm; $x ${y}it -qm m'),
    ('I4 wrapped commit', W + 'git status >/dev/null; $(printf gi)t $(printf com)mit -qm m'),
    ('A3 wrapped commit', W + 'y=comm; git -c alias.c=${y}it c -qm x'),
    # Round 7 sibling probes (fixer): L1-L3 are lexable by origin/main.
    ('L1 -c alias.c=commit', 'git -c alias.c=commit c -qm x'),
    ('L2 -c alias quoted', "git -c alias.c='commit -qm x' c"),
    ('L3 zsh alias -g nl', 'alias -g c=commit\ngit c -qm x'),
    ('L3w alias -g wrapped', W + 'alias -g c=commit\ngit c -qm x'),
    ('I2 git only in data', ": <<'Q'\nit's git\nQ\nx=git; y=comm; $x ${y}it -qm m"),
]
T = tempfile.mkdtemp(prefix='rg6-')


def write(path, text):
    with open(path, 'w') as handle:
        handle.write(text)


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def argv(sh, cmd, check=False):
    if sh == 'czsh':
        q = "'" + cmd.replace("'", "'\\''") + "'"
        if check:
            return ['/bin/zsh', '-n', '-c', cmd]
        return ['/bin/zsh', '-c', 'setopt NO_EXTENDED_GLOB NO_BARE_GLOB_QUAL 2>/dev/null || true && eval ' + q + ' < /dev/null']
    return [sh, '-n', '-c', cmd] if check else [sh, '-c', cmd]


try:
    for name, cmd in CASES:
        for sh in ('bash', 'zsh', 'czsh'):
            repo, remote = os.path.join(T, 'r'), os.path.join(T, 'remote.git')
            shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(remote, ignore_errors=True)
            git('init', '-q', '--bare', remote); git('init', '-q', repo)
            for a in (('config', 'user.email', 't@t'), ('config', 'user.name', 't')):
                git(*a, cwd=repo)
            write(os.path.join(repo, 'f'), 'a\n'); git('add', 'f', cwd=repo); git('commit', '-qm', 'base', cwd=repo)
            git('remote', 'add', 'origin', remote, cwd=repo)
            write(os.path.join(repo, 'g'), 'b\n'); git('add', 'g', cwd=repo)
            pc = subprocess.run(argv(sh, cmd, True), cwd=repo, capture_output=True, stdin=subprocess.DEVNULL).returncode
            rc = subprocess.run(argv(sh, cmd), cwd=repo, capture_output=True, stdin=subprocess.DEVNULL, timeout=30).returncode
            commits = git('rev-list', '--count', 'HEAD', cwd=repo)
            refs = git('for-each-ref', '--format=%(refname)', cwd=remote).split()
            print(f'{name:20s} {sh:5s} parse(-n)={pc} run={rc} commits={commits} remote_refs={refs}', flush=True)
finally:
    shutil.rmtree(T)
