"""Per-task cycle ledger: rows, checked declarations, the metric (tools/cycle_ledger.py)."""
from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from cycle_support import CHECK, SESSION, git_repo
import cycle_ledger as cl
import gates_jsonl


def opener(repo, **fields):
    base = {"session_id": SESSION, "agent_id": None, "agent_type": "main",
            "transcript_path": "/t/main.jsonl", "repo": str(repo), "first_path": "a.py"}
    return {**base, **fields}


@pytest.fixture
def repo(tmp_path):
    return git_repo(tmp_path / "repo")


@pytest.fixture
def path(repo):
    return cl.ledger_path(str(repo))


def commit(repo) -> str:
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(repo), "add", "a.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True, env=env)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_task_repo_counts_new_files_and_skips_ignored_or_outside_files(repo, tmp_path):
    assert cl.task_repo(str(repo / "new" / "dir" / "file.py")) == str(repo.resolve())
    assert cl.task_repo(str(repo / "scratch" / "notes.md")) is None
    outside = tmp_path / "plain"
    outside.mkdir()
    assert cl.task_repo(str(outside / "x.py")) is None


def test_one_open_task_per_session_and_agent_in_an_owner_only_append_only_file(path, repo):
    first, created = cl.open_task(path, opener(repo))
    again, created_again = cl.open_task(path, opener(repo))
    sub, sub_created = cl.open_task(path, opener(repo, agent_id="ag1", agent_type="engineer"))
    other, other_created = cl.open_task(path, opener(repo, session_id="sess-other"))
    assert (created, created_again, sub_created, other_created) == (True, False, True, True)
    assert again["open"] == first["open"] and len({first["open"], sub["open"], other["open"]}) == 3
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert len(gates_jsonl.read_rows(path)) == 3


def test_an_open_without_a_session_never_adopts_another_sessions_task(path, repo):
    cl.open_task(path, opener(repo))
    _, created = cl.open_task(path, opener(repo, session_id=None))
    assert created


def test_a_new_task_starts_where_the_previous_task_of_the_same_transcript_closed(path, repo):
    first, _ = cl.open_task(path, opener(repo))
    cl.close(path, first["open"], {"evidence": {}, "counts": {}}, 1234)
    second, created = cl.open_task(path, opener(repo))
    fresh, _ = cl.open_task(path, opener(repo, session_id="s2", transcript_path="/t/other.jsonl"))
    assert created and second["window_start"] == 1234 and fresh["window_start"] == 0


def test_declarations_are_checked_and_the_latest_wins(path, repo):
    sha = commit(repo)
    task, _ = cl.open_task(path, opener(repo))
    tid = task["open"]
    cl.declare(str(repo), tid, "check", {"command": "pytest -q"})
    cl.declare(str(repo), tid, "check", {"command": CHECK})
    cl.declare(str(repo), tid, "refine", {"sha": sha[:10]})
    cl.declare(str(repo), tid, "benchmark", {"memory": 77})
    decls = cl.declarations(gates_jsonl.read_rows(path), tid)
    assert decls["check"]["ref"] == CHECK
    assert (decls["refine"]["kind"], decls["benchmark"]["ref"]) == ("sha", 77)


@pytest.mark.parametrize("case", [
    ("verify", {"command": "x"}, "proven by the transcript"),
    ("refine", {"sha": "deadbeef"}, "is not a commit"),
    ("refine", {"url": "https://example.com/pull/1"}, "not a GitHub"),
    ("refine", {"memory": 0}, "positive integer"),
    ("refine", {"memory": True}, "positive integer"),
    ("refine", {"n/a": "no spec"}, "accepts sha, url, memory"),
    ("check", {"sha": "abc1234"}, "accepts command"),
    ("benchmark", {"url": "https://github.com/o/r/pull/3", "memory": 4}, "exactly one"),
    ("benchmark", {}, "exactly one"),
])
def test_unchecked_declarations_are_refused_and_change_nothing(path, repo, case):
    stage, ref, message = case
    task, _ = cl.open_task(path, opener(repo))
    before = gates_jsonl.read_rows(path)
    with pytest.raises(cl.DeclareRefused, match=message):
        cl.declare(str(repo), task["open"], stage, ref)
    assert gates_jsonl.read_rows(path) == before


def test_a_closed_or_unknown_task_cannot_be_declared(path, repo):
    task, _ = cl.open_task(path, opener(repo))
    cl.close(path, task["open"], {"evidence": {}, "counts": {}}, 0)
    for tid in (task["open"], "nope"):
        with pytest.raises(cl.DeclareRefused, match="no open task"):
            cl.declare(str(repo), tid, "check", {"command": CHECK})


def test_metrics_give_the_promise_rate_reopens_and_bypasses_per_agent_type(path, repo):
    main, _ = cl.open_task(path, opener(repo))
    eng, _ = cl.open_task(path, opener(repo, agent_id="a", agent_type="engineer"))
    evidence = {s: {"source": "transcript"} for s in ("recall", "verify", "review")}
    cl.close(path, main["open"], {"evidence": {**evidence, "refine": {"source": "declaration"}},
                                  "counts": {"reopens": 2}}, 10)
    cl.record_bypass(path, eng, ["review"])
    out = cl.metrics(gates_jsonl.read_rows(path))
    assert out["main"] == {"tasks": 1, "declared": 1, "proven": 3, "reopens": 2, "bypasses": 0,
                           "promise_rate": 0.25}
    assert out["engineer"]["bypasses"] == 1 and out["engineer"]["promise_rate"] is None


def test_cli_lists_declares_and_measures(path, repo, capsys):
    task, _ = cl.open_task(path, opener(repo))
    assert cl.main(["--cwd", str(repo), "declare", task["open"], "--stage", "check", "--command", CHECK]) == 0
    assert cl.main(["--cwd", str(repo), "declare", task["open"], "--stage", "benchmark",
                    "--not-applicable", "docs only"]) == 0
    assert cl.main(["--cwd", str(repo), "list"]) == 0
    assert cl.main(["--cwd", str(repo), "metrics"]) == 0
    out = capsys.readouterr().out
    assert f"declared check of {task['open']}: command {CHECK}" in out
    assert task["open"] in out.splitlines()[2]
    assert json.loads(out[out.index("{"):]) == {}


def test_cli_refusals_exit_2_with_the_reason(repo, tmp_path, capsys):
    assert cl.main(["--cwd", str(repo), "declare", "nope", "--stage", "check", "--command", "x"]) == 2
    assert "no open task nope" in capsys.readouterr().err
    outside = tmp_path / "plain"
    outside.mkdir()
    assert cl.main(["--cwd", str(outside), "list"]) == 2
    assert "not inside a git repository" in capsys.readouterr().err
