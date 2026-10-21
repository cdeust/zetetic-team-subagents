"""hooks/lib/gate_task.py in-process: the operator verbs `requeue --id` and `verify` (review round 5, B1, B2).

The hook-level behaviour (a requeue from another shell, the CI self-verification) is tested through the real
hooks in tests/test_stop_gate_ledger.py and by the CI job gate-self-verification; here each verb's branches are
called directly, so nothing waits.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from gate_support import git, write_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_task  # noqa: E402
import gate_trust  # noqa: E402

@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ZETETIC_TASKS_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(gate_trust.ENV_FILE, str(tmp_path / "trusted"))
    git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("one\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "init")
    return path


def test_requeue_needs_an_id_and_names_an_unknown_one(repo, capsys):
    with pytest.raises(SystemExit):
        gate_task.main(["requeue", "--repo", str(repo)])
    assert gate_task.main(["requeue", "--repo", str(repo), "--id", "gate-unknown"]) == 0
    assert "no gate task gate-unknown" in json.loads(capsys.readouterr().out)["error"]


def test_verify_needs_a_base_and_resolves_it(repo, capsys):
    with pytest.raises(SystemExit):
        gate_task.main(["verify", "--repo", str(repo)])
    assert gate_task.main(["verify", "--repo", str(repo), "--base", "no-such-rev"]) == 2
    assert gate_task.main(["verify", "--repo", str(repo), "--base", "-"]) == 0  # declares no gate: nothing to verify
    assert "declares no gate" in capsys.readouterr().out


def test_verify_refuses_an_unlisted_repository_and_runs_a_listed_one(repo, tmp_path, capsys):
    write_config(repo, [{"name": "ok", "argv": ["sh", "-c", "echo verified-in-the-foreground"]}])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")
    assert gate_task.main(["verify", "--repo", str(repo), "--base", "HEAD^"]) == 1
    assert "not in your trusted list" in capsys.readouterr().out
    (tmp_path / "trusted").write_text(os.path.realpath(repo) + "\n")
    assert gate_task.main(["verify", "--repo", str(repo), "--base", "HEAD^"]) == 0
    assert "verifying" in capsys.readouterr().out


def test_waive_still_needs_a_tree_and_a_reason(repo):
    with pytest.raises(SystemExit):
        gate_task.main(["waive", "--repo", str(repo), "--tree", "nothex", "--reason", "r"])
