"""Consumer scheduling policy preserves every native review completion path."""

from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
CODEX = Path('.github/workflows/Codex.yml')
SCHEDULE = '''  # Supported fallback: review-thread resolution has no Actions event.
  # GitHub documents five minutes as the shortest schedule interval.
  schedule:
    - cron: "*/5 * * * *"
'''


def test_no_schedule_changes_only_codex_schedule(tmp_path):
    default = renderer.prepare_files(tmp_path, native_review=True)
    files = renderer.prepare_files(tmp_path, native_review=True, no_schedule=True)
    assert files.keys() == default.keys()
    for path, data in default.items():
        expected = data.replace(SCHEDULE.encode(), b'') if path == tmp_path / CODEX else data
        assert files[path] == expected
    original = yaml.safe_load(default[tmp_path / CODEX])
    opted_out = yaml.safe_load(files[tmp_path / CODEX])
    assert set(opted_out[True]) == {'issue_comment', 'workflow_run', 'workflow_dispatch'}
    del original[True]['schedule']
    assert opted_out == original


def test_no_schedule_requires_native_profile_before_writes(tmp_path):
    with pytest.raises(ValueError, match='requires --native-review'):
        renderer.prepare_files(tmp_path, no_schedule=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('native', [False, True])
def test_cli_no_schedule_profile_and_dry_run(tmp_path, native):
    args = [sys.executable, str(ROOT / 'scripts/lib/render_ci.py'), str(tmp_path), '--no-schedule']
    if native:
        args.extend(['--native-review', '--dry-run'])
    result = subprocess.run(args, capture_output=True, text=True)
    if native:
        assert result.returncode == 0, result.stderr
        assert 'Would write:' in result.stdout
    else:
        assert result.returncode == 2
        assert '--no-schedule requires --native-review' in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_native_no_schedule_cli_delivery(tmp_path):
    result = subprocess.run(
        ['bash', str(ROOT / 'scripts/setup.sh'), 'render-ci', str(tmp_path), '--native-review', '--no-schedule'],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'schedule' not in yaml.safe_load((tmp_path / CODEX).read_bytes())[True]
    renderer.deliver(renderer.prepare_files(tmp_path, native_review=True))
    assert (tmp_path / CODEX).read_bytes() == (ROOT / 'templates/ci/native/assets' / CODEX).read_bytes()


def test_no_schedule_rejects_changed_canonical_trigger(tmp_path):
    asset = tmp_path / 'Codex.yml'
    asset.write_text('on:\n  workflow_dispatch:\n')
    with pytest.raises(ValueError, match='Canonical template changed'):
        renderer.native_asset(asset, no_schedule=True)
