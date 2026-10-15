"""hooks/lib/gate_run.py: the task's command verifies THE TREE, never the working directory.

In-process (gate_run.main) against a real repository: the checks are plain `sh -c` commands, so these
tests start no detached worker and wait for nothing.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from gate_support import git, write_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_run  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("one\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "init")
    return path


def verify(repo: Path, base: str = "-", kind: str = "commit") -> int:
    tree = git(repo, "write-tree")
    return gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", base, "--kind", kind])


def stage_config(repo: Path, checks: list, **extra) -> None:
    write_config(repo, checks, **extra)
    git(repo, "add", ".zetetic/gate.json")


def sh(script: str, name: str = "c") -> dict:
    return {"name": name, "argv": ["sh", "-c", script]}


def test_the_check_sees_the_staged_bytes_not_the_edited_working_tree(repo):
    stage_config(repo, [sh("grep -qx staged a.txt")])
    (repo / "a.txt").write_text("staged\n")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("edited after staging\n")  # the working tree moves on while the gate runs
    assert verify(repo) == 0


def test_a_failing_check_fails_the_task_with_its_exit_code_and_stops_there(repo, capsys):
    stage_config(repo, [sh("exit 4", "first"), sh("echo second-ran", "second")])
    assert verify(repo) == 4
    out = capsys.readouterr().out
    assert "[gate:first] FAILED rc=4" in out and "second-ran" not in out


def test_checks_run_in_a_private_checkout_that_is_removed(repo, tmp_path, capsys):
    stage_config(repo, [sh("pwd > " + str(tmp_path / "where"))])
    assert verify(repo) == 0
    where = Path((tmp_path / "where").read_text().strip())
    assert where != repo and not where.exists()  # not the working tree; gone afterwards


def test_checkout_is_removed_even_when_a_check_fails(repo, tmp_path):
    stage_config(repo, [sh("pwd > " + str(tmp_path / "where") + "; exit 1")])
    assert verify(repo) == 1
    assert not Path((tmp_path / "where").read_text().strip()).exists()


def test_a_missing_command_is_a_failure_127(repo, capsys):
    stage_config(repo, [{"name": "ghost", "argv": ["/nonexistent/zz"]}])
    assert verify(repo) == 127
    assert "cannot start" in capsys.readouterr().out


def test_only_checks_affected_by_the_change_run(repo, capsys):
    stage_config(repo, [{**sh("echo py-ran", "py"), "paths": ["**/*.py"]}, {**sh("echo txt-ran", "txt"), "paths": ["**/*.txt"]}])
    git(repo, "commit", "-q", "-m", "cfg")
    base = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")
    assert verify(repo, base) == 0
    out = capsys.readouterr().out
    assert "txt-ran" in out and "py-ran" not in out and "1 changed path(s)" in out


def test_untracked_dependencies_are_linked_and_env_is_resolved(repo, tmp_path):
    (repo / "deps").mkdir()
    (repo / "deps" / "lib.txt").write_text("dependency\n")  # untracked: not in the tree, so not in the checkout
    stage_config(repo, [sh('test -f deps/lib.txt && test "$GATE_TOP" = "' + str(repo) + '" && test -n "$GATE_COMMON"')],
                 link=["deps"], env={"GATE_TOP": "{top}", "GATE_COMMON": "{common}"})
    assert verify(repo) == 0


def test_a_missing_link_source_is_skipped_not_invented(repo):
    stage_config(repo, [sh("test ! -L nothing && test ! -e nothing")], link=["nothing"])  # no dangling symlink either
    assert verify(repo) == 0


def test_a_link_never_replaces_a_tracked_path(repo):
    stage_config(repo, [sh("test ! -L a.txt && grep -qx one a.txt")], link=["a.txt"])
    assert verify(repo) == 0


def test_no_change_runs_nothing_and_passes(repo, capsys):
    stage_config(repo, [sh("exit 9")])
    git(repo, "commit", "-q", "-m", "cfg")
    assert verify(repo, git(repo, "rev-parse", "HEAD^{tree}")) == 0
    assert "no check applies" in capsys.readouterr().out


def test_invalid_config_in_the_tree_fails_the_task(repo, capsys):
    (repo / ".zetetic").mkdir()
    (repo / ".zetetic" / "gate.json").write_text('{"version": 9}')
    git(repo, "add", ".zetetic/gate.json")
    assert verify(repo) == 1
    assert "version" in capsys.readouterr().out


def test_the_rules_come_from_the_staged_tree_not_the_working_copy(repo):
    stage_config(repo, [sh("exit 5")])
    write_config(repo, [sh("exit 0")])  # an unstaged weakening of the gate does not count
    assert verify(repo) == 5


LEGACY_PROOF = (
    "T=$(git write-tree); D=\"$(git rev-parse --git-common-dir)/zetetic-gates\"; mkdir -p \"$D\"\n"
    "printf '{\"tree\": \"%s\", \"rc\": 0}' \"$T\" > \"$D/$1-$T.json\"\n"
)


def stage_legacy(repo: Path, body: str) -> None:
    script = repo / "scripts" / "gate.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    git(repo, "add", "scripts/gate.sh")


def test_legacy_script_judges_the_real_checkout(repo, tmp_path, capsys):
    stage_legacy(repo, f"pwd > {tmp_path / 'legacy-cwd'}\necho \"kind=$1\"\n" + LEGACY_PROOF)
    assert verify(repo, kind="push") == 0  # the script left push-<this tree>.json
    assert (tmp_path / "legacy-cwd").read_text().strip() == str(repo.resolve())
    assert "[gate:legacy-gate] sh scripts/gate.sh push" in capsys.readouterr().out


def test_a_legacy_script_that_proved_another_tree_does_not_turn_this_one_green(repo, capsys):
    stage_legacy(repo, "T=$(git write-tree); mkdir -p .git/zetetic-gates\n"
                       "printf '{\"tree\": \"%s\", \"rc\": 0}' \"$T\" > \".git/zetetic-gates/$1-0000000000000000000000000000000000000000.json\"\n")
    assert verify(repo) == 1
    assert "proved a different tree" in capsys.readouterr().out


def test_a_legacy_script_that_exits_zero_without_a_proof_is_not_green(repo, capsys):
    stage_legacy(repo, "exit 0\n")
    assert verify(repo) == 1
    assert "left no green proof" in capsys.readouterr().out


def test_a_legacy_proof_must_be_green_and_name_the_tree(repo):
    common = str(repo / ".git")
    proofs = repo / ".git" / "zetetic-gates"
    proofs.mkdir()
    tree = "a" * 40
    for body in ('{"tree": "%s", "rc": 1}' % tree, '{"tree": "%s", "rc": true}' % tree, '{"tree": "%s"}' % ("b" * 40),
                 "{torn", "[1]"):
        (proofs / f"commit-{tree}.json").write_text(body)
        assert gate_run.legacy_proof_names(common, "commit", tree) is False, body
    (proofs / f"commit-{tree}.json").write_text('{"tree": "%s", "rc": 0}' % tree)
    assert gate_run.legacy_proof_names(common, "commit", tree) is True
    assert gate_run.legacy_proof_names(common, "push", tree) is False  # no push proof


def test_stack_default_runs_the_whole_suite_when_something_changed(repo, tmp_path, capsys, monkeypatch):
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "echo stack-suite-ran"}}))
    git(repo, "add", "package.json")
    npm = tmp_path / "bin" / "npm"
    npm.parent.mkdir()
    npm.write_text("#!/bin/sh\necho npm-stub \"$@\"\n")
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{npm.parent}{os.pathsep}{os.environ['PATH']}")
    assert verify(repo) == 0
    assert "[gate:test] npm test --silent" in capsys.readouterr().out


def test_python_placeholder_resolves_to_the_checkouts_venv_then_ours(repo, tmp_path):
    common = str(repo / ".git")
    assert gate_run.resolve_python(str(repo), common) == sys.executable
    venv = repo / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    assert gate_run.resolve_python(str(repo), common) == str(venv / "python")


def test_bad_arguments_are_a_usage_error(repo):
    with pytest.raises(SystemExit):
        gate_run.main(["run", "--repo", str(repo), "--tree", "nothex", "--base", "-", "--kind", "commit"])


def test_the_callers_git_environment_reaches_neither_the_checkout_nor_the_checks(repo, monkeypatch):
    stage_config(repo, [sh('test -z "$GIT_NAMESPACE" && test -z "$GIT_INDEX_FILE"')])
    tree = git(repo, "write-tree")
    monkeypatch.setenv("GIT_NAMESPACE", "leaked")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent/index")  # would break read-tree if it reached the private index
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/nonexistent/objects")  # would hide every object from the plumbing
    assert gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", "-", "--kind", "commit"]) == 0


def test_a_tree_that_declares_no_gate_has_nothing_to_verify(repo, capsys):
    (repo / ".zetetic").mkdir()
    (repo / ".zetetic" / "gate.json").write_text('{"version": 1, "off": true}')
    git(repo, "add", ".zetetic/gate.json")
    assert verify(repo) == 0
    assert "no gate is declared" in capsys.readouterr().out


def test_a_check_killed_by_a_signal_fails_the_task(repo, capsys):
    stage_config(repo, [sh("kill -9 $$")])
    assert verify(repo) == 1
    assert "FAILED rc=-9" in capsys.readouterr().out


def test_a_non_executable_venv_python_is_not_used(repo):
    venv = repo / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o644)
    assert gate_run.resolve_python(str(repo), str(repo / ".git")) == sys.executable


def test_a_directory_that_is_not_a_repository_is_a_failure(tmp_path, capsys):
    assert gate_run.main(["run", "--repo", str(tmp_path), "--tree", "a" * 40, "--base", "-", "--kind", "commit"]) == 1
    assert "not a git repository" in capsys.readouterr().out


def test_the_private_checkout_is_named_by_tree_and_repository_and_replaces_a_leftover(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = gate_run._snapshot_dir("a" * 40, "/one/.git")
    (Path(first) / "leftover").write_text("from a SIGKILLed attempt")
    again = gate_run._snapshot_dir("a" * 40, "/one/.git")
    assert again == first and os.listdir(again) == []  # replaced, empty
    assert gate_run._snapshot_dir("a" * 40, "/two/.git") != first  # another repository: another directory
    assert gate_run._snapshot_dir("b" * 40, "/one/.git") != first  # another tree: another directory


def test_nothing_is_left_behind_in_the_temp_directory(repo, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    stage_config(repo, [sh("exit 0")])
    assert verify(repo) == 0
    assert os.listdir(scratch) == []  # neither the checkout nor its private index


@pytest.mark.parametrize("missing", ["--repo", "--tree", "--base", "--kind"])
def test_every_option_is_required(repo, missing):
    args = {"--repo": str(repo), "--tree": "a" * 40, "--base": "-", "--kind": "commit"}
    del args[missing]
    with pytest.raises(SystemExit):
        gate_run.main(["run", *[x for kv in args.items() for x in kv]])
    with pytest.raises(SystemExit):
        gate_run.main([])  # the verb is required too


def test_the_worker_lowers_its_priority(monkeypatch):
    seen = []
    monkeypatch.setattr(os, "nice", lambda n: seen.append(n))
    gate_run._lower_priority()
    assert seen == [10]
