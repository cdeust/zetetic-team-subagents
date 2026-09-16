"""Assert CLI diagnostics and deterministic runner failure paths."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def initialize(repo):
    for args in [('init', '-q'), ('config', 'user.name', 'test'),
                 ('config', 'user.email', 'test@example.invalid')]:
        subprocess.run(['git', *args], cwd=repo, check=True)


def main():
    gate = Path(sys.argv[1]).resolve()
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + ':' + os.environ['PATH'])
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        def run(args=(), env=None, code=0, text=''):
            result = subprocess.run([str(gate), *args], cwd=repo, env=env,
                                    text=True, capture_output=True)
            assert result.returncode == code, result
            assert text in result.stdout + result.stderr, result
        run(code=2, text='not a git repository')
        run(['--bad'], code=2, text='Usage')
        run(['--base'], code=2, text='Usage')
        initialize(repo)
        run(text='no commit yet')
        (repo / 'seed').write_text('base')
        subprocess.run(['git', 'add', 'seed'], cwd=repo, check=True)
        subprocess.run(['git', 'commit', '-qm', 'base'], cwd=repo, check=True)
        run(['--base', 'HEAD'], text='no changed test')
        (repo / '.zetetic.conf').write_text('ZETETIC_FAIL_BEFORE_TIMEOUT=bad\n')
        run(['--base', 'HEAD'], code=2, text='whole number')
        (repo / '.zetetic.conf').unlink()
        (repo / 'test_probe.py').write_text('def test_probe():\n    assert False\n')
        fake = repo / 'fake'
        fake.mkdir()
        (fake / 'timeout').write_text('#!/bin/sh\nexit 124\n')
        (fake / 'timeout').chmod(0o755)
        injected = dict(env, PATH=str(fake) + ':' + env['PATH'])
        run(['--base', 'HEAD'], injected, text='INCONCLUSIVE fail-before: the base-tree run exceeded')
        (fake / 'timeout').unlink()
        real_git = shutil.which('git')
        (fake / 'git').write_text('#!/bin/sh\nif [ "$1" = worktree ] && [ "$2" = add ]; then exit 1; fi\nexec ' + real_git + ' "$@"\n')
        (fake / 'git').chmod(0o755)
        run(['--base', 'HEAD'], injected, text='could not check out')
        assert len(subprocess.check_output(['git', 'worktree', 'list'], cwd=repo).splitlines()) == 1
        print('9 CLI/error-path assertions passed')


if __name__ == '__main__':
    main()
