"""hooks/lib/gate_state.py and gate_git.py: the verdict is a function of the task record, nothing else.

In-process, synthetic records: no worker is started and nothing waits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gate_support import git
from task_support import tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_git as gitq  # noqa: E402
import gate_rules as rules  # noqa: E402
import gate_runner as runner_mod  # noqa: E402
import gate_state as state  # noqa: E402

TREE = "a" * 40
DIGEST = "d" * 12
TRUSTED = "e" * 40
RULES = rules.Rules(TRUSTED, [rules.RuleSet("config", {"version": 1, "checks": []}, None)], DIGEST)
RUNNER = runner_mod.Runner({}, None, "c" * 12)
KEY = f"commit-{TREE}-{DIGEST}-{RUNNER.digest}"  # verb, tree, rules digest, runner digest


def plan(verb: str = "commit", base: str | None = "b" * 40) -> state.Plan:
    return state.Plan("/repo", verb, TREE, base, RULES, RUNNER)


def record(**over) -> dict:
    base = {"id": plan().id, "key": plan().key, "state": "done", "rc": 0, "signal": None, "reason": None,
            "attempt": 1, "output_path": "/o/gate.a1.out", "result_excerpt": "line1\nthe failing line\n", "pgid": 7}
    return {**base, **over}


def judge(disposition: str, **over):
    return state.verdict_of(plan(), tasks.Started(record(**over), disposition))


def test_cached_green_allows():
    assert judge("cached") == state.Verdict(True, "")


def test_failed_denies_with_cause_output_path_tail_and_the_requeue_command():
    verdict = judge("failed", state="failed", rc=3)
    assert verdict.allow is False
    for part in (f"tree {TREE}", "commit; rc=3", "/o/gate.a1.out", "the failing line", "gate_task.py requeue --repo /repo --id gate-"):
        assert part in verdict.message
    assert "signal 9" in judge("failed", state="failed", rc=-9, signal=9).message
    assert "worker died" in judge("failed", state="failed", rc=None, reason="worker died").message


@pytest.mark.parametrize("disposition,word", [("started", "started"), ("in-flight", "running")])
def test_pending_denies_with_the_retry_message_and_the_status_command(disposition, word):
    verdict = judge(disposition, state="running", rc=None)
    assert verdict.allow is False
    assert f"verification {word} for tree {TREE}; retry the commit when it finishes" in verdict.message
    assert f"tools/task.sh status gate-{KEY} --repo /repo" in verdict.message


def test_the_retry_message_names_the_verb():
    started = tasks.Started(record(state="running"), "in-flight")
    assert "retry the push when it finishes" in state.verdict_of(plan("push"), started).message


def test_the_tail_is_bounded():
    long = "\n".join(f"row{i}" for i in range(100))
    message = judge("failed", state="failed", rc=1, result_excerpt=long).message
    assert "row99" in message and "row88" in message and "row87" not in message  # exactly the last 12 lines


def test_stale_requeues_once_and_orphaned_says_so(monkeypatch):
    calls = []

    def fake_requeue(kind, key, argv, cwd):
        calls.append((kind, key, argv, cwd))
        return tasks.Started(record(attempt=2, state="queued"), "started")

    monkeypatch.setattr(state.tasks, "requeue", fake_requeue)
    verdict = judge("stale", state="running")
    assert calls == [("gate", KEY, plan().argv, "/repo")]
    assert "attempt 2" in verdict.message and "previous worker died" in verdict.message and not verdict.allow
    assert f"verification started for tree {TREE}" in verdict.message  # a fresh attempt has just been launched
    monkeypatch.setattr(state.tasks, "requeue", lambda *a: tasks.Started(record(state="failed"), "orphaned"))
    orphan = judge("stale", state="running")
    assert "process group 7" in orphan.message and "orphaned" in orphan.message and not orphan.allow


def test_the_task_key_is_verb_tree_rules_and_runner():
    assert state.task_key(state.Basis(DIGEST, RUNNER.digest, "commit"), TREE) == KEY
    assert plan("push").id == f"gate-push-{TREE}-{DIGEST}-{RUNNER.digest}" != plan("commit").id
    assert plan()._replace(runner=RUNNER._replace(digest="e" * 12)).id != plan().id  # another runner, another task


def test_job_argv_names_the_worker_the_base_the_trusted_tree_and_the_rules():
    argv = plan("push", None).argv
    assert argv[2:] == [state.RUN, "run", "--repo", "/repo", "--tree", TREE, "--base", "-", "--kind", "push",
                        "--trusted", TRUSTED, "--rules", DIGEST, "--runner", RUNNER.digest, "--env", "{}"]
    assert plan("commit").argv[argv.index("--base") + 1] == "b" * 40


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1\n")
    git(tmp_path, "add", "a")
    return tmp_path


def commit(repo: Path, text: str) -> str:
    (repo / "a").write_text(text)
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "c", "--no-verify")
    return git(repo, "rev-parse", "HEAD^{tree}")


def test_commit_trees_before_the_first_commit_and_with_an_empty_index(repo, monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    staged = git(repo, "write-tree")
    assert state.commit_trees(str(repo), False, False) == (staged, None)  # first commit: measured from the empty tree
    first = commit(repo, "1\n")
    assert state.commit_trees(str(repo), False, False) is None  # nothing staged: git refuses it
    assert state.commit_trees(str(repo), False, True) == (first, first)  # --allow-empty
    assert state.commit_trees(str(repo), True, False) == (first, None)  # --amend of a root commit
    second = commit(repo, "2\n")
    assert state.commit_trees(str(repo), True, False) == (second, first)  # amend: measured from the parent
    assert state.push_trees(str(repo)) == (second, first)


def test_empty_index_before_any_commit_is_nothing_to_commit(tmp_path):
    git(tmp_path, "init", "-q")
    assert state.commit_trees(str(tmp_path), False, False) is None
    with pytest.raises(gitq.Unavailable):
        state.push_trees(str(tmp_path))  # unborn HEAD: no tree to judge, refused closed


def test_locate_and_head_ahead_of_upstream(repo, tmp_path_factory, monkeypatch):
    assert gitq.locate(str(repo)).top == str(repo.resolve())
    assert gitq.locate(str(tmp_path_factory.mktemp("plain"))) is None
    assert gitq.head_ahead_of_upstream(str(repo)) is False  # unborn HEAD
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    commit(repo, "1\n")
    assert gitq.head_ahead_of_upstream(str(repo)) is False  # no upstream: not counted as ahead


def test_a_missing_git_is_unavailable_not_a_crash(repo, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(gitq.Unavailable):
        gitq.git(str(repo), "status")


def test_check_begin_and_peek_are_wired_to_the_task_layer(monkeypatch):
    seen = []
    green = tasks.Started(record(), "cached")
    monkeypatch.setattr(state, "prepare", lambda top, verb, tree, base: plan(verb, base))
    monkeypatch.setattr(state.tasks, "start", lambda *a: seen.append(("start", a)) or green)
    monkeypatch.setattr(state.tasks, "status", lambda *a: seen.append(("status", a)) or record(state="running"))
    verdict = state.check("/repo", "commit", TREE, "b" * 40)
    assert verdict == state.Verdict(True, "")
    assert state.begin("/repo", "push", TREE, None) is green
    assert state.peek(plan())["state"] == "running"
    assert seen == [("start", ("gate", plan().key, plan().argv, "/repo")),
                    ("start", ("gate", plan("push", None).key, plan("push", None).argv, "/repo")),
                    ("status", (plan().id, "/repo"))]


def test_a_base_is_green_only_for_the_same_verb_the_same_rules_and_the_same_runner(monkeypatch):
    asked = []
    green = {f"gate-commit-{'b' * 40}-{DIGEST}-{RUNNER.digest}"}

    def status(tid, cwd):
        asked.append(tid)
        return record() if tid in green else None

    monkeypatch.setattr(state.tasks, "status", status)
    basis = state.Basis(DIGEST, RUNNER.digest, "commit")
    assert state.base_is_green("/repo", basis, "b" * 40) is True
    assert state.base_is_green("/repo", basis._replace(kind="push"), "b" * 40) is False  # a commit's record is not a push's
    assert state.base_is_green("/repo", basis._replace(rules="f" * 12), "b" * 40) is False  # other rules: not a proof
    assert state.base_is_green("/repo", basis._replace(runner="f" * 12), "b" * 40) is False  # another runner either
    assert state.base_is_green("/repo", basis, None) is False  # no base: nothing vouches for it
    assert len(asked) == 4


def test_waivers_survive_a_torn_line_and_foreign_rows(tmp_path, monkeypatch):
    monkeypatch.setenv(state.task_store.ENV_DIR, str(tmp_path / "state"))
    import gate_ledger as ledger  # noqa: E402
    assert ledger.waived_trees("/anywhere") == set()  # no file yet
    ledger.waive("/anywhere", TREE, "because")
    path = ledger._waiver_path("/anywhere")
    with open(path, "a") as fh:
        fh.write("{torn\n[1, 2]\n" + json.dumps({"tree": 5}) + "\n" + json.dumps({"no_tree": 1}) + "\n")
    ledger.waive("/anywhere", "c" * 40, "also")
    assert ledger.waived_trees("/anywhere") == {TREE, "c" * 40}


def test_head_ahead_of_upstream_is_true_only_when_they_differ(repo, tmp_path, monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    commit(repo, "1\n")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    assert gitq.head_ahead_of_upstream(str(repo)) is False
    commit(repo, "2\n")
    assert gitq.head_ahead_of_upstream(str(repo)) is True


def test_a_failing_write_tree_is_unavailable_and_a_missing_revision_is_none(repo):
    (repo / "a").write_text("x\n")
    git(repo, "add", "a")
    assert gitq.tree_of(str(repo), "HEAD") is None  # unborn
    assert gitq.tree_of(str(repo), "nonsense") is None
    (repo / ".git" / "index").write_bytes(b"garbage")  # an unreadable index
    with pytest.raises(gitq.Unavailable):
        gitq.staged_tree(str(repo))


# ---------------------------------------------------------------- prepare: the refusals that need no task


GOOD_CONFIG = '{"version": 1, "checks": [{"name": "c", "argv": ["true"]}]}'


def declared_repo(tmp_path, monkeypatch, listed: bool, config_text: str | None = GOOD_CONFIG):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a").write_text("1\n")
    if config_text is not None:
        (repo / ".zetetic").mkdir()
        (repo / ".zetetic" / "gate.json").write_text(config_text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    listing = tmp_path / "trusted"
    import os
    listing.write_text((os.path.realpath(repo) + "\n") if listed else "")
    monkeypatch.setenv("ZETETIC_GATE_TRUSTED_REPOS", str(listing))
    return repo, git(repo, "rev-parse", "HEAD^{tree}")


def test_prepare_returns_a_plan_for_a_gated_and_trusted_repository(tmp_path, monkeypatch):
    repo, head = declared_repo(tmp_path, monkeypatch, listed=True)
    found = state.prepare(str(repo), "push", head, None)
    assert isinstance(found, state.Plan)
    assert (found.top, found.verb, found.tree, found.base, found.rules.trusted) == (str(repo), "push", head, None, head)
    key = f"push-{head}-{found.rules.digest}-{found.runner.digest}"
    assert found.id == f"gate-{key}" and found.key == key


def test_prepare_allows_what_no_rules_gate(tmp_path, monkeypatch):
    repo, head = declared_repo(tmp_path, monkeypatch, listed=False, config_text=None)
    assert state.prepare(str(repo), "commit", head, None) == state.Verdict(True, "")  # not gated: trust is not asked


def test_prepare_denies_an_unlisted_repository_with_the_line_to_add(tmp_path, monkeypatch):
    import os
    repo, head = declared_repo(tmp_path, monkeypatch, listed=False)
    found = state.prepare(str(repo), "commit", head, None)
    assert isinstance(found, state.Verdict) and found.allow is False
    assert f"\n{os.path.realpath(repo)}\n" in found.message and "Nothing was run" in found.message


def test_prepare_denies_an_invalid_config_closed(tmp_path, monkeypatch):
    repo, head = declared_repo(tmp_path, monkeypatch, listed=True, config_text="{torn")
    found = state.prepare(str(repo), "commit", head, None)
    assert found.allow is False and "invalid" in found.message and "refused (closed)" in found.message and str(repo) in found.message


def test_prepare_refuses_a_directory_that_is_not_a_repository_it_can_locate(tmp_path, monkeypatch):
    repo, head = declared_repo(tmp_path, monkeypatch, listed=True)
    monkeypatch.setattr(state.gitq, "locate", lambda directory: None)
    with pytest.raises(gitq.Unavailable):
        state.prepare(str(repo), "commit", head, None)


def test_check_and_begin_stop_at_a_final_verdict(monkeypatch):
    final = state.Verdict(False, "untrusted")
    monkeypatch.setattr(state, "prepare", lambda *a: final)
    monkeypatch.setattr(state.tasks, "start", lambda *a: pytest.fail("a final verdict starts no task"))
    assert state.check("/repo", "commit", TREE, None) is final
    assert state.begin("/repo", "commit", TREE, None) is None


def test_a_ledger_row_finds_its_task_and_its_status_command(monkeypatch):
    seen = []
    monkeypatch.setattr(state.tasks, "status", lambda tid, cwd: seen.append((tid, cwd)) or {"id": tid})
    assert state.record_of_key("/repo", f"commit-{TREE}-{DIGEST}") == {"id": f"gate-commit-{TREE}-{DIGEST}"}
    assert seen == [(f"gate-commit-{TREE}-{DIGEST}", "/repo")]
    assert state.status_command("/repo", f"commit-{TREE}-{DIGEST}") == f"{state.TASK_SH} status gate-commit-{TREE}-{DIGEST} --repo /repo"
