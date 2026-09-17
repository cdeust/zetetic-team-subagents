#!/usr/bin/env python3
"""Synchronize the standalone package with canonical full-plugin gates."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'plugins/zetetic-gates'
FILES = (
    'hooks/zetetic-gates.py', 'hooks/gates.json', 'hooks/gates-pre-commit.sh',
    'hooks/lib/host_events.py', 'hooks/lib/staged_checks.py',
    'hooks/lib/gate_targets.py', 'hooks/lib/git-command-cwd.py',
    'hooks/run-python.sh', 'hooks/pre-tool-secret-shield.py',
    'hooks/pre-tool-claim-gate.sh', 'hooks/pre-edit-layer-check.sh',
    'hooks/pre-tool-deletion-gate.py', 'hooks/post-tool-deletion-gate.py',
    'hooks/pre-tool-redaction-gate.py', 'hooks/stop-redaction-gate.py',
    'hooks/pre-push-fail-before.sh', 'hooks/git-push-context.py',
    'tools/fail-before-checker.sh', 'tools/fail-before-runners.sh',
    'tools/zetetic-checker.sh', 'tools/craftsmanship-checker.sh',
    'tools/lib/craftsmanship-detectors.sh', 'tools/redaction-checker.sh',
    'tools/redaction_gate.py', 'tools/deletion_gate.py',
    'tools/deletion_gate_git.py', 'tools/deletion_gate_lang.py',
    'rules/coding-standards.md', 'rules/gates-policy.md',
    'skills/writing/redaction.md',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    drift = []
    for relative in FILES:
        source, target = ROOT / relative, PACKAGE / relative
        if args.check:
            if not target.is_file() or source.read_bytes() != target.read_bytes():
                drift.append(relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    if drift:
        print('Gate package drift: ' + ', '.join(drift))
        return 1
    print('Gate package matches canonical sources.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
