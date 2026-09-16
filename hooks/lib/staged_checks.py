#!/usr/bin/env python3
"""Run bundled file checkers on frozen index blobs, without changing the checkout.

Git's ls-files --stage object IDs and cat-file preserve the index preimage.
Checker selection/config semantics come from craftsmanship-checker.sh and
redaction-checker.sh; --files applies their existing path filters.
"""
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

CONFIGS = ('.craftsmanship.conf', '.claude/craftsmanship.conf', '.zetetic.conf')
REGULAR_MODES = {'100644', '100755'}  # gitformat-index: regular file modes.


def environment():
    """Do not let the caller's Git directory/index override the disposable repo."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    env.setdefault('ZETETIC_PROFILE', 'strict')
    return env


def git(repo, args, env):
    result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                            capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace').strip())
    return result.stdout


def _entries(raw):
    entries = {}
    for record in raw.split(b'\0'):
        if not record:
            continue
        metadata, raw_path = record.split(b'\t', 1)
        mode, oid, stage = metadata.decode('ascii').split()
        if stage != '0':
            raise ValueError('Unmerged index cannot be checked')
        path = os.fsdecode(raw_path)
        parts = PurePosixPath(path).parts
        if not parts or '..' in parts or '.git' in parts or path.startswith('/'):
            raise ValueError(f'Unsafe index path: {path!r}')
        entries[path] = (mode, oid)
    return entries


def freeze(repo, env):
    """Capture stable paths/object IDs; concurrent index edits require a retry."""
    before = git(repo, ['ls-files', '--stage', '-z'], env)
    head = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', 'HEAD'],
                          env=env, capture_output=True)
    ref = [head.stdout.decode().strip()] if head.returncode == 0 else []
    changed = git(repo, ['diff', '--cached', '--name-only', '-z', '--diff-filter=ACMR',
                         *ref, '--'], env)
    after = git(repo, ['ls-files', '--stage', '-z'], env)
    if before != after:
        raise ValueError('Index changed during snapshot; rerun the gate')
    return _entries(before), [os.fsdecode(p) for p in changed.split(b'\0') if p]


def _materialize(repo, snapshot, selection, env):
    entries, changed = selection
    for name in dict.fromkeys([*changed, *CONFIGS]):
        if name not in entries:
            continue
        mode, oid = entries[name]
        if mode not in REGULAR_MODES:
            if name in CONFIGS:
                raise ValueError(f'Nonregular project config refused: {name}')
            kind = 'symlink' if mode == '120000' else 'gitlink'
            print(f'Skipping {kind} index entry without dereferencing: {name}')
            continue
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git(repo, ['cat-file', 'blob', oid], env))
        path.chmod(0o755 if mode == '100755' else 0o644)
    return [name for name in changed if entries.get(name, ('',))[0] in REGULAR_MODES]


def _check(plugin, snapshot, names, env):
    if not names:
        return 0
    status = 0
    for script in ('craftsmanship-checker.sh', 'redaction-checker.sh'):
        path = plugin / 'tools' / script
        if not path.is_file():
            raise ValueError(f'Missing checker: {path}')
        result = subprocess.run(['bash', str(path), '--files', *names], cwd=snapshot,
                                env=env, check=False)
        if result.returncode not in (0, 1):
            status = 2
        elif result.returncode:
            status = max(status, 1)
    return status


def check_staged(plugin, repo):
    env = environment()
    repo = Path(git(repo, ['rev-parse', '--show-toplevel'], env).decode().strip())
    selection = freeze(repo, env)
    with tempfile.TemporaryDirectory(prefix='zetetic-index-') as directory:
        snapshot = Path(directory)
        git(snapshot, ['init', '-q', '--template='], env)
        names = _materialize(repo, snapshot, selection, env)
        return _check(plugin, snapshot, names, env)


def main():
    try:
        if len(sys.argv) != 3:
            raise ValueError('usage: staged_checks.py PLUGIN_ROOT TARGET_REPO')
        return check_staged(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except (OSError, ValueError) as exc:
        print(f'Staged checks: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
