"""hooks/lib/gate_run.py: the task's command verifies THE TREE, never the working directory.

In-process (gate_run.main) against a real repository: the checks are plain `sh -c` commands, so these
tests start no detached worker and wait for nothing.
"""
from __future__ import annotations

import json
import os
import sys
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
    stage_config(repo, [sh("test ! -e nothing")], link=["nothing"])
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


def test_legacy_script_judges_the_real_checkout(repo, tmp_path, capsys):
    script = repo / "scripts" / "gate.sh"
    script.parent.mkdir()
    script.write_text(f"#!/bin/sh\npwd > {tmp_path / 'legacy-cwd'}\necho \"kind=$1\"\nexit 0\n")
    script.chmod(0o755)
    git(repo, "add", "scripts/gate.sh")
    assert verify(repo, kind="push") == 0
    assert (tmp_path / "legacy-cwd").read_text().strip() == str(repo.resolve())
    assert "[gate:legacy-gate] sh scripts/gate.sh push" in capsys.readouterr().out


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
