"""Per-task cycle ledger: rows, checked declarations, the metric (tools/cycle_ledger.py)."""
from __future__ import annotations

import contextlib
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


def git_in(repo, *args, env=None) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit_file(repo, name: str, when: str = "") -> str:
    """Commit a new file ``name``; ``when`` (ISO-8601) fixes the commit dates."""
    (repo / name).write_text(name, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    git_in(repo, "add", name)
    git_in(repo, "commit", "-qm", name, env=env)
    return git_in(repo, "rev-parse", "HEAD")


@pytest.fixture
def origin(repo):
    """``repo`` cloned-like from github.com/o/r: origin/main (= origin/HEAD) holds the base commit."""
    git_in(repo, "remote", "add", "origin", "git@github.com:o/r.git")
    git_in(repo, "update-ref", "refs/remotes/origin/main", commit_file(repo, "base.py"))
    git_in(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return repo


def pushed_work(repo, task, when: str = "") -> str:
    """A commit of the task's work, dated when the task opened unless ``when``
    says otherwise, that origin/feature contains and origin/main does not. It
    changes a.py, the file ``gone_task`` first edited."""
    sha = commit_file(repo, "a.py", when or task["time"])
    git_in(repo, "update-ref", "refs/remotes/origin/feature", sha)
    return sha


def gone_task(path, tmp_path, **fields):
    gone = tmp_path / "worktrees" / "gone"
    return cl.open_task(path, opener(gone, **{"first_path": str(gone / "a.py"), **fields}))[0]


def test_a_task_whose_worktree_is_gone_closes_on_its_pr_and_pushed_commit(path, origin, tmp_path, capsys):
    task = gone_task(path, tmp_path)
    sha = pushed_work(origin, task)
    assert cl.main(["--cwd", str(origin), "close-disposed", task["open"], "--url", PR, "--sha", sha[:12]]) == 0
    assert f"closed {task['open']} as disposed" in capsys.readouterr().out
    rows = gates_jsonl.read_rows(path)
    assert cl.open_tasks(rows) == []
    assert rows[-1]["disposed"] == {"url": PR, "sha": sha}  # the abbreviation is recorded resolved
    assert cl.metrics(rows)["main"] == {"tasks": 0, "declared": 0, "proven": 0, "reopens": 0,
                                        "bypasses": 0, "disposed": 1, "promise_rate": None}


def test_the_next_task_of_the_reader_starts_after_a_disposed_close(path, origin, tmp_path):
    """A disposed close records where the reader's transcript ended, so the
    stage calls made for the disposed task are not counted for the next one;
    a subagent's end is read from its own agent-<id>.jsonl, not the parent's."""
    main_log = tmp_path / "proj" / "sess.jsonl"
    sub_log = tmp_path / "proj" / "sess" / "subagents" / "agent-ag1.jsonl"
    sub_log.parent.mkdir(parents=True)
    main_log.write_text("x" * 300)
    sub_log.write_text("y" * 70)
    main = gone_task(path, tmp_path, transcript_path=str(main_log))
    sub = gone_task(path, tmp_path, agent_id="ag1", transcript_path=str(main_log))
    sha = pushed_work(origin, sub)  # dated when the later of the two tasks opened
    for task in (main, sub):
        cl.close_disposed(str(origin), task["open"], PR, sha)
    after_main, _ = cl.open_task(path, opener(origin, transcript_path=str(main_log)))
    after_sub, _ = cl.open_task(path, opener(origin, agent_id="ag1", transcript_path=str(main_log)))
    assert (after_main["window_start"], after_sub["window_start"]) == (300, 70)


def test_worktree_gone_needs_both_recorded_absolute_paths_absent(tmp_path):
    present = tmp_path / "a.py"
    present.write_text("")
    gone = str(tmp_path / "gone")
    assert cl.worktree_gone({"repo": gone, "first_path": gone + "/a.py"})
    assert not cl.worktree_gone({"repo": str(tmp_path), "first_path": gone + "/a.py"})
    assert not cl.worktree_gone({"repo": gone, "first_path": str(present)})
    assert not cl.worktree_gone({"repo": None, "first_path": gone + "/a.py"})  # no repository: nothing proven
    assert not cl.worktree_gone({"first_path": gone + "/a.py"})
    assert not cl.worktree_gone({"repo": gone, "first_path": "a.py"})  # relative to an unrecorded cwd
    assert not cl.worktree_gone({"repo": gone})


REFUSALS = {  # case -> what the refusal names
    "worktree-exists": "not proven gone", "no-repo": "not proven gone", "relative-first-path": "not proven gone",
    "unknown-task": "no open task", "not-a-pr": "not a GitHub pull-request URL",
    "trailing-newline": "not a GitHub pull-request URL", "other-repo": "not a pull request of origin",
    "no-origin": "no GitHub origin remote", "unpushed": "no ref of origin contains",
    "base-commit-of-main": "committed before the task opened", "older-than-task": "committed before the task opened",
    "unrelated-pushed-commit": "does not change a.py", "unrelated-commit-on-main": "does not change a.py",
}


def _refusal_task(path, repo, tmp_path, case):
    if case == "worktree-exists":
        return cl.open_task(path, opener(repo, first_path=str(repo / "a.py")))[0]
    if case == "no-repo":
        return gone_task(path, tmp_path, repo=None)
    if case == "relative-first-path":
        return gone_task(path, tmp_path, first_path="a.py")
    return gone_task(path, tmp_path)


def _refusal_sha(repo, task, case):
    if case == "unpushed":
        return commit_file(repo, "a.py", task["time"])
    if case == "unrelated-pushed-commit":  # a sibling session's push: after the task opened, on origin, not its work
        sha = commit_file(repo, "sibling.py", task["time"])
        git_in(repo, "update-ref", "refs/remotes/origin/sibling", sha)
        return sha
    if case == "unrelated-commit-on-main":
        sha = commit_file(repo, "sibling.py", task["time"])
        git_in(repo, "update-ref", "refs/remotes/origin/main", sha)
        return sha
    if case == "base-commit-of-main":  # the base the task started from: it touches a.py but predates the task
        sha = commit_file(repo, "a.py", "2000-01-01T00:00:00+00:00")
        git_in(repo, "update-ref", "refs/remotes/origin/main", sha)
        return sha
    return pushed_work(repo, task, "2000-01-01T00:00:00+00:00" if case == "older-than-task" else "")


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_close_disposed_refuses_without_proof_bound_to_the_task_and_changes_nothing(path, origin, tmp_path,
                                                                                   case):
    task = _refusal_task(path, origin, tmp_path, case)
    sha = _refusal_sha(origin, task, case)
    if case == "no-origin":
        git_in(origin, "remote", "remove", "origin")
    url = {"not-a-pr": "https://github.com/o/r/issues/7", "trailing-newline": PR + "\n",
           "other-repo": "https://github.com/someone/else/pull/7"}.get(case, PR)
    before = gates_jsonl.read_rows(path)
    with pytest.raises(cl.DeclareRefused, match=REFUSALS[case]):
        cl.close_disposed(str(origin), "nope" if case == "unknown-task" else task["open"], url, sha)
    assert gates_jsonl.read_rows(path) == before


@pytest.mark.parametrize("raced", [False, True])
def test_close_disposed_runs_git_outside_the_lock_and_rereads_the_ledger_under_it(path, origin, tmp_path,
                                                                                  monkeypatch, raced):
    """Only ledger state is checked under the lock (git there would hold every
    hook's open or close behind it); a task another process closed after the
    git checks is refused, never closed twice."""
    task = gone_task(path, tmp_path)
    sha = pushed_work(origin, task)
    held = []
    real_git, real_locked = cl.git, cl.locked

    def git_unlocked(*args, **kwargs):
        assert not held, f"git {args[1:]} ran under the ledger lock"
        return real_git(*args, **kwargs)

    @contextlib.contextmanager
    def watched_lock(lock_path):
        with real_locked(lock_path):
            if raced:
                gates_jsonl.append_row(lock_path, {"close": task["open"], "evidence": {}, "counts": {}})
            held.append(True)
            try:
                yield
            finally:
                held.clear()
    monkeypatch.setattr(cl, "git", git_unlocked)
    monkeypatch.setattr(cl, "locked", watched_lock)
    if raced:
        with pytest.raises(cl.DeclareRefused, match="no open task"):
            cl.close_disposed(str(origin), task["open"], PR, sha)
    else:
        cl.close_disposed(str(origin), task["open"], PR, sha)
    closes = [r for r in gates_jsonl.read_rows(path) if r.get("close") == task["open"]]
    assert len(closes) == 1 and ("disposed" in closes[0]) is not raced


def test_a_task_closes_after_its_pr_was_squash_merged_and_the_branch_pruned(path, origin, tmp_path):
    """No origin branch holds the task's own commit any more; the squash commit
    on the default branch (it changes the task's file) is the proof."""
    task = gone_task(path, tmp_path)
    squash = commit_file(origin, "a.py", task["time"])
    git_in(origin, "update-ref", "refs/remotes/origin/main", squash)
    row = cl.close_disposed(str(origin), task["open"], PR, squash)
    assert row["disposed"] == {"url": PR, "sha": squash}
    assert cl.open_tasks(gates_jsonl.read_rows(path)) == []


@pytest.mark.parametrize("give", ["merge-commit", "feature-commit"])
def test_a_task_closes_after_a_merge_commit_put_its_work_in_the_default_branch(path, origin, tmp_path, give):
    task = gone_task(path, tmp_path)
    base = git_in(origin, "rev-parse", "HEAD")
    work = pushed_work(origin, task)
    git_in(origin, "checkout", "-q", "--detach", base)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": task["time"]}
    git_in(origin, "merge", "--no-ff", "-q", "-m", "merge", work, env=env)
    merge = git_in(origin, "rev-parse", "HEAD")
    git_in(origin, "update-ref", "refs/remotes/origin/main", merge)
    git_in(origin, "update-ref", "-d", "refs/remotes/origin/feature")  # the branch is deleted after the merge
    sha = merge if give == "merge-commit" else work
    assert cl.close_disposed(str(origin), task["open"], PR, sha)["disposed"]["sha"] == sha
