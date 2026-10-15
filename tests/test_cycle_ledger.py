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


def opener(root, **fields):
    base = {"session_id": SESSION, "agent_id": None, "agent_type": "main",
            "transcript_path": "/t/main.jsonl", "repo": str(root), "first_path": "a.py"}
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
    cl.close(path, first["open"], {"evidence": {}, "counts": {}}, (1234, "/t/main.jsonl"))
    second, created = cl.open_task(path, opener(repo))
    fresh, _ = cl.open_task(path, opener(repo, session_id="s2", transcript_path="/t/other.jsonl"))
    assert created and second["window_start"] == 1234 and fresh["window_start"] == 0


def test_a_subagent_window_ignores_parent_closes_and_a_main_window_ignores_subagent_closes(path, repo):
    """A subagent's PostToolUse carries the PARENT transcript_path, so windows
    are keyed by agent_id for a subagent and by the scanned transcript for the
    main agent; the larger subagent end must not leak into the main window."""
    main, _ = cl.open_task(path, opener(repo))
    cl.close(path, main["open"], {"evidence": {}, "counts": {}}, (1234, "/t/main.jsonl"))
    sub, _ = cl.open_task(path, opener(repo, agent_id="ag1", agent_type="engineer"))
    assert sub["window_start"] == 0
    cl.close(path, sub["open"], {"evidence": {}, "counts": {}}, (5000, "/t/main/subagents/agent-ag1.jsonl"))
    resumed, _ = cl.open_task(path, opener(repo, agent_id="ag1", agent_type="engineer"))
    later_main, _ = cl.open_task(path, opener(repo))
    assert (resumed["window_start"], later_main["window_start"]) == (5000, 1234)


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
    cl.close(path, task["open"], {"evidence": {}, "counts": {}}, (0, "/t/main.jsonl"))
    for tid in (task["open"], "nope"):
        with pytest.raises(cl.DeclareRefused, match="no open task"):
            cl.declare(str(repo), tid, "check", {"command": CHECK})


def test_metrics_give_the_promise_rate_reopens_and_bypasses_per_agent_type(path, repo):
    main, _ = cl.open_task(path, opener(repo))
    eng, _ = cl.open_task(path, opener(repo, agent_id="a", agent_type="engineer"))
    evidence = {s: {"source": "transcript"} for s in ("recall", "verify", "review")}
    cl.close(path, main["open"], {"evidence": {**evidence, "refine": {"source": "declaration"}},
                                  "counts": {"reopens": 2}}, (10, "/t/main.jsonl"))
    cl.close(path, eng["open"], {"evidence": evidence, "missing": ["review"], "counts": {"reopens": 1}},
             (20, "/t/eng.jsonl"))
    out = cl.metrics(gates_jsonl.read_rows(path))
    assert out["main"] == {"tasks": 1, "declared": 1, "proven": 3, "reopens": 2, "bypasses": 0,
                           "disposed": 0, "promise_rate": 0.25}
    assert out["engineer"] == {"tasks": 0, "declared": 0, "proven": 0, "reopens": 0, "bypasses": 1,
                               "disposed": 0, "promise_rate": None}  # a bypass proved nothing
    assert cl.open_tasks(gates_jsonl.read_rows(path)) == []  # and it closed the task


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


def test_task_repo_stops_at_the_root_when_no_ancestor_exists(monkeypatch):
    monkeypatch.setattr(cl.os.path, "isdir", lambda _: False)
    assert cl.task_repo("/no/such/dir/a.py") is None


def test_a_check_ignore_failure_is_a_ledger_error_not_a_task_file(repo, monkeypatch):
    real = cl.git

    def broken(cwd, *args, **kw):
        if args[0] == "check-ignore":
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(cl, "git", broken)
    with pytest.raises(gates_jsonl.LedgerError, match="exit 128"):
        cl.task_repo(str(repo / "a.py"))


def test_task_repos_classifies_many_paths_with_one_check_ignore_per_work_tree(repo, tmp_path, monkeypatch):
    other = git_repo(tmp_path / "other")
    calls = []
    real = cl.git
    monkeypatch.setattr(cl, "git", lambda cwd, *a, **kw: calls.append(a[0]) or real(cwd, *a, **kw))
    paths = [str(repo / "a.py"), str(repo / "b.py"), str(repo / "scratch" / "n.md"), str(other / "c.py"),
             str(tmp_path / "plain.py")]
    out = cl.task_repos(paths)
    assert [out[p] for p in paths] == [str(repo.resolve())] * 2 + [None, str(other.resolve()), None]
    assert calls.count("check-ignore") == 2 and calls.count("rev-parse") == 4  # 4 distinct directories


def test_a_lock_held_past_its_timeout_still_opens_the_task(path, repo, monkeypatch):
    import fcntl
    monkeypatch.setattr(gates_jsonl, "LOCK_TIMEOUT_S", 0.2)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as holder:  # another hook process holds the lock
        fcntl.flock(holder, fcntl.LOCK_EX)
        task, created = cl.open_task(path, opener(repo))
    assert created and "still held" in task["lock_timeout"]
    assert cl.open_tasks(gates_jsonl.read_rows(path)) == [task]
    assert not cl.open_task(path, opener(repo))[1]  # released: the next edit reuses it


def test_parallel_opens_of_one_agent_record_a_single_task(path, repo):
    import threading
    barrier = threading.Barrier(8)
    results = []

    def opener_thread():
        barrier.wait()
        results.append(cl.open_task(path, opener(repo)))
    threads = [threading.Thread(target=opener_thread) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(created for _, created in results) == 1
    assert len([r for r in gates_jsonl.read_rows(path) if "open" in r]) == 1


PR = "https://github.com/o/r/pull/7"


def pushed_commit(repo) -> str:
    """A commit that the remote-tracking branch origin/main contains."""
    sha = commit(repo)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", sha], check=True)
    return sha


def test_a_task_whose_worktree_is_gone_closes_on_its_pr_and_pushed_commit(path, repo, tmp_path, capsys):
    sha = pushed_commit(repo)
    gone = tmp_path / "worktrees" / "gone"
    task, _ = cl.open_task(path, opener(gone, first_path=str(gone / "a.py")))
    assert cl.main(["--cwd", str(repo), "close-disposed", task["open"], "--url", PR, "--sha", sha]) == 0
    assert f"closed {task['open']} as disposed" in capsys.readouterr().out
    rows = gates_jsonl.read_rows(path)
    assert cl.open_tasks(rows) == []
    assert rows[-1]["disposed"] == {"url": PR, "sha": sha}
    assert cl.metrics(rows)["main"] == {"tasks": 0, "declared": 0, "proven": 0, "reopens": 0,
                                        "bypasses": 0, "disposed": 1, "promise_rate": None}


@pytest.mark.parametrize("case", ["worktree-exists", "not-a-pr", "unpushed", "unknown-task"])
def test_close_disposed_refuses_without_proof_and_changes_nothing(path, repo, tmp_path, case):
    sha = commit(repo) if case == "unpushed" else pushed_commit(repo)
    where = repo if case == "worktree-exists" else tmp_path / "gone"
    task, _ = cl.open_task(path, opener(where))
    tid = "nope" if case == "unknown-task" else task["open"]
    url = "https://github.com/o/r/issues/7" if case == "not-a-pr" else PR
    before = gates_jsonl.read_rows(path)
    with pytest.raises(cl.DeclareRefused):
        cl.close_disposed(str(repo), tid, url, sha)
    assert gates_jsonl.read_rows(path) == before
