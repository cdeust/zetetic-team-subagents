"""hooks/lib/gate_ledger.py: the Stop hook's todo. In-process; the state directory and the repository are the test's own."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from gate_support import git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_ledger as ledger  # noqa: E402

A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ZETETIC_TASKS_DIR", str(tmp_path / "state"))
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n")
    git(path, "add", "a")
    git(path, "commit", "-q", "-m", "c")
    return path


def lines(repo: Path, name: str = ledger.RESULTS) -> list:
    return [json.loads(line) for line in Path(ledger._results_path(str(repo)).replace(ledger.RESULTS, name)).read_text().splitlines()]


def test_a_result_is_one_json_line_with_verb_tree_key_rc_and_a_description_time(repo):
    ledger.record(str(repo), ledger.Result("commit", A, f"commit-{A}-x", 3))
    ledger.record(str(repo), ledger.Result("push", B, f"push-{B}-x", 0))
    first, second = lines(repo)
    assert (first["verb"], first["tree"], first["key"], first["rc"]) == ("commit", A, f"commit-{A}-x", 3)
    assert (second["verb"], second["rc"]) == ("push", 0) and first["time"].endswith("Z")


def test_a_green_line_lifts_only_the_earlier_failures_of_its_own_verb(repo):
    for verb, tree, rc in (("commit", A, 1), ("push", B, 1), ("commit", C, 0), ("commit", D, 2)):
        ledger.record(str(repo), ledger.Result(verb, tree, f"{verb}-{tree}", rc))
    assert [(r["verb"], r["tree"]) for r in ledger.open_failures(str(repo))] == [("push", B), ("commit", D)]


def test_a_failure_after_the_green_line_is_open_and_a_green_after_all_lifts_everything(repo):
    ledger.record(str(repo), ledger.Result("commit", A, "k1", 0))
    ledger.record(str(repo), ledger.Result("commit", B, "k2", 1))
    assert [r["tree"] for r in ledger.open_failures(str(repo))] == [B]
    ledger.record(str(repo), ledger.Result("commit", C, "k3", 0))
    assert ledger.open_failures(str(repo)) == []


def test_a_waiver_lifts_its_tree_only_and_survives_torn_lines(repo):
    ledger.record(str(repo), ledger.Result("commit", A, "k1", 1))
    ledger.record(str(repo), ledger.Result("commit", B, "k2", 1))
    ledger.waive(str(repo), A, "upstream check is broken")
    with open(ledger._waiver_path(str(repo)), "a") as fh:
        fh.write("{torn\n[1]\n" + json.dumps({"tree": 5}) + "\n")
    ledger.record(str(repo), ledger.Result("push", C, "k3", 1))
    assert [r["tree"] for r in ledger.open_failures(str(repo))] == [B, C]
    assert ledger.waived_trees(str(repo)) == {A}


def test_foreign_and_malformed_result_lines_are_skipped_not_fatal(repo):
    path = ledger._results_path(str(repo))
    with open(path, "w") as fh:
        fh.write("not json\n[1]\n" + json.dumps({"verb": 1, "tree": A, "rc": 1}) + "\n" + json.dumps({"verb": "commit", "rc": 1}) + "\n")
        fh.write(json.dumps({"verb": "commit", "tree": B, "rc": True}) + "\n")  # True is not a pass: not rc == 0
    assert [r["tree"] for r in ledger.open_failures(str(repo))] == [B]
    ledger.record(str(repo), ledger.Result("commit", C, "k", 0))
    assert ledger.open_failures(str(repo)) == []


def test_no_ledger_yet_is_no_failure(repo):
    assert ledger.open_failures(str(repo)) == [] and ledger.waived_trees(str(repo)) == set()


def test_work_is_at_risk_while_tracked_changes_remain_staged_or_not(repo):
    assert ledger.work_at_risk(str(repo)) is False
    (repo / "a").write_text("edited\n")
    assert ledger.work_at_risk(str(repo)) is True  # an unstaged edit
    git(repo, "add", "a")
    assert ledger.work_at_risk(str(repo)) is True  # the same edit staged
    git(repo, "restore", "--staged", "--worktree", "a")
    assert ledger.work_at_risk(str(repo)) is False
    (repo / "untracked").write_text("x\n")
    assert ledger.work_at_risk(str(repo)) is False  # untracked files are not commit risk


def test_a_touched_but_unchanged_file_is_not_a_change(repo):
    (repo / "a").write_text("1\n")  # same bytes, new mtime: stale stat data, no content change
    os.utime(repo / "a", (1, 1))
    assert ledger.work_at_risk(str(repo)) is False


def test_work_is_at_risk_while_head_is_ahead_of_its_upstream(repo, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    assert ledger.work_at_risk(str(repo)) is False
    git(repo, "commit", "-q", "--allow-empty", "-m", "ahead")
    assert ledger.work_at_risk(str(repo)) is True


def test_before_the_first_commit_only_a_staged_index_is_at_risk(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETETIC_TASKS_DIR", str(tmp_path / "state"))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    assert ledger.work_at_risk(str(fresh)) is False
    (fresh / "x").write_text("1\n")
    git(fresh, "add", "x")
    assert ledger.work_at_risk(str(fresh)) is True


def test_a_waiver_returns_the_row_it_appended(repo):
    row = ledger.waive(str(repo), A, "because")
    assert (row["tree"], row["reason"]) == (A, "because") and row["time"].endswith("Z")
    assert lines(repo, ledger.WAIVERS) == [row]
