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
import gate_rules  # noqa: E402
import gate_run  # noqa: E402
import gate_state  # noqa: E402
import gate_trust  # noqa: E402


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
    listed = tmp_path / "trusted-repos"
    listed.write_text(os.path.realpath(path) + "\n")  # the test's own trusted-repos file, never the user's
    monkeypatch.setenv(gate_trust.ENV_FILE, str(listed))
    monkeypatch.setenv("ZETETIC_TASKS_DIR", str(tmp_path / "state"))
    return path


def verify(repo: Path, base: str = "-", kind: str = "commit") -> int:
    """What the hook asks the worker for: the staged tree, under the rules of HEAD plus the staged tree."""
    tree = git(repo, "write-tree")
    rules = gate_rules.effective(str(repo), tree)
    return gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", base, "--kind", kind,
                          "--trusted", rules.trusted, "--rules", rules.digest])


def mark_green(repo: Path, tree: str, kind: str = "commit") -> None:
    """A green task record for ``tree`` under the rules a verification of the current index would use: the
    state the gate reaches after a verified commit (written directly; the record is the whole contract)."""
    rules = gate_rules.effective(str(repo), tree)
    tid = gate_state.Plan(str(repo), kind, tree, None, rules).id
    directory = gate_state.task_store.tasks_dir(str(repo))
    gate_state.task_store.atomic_write(gate_state.task_store.record_path(directory, tid),
                                       {"id": tid, "state": "done", "rc": 0})


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


def test_no_change_runs_nothing_when_the_base_is_verified(repo, capsys):
    stage_config(repo, [sh("exit 9")])
    git(repo, "commit", "-q", "-m", "cfg")
    head = git(repo, "rev-parse", "HEAD^{tree}")
    mark_green(repo, head)  # the base has a green record of this kind under these rules
    assert verify(repo, head) == 0
    assert "no check applies" in capsys.readouterr().out


def test_no_change_still_runs_the_full_gate_when_nothing_vouches_for_the_base(repo, capsys):
    stage_config(repo, [sh("exit 9")])
    git(repo, "commit", "-q", "-m", "cfg")
    head = git(repo, "rev-parse", "HEAD^{tree}")
    assert verify(repo, head) == 9  # no green record for the base: affected-only selection is not valid
    assert "no green commit record for base" in capsys.readouterr().out


def test_a_green_record_of_another_kind_does_not_vouch_for_the_base(repo, capsys):
    stage_config(repo, [sh("exit 9")])
    git(repo, "commit", "-q", "-m", "cfg")
    head = git(repo, "rev-parse", "HEAD^{tree}")
    mark_green(repo, head, kind="commit")
    assert verify(repo, head, kind="push") == 9  # the base was verified as a commit, not as a push


def test_invalid_config_in_the_tree_fails_the_task(repo, capsys):
    (repo / ".zetetic").mkdir()
    (repo / ".zetetic" / "gate.json").write_text('{"version": 9}')
    git(repo, "add", ".zetetic/gate.json")
    tree, head = git(repo, "write-tree"), git(repo, "rev-parse", "HEAD^{tree}")
    # the hook refuses an invalid config before any task exists; a worker started by hand still fails closed
    assert gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", "-", "--kind", "commit",
                          "--trusted", head, "--rules", "0" * 12]) == 1
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
    out = capsys.readouterr().out
    assert "[gate:legacy-gate] sh " in out and "scripts/gate.sh push" in out


def test_a_staged_change_to_the_legacy_script_does_not_replace_the_trusted_one(repo, tmp_path):
    stage_legacy(repo, f"echo trusted-copy-ran > {tmp_path / 'which'}\nexit 1\n")  # HEAD's script fails
    git(repo, "commit", "-q", "-m", "legacy gate")
    (repo / "scripts" / "gate.sh").write_text("#!/bin/sh\n" + LEGACY_PROOF)  # the change makes itself pass
    git(repo, "add", "scripts/gate.sh")
    assert verify(repo) == 1  # HEAD's copy judges the change, and it fails
    assert (tmp_path / "which").read_text().strip() == "trusted-copy-ran"


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
        gate_run.main(["run", "--repo", str(repo), "--tree", "nothex", "--base", "-", "--kind", "commit",
                       "--trusted", "b" * 40, "--rules", "0" * 12])


def test_the_callers_git_environment_reaches_neither_the_checkout_nor_the_checks(repo, monkeypatch):
    stage_config(repo, [sh('test -z "$GIT_NAMESPACE" && test -z "$GIT_INDEX_FILE"')])
    tree = git(repo, "write-tree")
    rules = gate_rules.effective(str(repo), tree)
    monkeypatch.setenv("GIT_NAMESPACE", "leaked")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent/index")  # would break read-tree if it reached the private index
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/nonexistent/objects")  # would hide every object from the plumbing
    assert gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", "-", "--kind", "commit",
                          "--trusted", rules.trusted, "--rules", rules.digest]) == 0


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
    assert gate_run.main(["run", "--repo", str(tmp_path), "--tree", "a" * 40, "--base", "-", "--kind", "commit",
                          "--trusted", "b" * 40, "--rules", "0" * 12]) == 1
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


def test_a_worker_started_by_hand_for_an_unlisted_repository_runs_nothing(repo, tmp_path, monkeypatch, capsys):
    stage_config(repo, [sh(f"echo ran > {tmp_path / 'ran'}")])
    monkeypatch.setenv(gate_trust.ENV_FILE, str(tmp_path / "nobody"))  # a trusted-repos file that lists nothing
    assert verify(repo) == 1
    assert "not in your trusted list" in capsys.readouterr().out and not (tmp_path / "ran").exists()


def test_a_worker_asked_for_other_rules_than_the_ones_in_force_refuses(repo, tmp_path, capsys):
    stage_config(repo, [sh(f"echo ran > {tmp_path / 'ran'}")])
    tree = git(repo, "write-tree")
    trusted = gate_rules.effective(str(repo), tree).trusted
    assert gate_run.main(["run", "--repo", str(repo), "--tree", tree, "--base", "-", "--kind", "commit",
                          "--trusted", trusted, "--rules", "f" * 12]) == 1
    out = capsys.readouterr().out
    assert "effective rules changed" in out and "f" * 12 in out and not (tmp_path / "ran").exists()


@pytest.mark.parametrize("missing", ["--repo", "--tree", "--base", "--kind", "--trusted", "--rules"])
def test_every_argument_of_the_worker_is_required(repo, missing):
    tree = git(repo, "write-tree")
    given = {"--repo": str(repo), "--tree": tree, "--base": "-", "--kind": "commit", "--trusted": tree, "--rules": "0" * 12}
    argv = ["run"] + [x for k, v in given.items() if k != missing for x in (k, v)]
    with pytest.raises(SystemExit):
        gate_run.main(argv)


def test_an_archive_member_cannot_leave_the_directory_it_is_extracted_into(tmp_path):
    import io
    import tarfile
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("../escape.sh")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
    buffer.seek(0)
    root = tmp_path / "scripts"
    root.mkdir()
    with tarfile.open(fileobj=buffer) as tar:
        with pytest.raises(RuntimeError, match="escapes"):
            gate_run._unpack(tar, tar.getmembers()[0], str(root))
    assert not (tmp_path / "escape.sh").exists()


def test_the_legacy_scripts_are_exported_with_their_modes_and_without_symlinks(repo, tmp_path):
    scripts = repo / "scripts"
    (scripts / "gate.d").mkdir(parents=True)
    (scripts / "gate.sh").write_text("#!/bin/sh\n. \"$(dirname \"$0\")/gate.d/common.sh\"\n")
    (scripts / "gate.sh").chmod(0o755)
    (scripts / "gate.d" / "common.sh").write_text("echo common\n")
    (scripts / "link").symlink_to("/etc/passwd")
    git(repo, "add", "scripts")
    oid = git(repo, "write-tree")
    oid = git(repo, "rev-parse", f"{oid}:scripts")
    out = gate_run.export_scripts(str(repo), oid, str(tmp_path / "exp"))
    base = Path(out).parent
    assert out == str(tmp_path / "exp" / "scripts" / "gate.sh") and os.access(out, os.X_OK)
    assert (base / "gate.d" / "common.sh").read_text() == "echo common\n" and not (base / "gate.d" / "common.sh").stat().st_mode & 0o111
    assert not (base / "link").exists() and not (base / "link").is_symlink()
