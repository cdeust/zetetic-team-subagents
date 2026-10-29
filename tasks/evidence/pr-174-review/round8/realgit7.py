"""Round-7: real git (no shim), throwaway repo + bare fake remote: does each shell really commit/push?
Prints the parse-check exit (sh -n) and the effect (commit count, remote refs) per shell.
Usage: python3 -I realgit7.py"""
import os, shutil, subprocess, tempfile

W = ": <<'Q'\nit's\nQ\n"
CASES = [
    ('S10 [[ <->#x ]]', W + '[[ 5 == <->#x ]]; git commit -qm x'),
    ('S12 [[ (b|#x) ]]', W + '[[ a == (b|#x) ]]; git commit -qm x'),
    ('S13 case (b|#x)', W + 'case a in (b|#x) echo IN;; esac; git commit -qm x'),
    ('S17 [[ (b| #x) ]]', W + '[[ a == (b| #x) ]]; git commit -qm x'),
    ('S21 x=<->#x push', W + 'x=<->#x; git push -q origin HEAD:refs/heads/pwned'),
    ('S22 delimiter git', W + "cat <<git\n$(x=gi; ${x}t commit -qm m)\ngit"),
    ('Z1 rewrite over cap', W + 'git status >/dev/null; ' + '\n' * 45000 + 'x=git; y=comm; $x ${y}it -qm m'),
]
T = tempfile.mkdtemp(prefix='rg7-')


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
            with open(os.path.join(repo, 'f'), 'w') as fh:
                fh.write('a\n')
            git('add', 'f', cwd=repo); git('commit', '-qm', 'base', cwd=repo)
            git('remote', 'add', 'origin', remote, cwd=repo)
            with open(os.path.join(repo, 'g'), 'w') as fh:
                fh.write('b\n')
            git('add', 'g', cwd=repo)
            pc = subprocess.run(argv(sh, cmd, True), cwd=repo, capture_output=True, stdin=subprocess.DEVNULL).returncode
            rc = subprocess.run(argv(sh, cmd), cwd=repo, capture_output=True, stdin=subprocess.DEVNULL, timeout=60).returncode
            commits = git('rev-list', '--count', 'HEAD', cwd=repo)
            refs = git('for-each-ref', '--format=%(refname)', cwd=remote).split()
            print(f'{name:20s} {sh:5s} parse(-n)={pc} run={rc} commits={commits} remote_refs={refs}', flush=True)
finally:
    shutil.rmtree(T)
