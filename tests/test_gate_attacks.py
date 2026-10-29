"""The commit gate against the attacks of the PR #169 review (round 1 at 1b96a40, REQUEST-CHANGES).

Each test is the ATTACK first: written to pass at 1b96a40 (the attack succeeds there, so the assertion that
it is refused fails there) and to fail here. Real git repository, real hooks as subprocesses, a real
detached worker. Event-synchronised only: a verification is awaited by the exit of its worker; no sleep,
poll or timeout decides a result.

  1  a staged .zetetic/gate.json must not approve its own change         (config: checks ["true"], "off")
  2  a push-only gate must not be satisfied by a green commit record       (legacy scripts/gate.sh push)
  3  a push is judged by the tip of every ref it publishes                 (feat, feat:main, --all, gh --head)
  a  a repository the user did not list never has its commands run
  b  the cache key is kind + tree + rules; affected-only needs a green base
  c  run-python.sh fails closed for gate-proof.py only; the registration refuses a hook that cannot finish
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from gate_support import HOOKS, ROOT, Gate, git, payload, run_hook, write_config
from task_support import tasks, wait_exit

COMMIT = 'git commit -m "wip"'
FAIL_IF_BAD = {"name": "no-bad", "argv": ["sh", "-c", "test ! -e bad.txt"]}


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    commit_rules(g, [FAIL_IF_BAD])
    yield g
    g.close()


def commit_rules(g: Gate, checks: list, **extra) -> None:
    """HEAD's rules: committed (unverified: --no-verify), so they are the trusted tree."""
    write_config(g.repo, checks, **extra)
    git(g.repo, "add", ".zetetic/gate.json")
    git(g.repo, "commit", "-q", "-m", "rules", "--no-verify")


def settle(g: Gate) -> dict:
    """Wait for the exit of the worker of the task started last; return its final record."""
    rec = tasks.latest("gate", None, str(g.repo))
    wait_exit(rec["pid"])
    return tasks.latest("gate", None, str(g.repo))


def stage_bad(g: Gate) -> str:
    (g.repo / "bad.txt").write_text("this file fails HEAD's rule\n")
    git(g.repo, "add", "bad.txt")
    return git(g.repo, "write-tree")


# ------------------------------------------------------------------ 1. self-approving configuration


def test_a_staged_config_that_approves_everything_does_not_approve_its_own_change(gate):
    stage_bad(gate)
    write_config(gate.repo, [{"name": "yes", "argv": ["true"]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    assert gate.gate(COMMIT)[0] == 2  # starts the verification
    assert settle(gate)["state"] == "failed"  # HEAD's rule ran on the staged tree and found bad.txt
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "verification FAILED" in err


def test_a_staged_off_switch_does_not_switch_the_gate_off(gate):
    stage_bad(gate)
    write_config(gate.repo, [], off=True)
    git(gate.repo, "add", ".zetetic/gate.json")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "failed"
    assert gate.gate(COMMIT)[0] == 2


def test_an_unstaged_off_switch_in_the_working_copy_is_not_read_at_all(gate):
    stage_bad(gate)
    write_config(gate.repo, [], off=True)  # edited, never staged: the declaration comes from the trusted tree
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "failed"
    assert gate.head_start()[0] == 0


def test_a_config_change_is_judged_by_the_union_of_head_rules_and_staged_rules(gate):
    (gate.repo / "other.txt").write_text("trips the staged rule\n")
    git(gate.repo, "add", "other.txt")
    write_config(gate.repo, [FAIL_IF_BAD, {"name": "no-other", "argv": ["sh", "-c", "test ! -e other.txt"]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "failed"  # the rule the change ADDS also applies to it


def test_staged_environment_of_a_config_does_not_reach_heads_checks(gate):
    commit_rules(gate, [{"name": "env", "argv": ["sh", "-c", 'test -z "$HIJACK"']}])
    write_config(gate.repo, [{"name": "noop", "argv": ["true"]}], env={"HIJACK": "1"})
    git(gate.repo, "add", ".zetetic/gate.json")
    gate.stage("two\n")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "done"  # HEAD's check ran without the staged config's environment


# --------------------------------------------------------------------- 2. push-only legacy gates

LEGACY = (
    '#!/bin/sh\n'
    'kind=$1\n'
    '[ "$kind" = push ] && { echo "push-only gate (bench) failed"; exit 1; }\n'
    'T=$(git write-tree); D="$(git rev-parse --git-common-dir)/zetetic-gates"; mkdir -p "$D"\n'
    'printf \'{"tree": "%s", "rc": 0}\' "$T" > "$D/$kind-$T.json"\n'
)


def test_a_green_commit_record_does_not_satisfy_a_push_only_gate(gate):
    git(gate.repo, "rm", "-q", ".zetetic/gate.json")
    script = gate.repo / "scripts" / "gate.sh"
    script.parent.mkdir()
    script.write_text(LEGACY)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    git(gate.repo, "add", "scripts/gate.sh")
    git(gate.repo, "commit", "-q", "-m", "legacy gate", "--no-verify")
    tree = gate.stage("two\n")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "done"
    assert gate.gate(COMMIT) == (0, "", "")  # the commit gate is green
    assert gate.commit() == tree
    rc, _, err = gate.gate("git push")  # but the push gate has not run: a commit record is not a push record
    assert rc == 2 and "verification started" in err
    assert settle(gate)["state"] == "failed"
    rc, _, err = gate.gate("git push")
    assert rc == 2 and "push-only gate (bench) failed" in err


# -------------------------------------------------------- 3. a push is judged by what it publishes


def push_green_main_with_failing_feat(g: Gate) -> None:
    """main (HEAD) holds a green push record; branch feat holds a tree that fails the rules."""
    assert g.gate("git push")[0] == 2
    assert settle(g)["state"] == "done"
    assert g.gate("git push") == (0, "", "")
    git(g.repo, "checkout", "-q", "-b", "feat")
    (g.repo / "bad.txt").write_text("fails\n")
    git(g.repo, "add", "bad.txt")
    git(g.repo, "commit", "-q", "-m", "feat", "--no-verify")
    git(g.repo, "checkout", "-q", "main")


@pytest.mark.parametrize("command", [
    "git push origin feat",
    "git push origin feat:main",
    "git push origin +feat:refs/heads/other",
    "git push --all origin",
    "git push origin 'refs/heads/*:refs/heads/*'",
    "git push origin feat main",
    "git -C {repo} push origin feat",
    "gh pr create --head feat --fill",
    "gh pr create -H feat --fill",
    "gh pr create --head=someone:feat --fill",
])
def test_a_push_of_a_failing_branch_is_refused_while_head_is_green(gate, command):
    push_green_main_with_failing_feat(gate)
    rc, _, err = gate.gate(command.format(repo=gate.repo))
    assert rc == 2 and "[feat]" in err and "verification" in err, command


def test_what_is_green_is_still_allowed(gate):
    push_green_main_with_failing_feat(gate)
    for command in ("git push", "git push origin main", "git push origin HEAD", "git push -u origin main:main",
                    "git push origin --tags", "git push origin :feat", "git push --delete origin feat"):
        assert gate.gate(command) == (0, "", ""), command


def test_the_failure_of_the_published_branch_is_reported_once_its_verification_ended(gate):
    push_green_main_with_failing_feat(gate)
    assert gate.gate("git push origin feat")[0] == 2
    assert settle(gate)["state"] == "failed"
    rc, _, err = gate.gate("git push origin feat")
    assert rc == 2 and "[feat]" in err and "verification FAILED" in err and "push" in err


@pytest.mark.parametrize("command,reason", [
    ("git push origin nosuch", "cannot resolve 'nosuch'"),
    ("git push origin nosuch:main", "cannot resolve 'nosuch'"),
    ("gh pr create --head nosuch --fill", "cannot resolve 'refs/heads/nosuch'"),
])
def test_a_ref_that_does_not_resolve_is_denied_with_the_reason(gate, command, reason):
    rc, _, err = gate.gate(command)
    assert rc == 2 and reason in err and "cannot tell which commits this publishes" in err


def test_a_push_without_a_ref_from_a_detached_head_is_denied(gate):
    git(gate.repo, "checkout", "-q", "--detach")
    rc, _, err = gate.gate("git push")
    assert rc == 2 and "detached" in err


def test_a_configured_push_refspec_is_the_ref_that_is_published(gate):
    push_green_main_with_failing_feat(gate)
    git(gate.repo, "config", "remote.origin.push", "refs/heads/feat:refs/heads/feat")
    rc, _, err = gate.gate("git push origin")
    assert rc == 2 and "[feat]" in err


def test_push_default_matching_publishes_every_local_branch(gate):
    push_green_main_with_failing_feat(gate)
    git(gate.repo, "config", "push.default", "matching")
    rc, _, err = gate.gate("git push")
    assert rc == 2 and "[feat]" in err


# ------------------------------------------------------------- a. only listed repositories ever run


def untrusted(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path, trusted=False)
    commit_rules(g, [{"name": "mark", "argv": ["sh", "-c", f"echo ran >> {g.mark}"]}])
    return g


def test_an_unlisted_repository_is_denied_with_the_line_to_add_and_nothing_runs(tmp_path, monkeypatch, spawning):
    g = untrusted(tmp_path, monkeypatch, spawning)
    try:
        g.stage("two\n")
        assert g.head_start()[0] == 0 and g.started() == []  # `git add` starts nothing in an unlisted repository
        rc, _, err = g.gate(COMMIT)
        line = os.path.realpath(g.repo)
        assert rc == 2 and "not in your trusted list" in err and "Nothing was run" in err
        assert f"\n{line}\n" in err and str(g.trusted_file) in err  # the exact line, and the file it goes in
        assert g.started() == [] and g.runs() == 0
        git(g.repo, "commit", "-q", "-m", "x", "--no-verify")
        rc, _, err = g.gate("git push")
        assert rc == 2 and "not in your trusted list" in err and g.started() == [] and g.runs() == 0
        assert not g.trusted_file.exists()  # the hook never writes the user's file
    finally:
        g.close()


def test_listing_the_repository_lets_the_gate_run(tmp_path, monkeypatch, spawning):
    g = untrusted(tmp_path, monkeypatch, spawning)
    try:
        g.stage("two\n")
        assert g.gate(COMMIT)[0] == 2 and g.runs() == 0
        g.trust()
        assert g.gate(COMMIT)[0] == 2  # now it starts
        assert settle(g)["state"] == "done" and g.runs() == 1
        assert g.gate(COMMIT) == (0, "", "")
    finally:
        g.close()


def test_a_worker_started_by_hand_refuses_an_unlisted_repository_too(tmp_path, monkeypatch, spawning, capsys):
    g = untrusted(tmp_path, monkeypatch, spawning)
    try:
        sys.path.insert(0, str(HOOKS / "lib"))
        import gate_rules  # noqa: E402
        import gate_run  # noqa: E402
        monkeypatch.setenv("ZETETIC_GATE_TRUSTED_REPOS", str(g.trusted_file))
        tree = g.stage("two\n")
        rules = gate_rules.effective(str(g.repo), tree)
        argv = ["run", "--repo", str(g.repo), "--tree", tree, "--base", "-", "--kind", "commit",
                "--trusted", rules.trusted, "--rules", rules.digest, "--runner", "0" * 12, "--env", "{}"]
        assert gate_run.main(argv) == 1 and g.runs() == 0
        assert "not in your trusted list" in capsys.readouterr().out
    finally:
        g.close()


def test_the_trusted_file_is_parsed_strictly(tmp_path, monkeypatch):
    sys.path.insert(0, str(HOOKS / "lib"))
    import gate_trust  # noqa: E402
    listing = tmp_path / "trusted"
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    listing.write_text(f"# a comment\n\n   {link}   \nrelative/path\n{tmp_path / 'absent'}\n")
    monkeypatch.setenv(gate_trust.ENV_FILE, str(listing))
    assert gate_trust.listed() == {os.path.realpath(real), os.path.realpath(tmp_path / "absent")}  # symlinks resolved; relative lines ignored
    monkeypatch.setenv(gate_trust.ENV_FILE, str(tmp_path / "missing"))
    assert gate_trust.listed() == set()


def test_listing_the_main_checkout_trusts_its_worktrees_and_a_listed_worktree_only_itself(tmp_path, monkeypatch):
    sys.path.insert(0, str(HOOKS / "lib"))
    import gate_git  # noqa: E402
    import gate_trust  # noqa: E402
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "a").write_text("1\n")
    git(main, "add", "a")
    git(main, "commit", "-q", "-m", "c")
    worktree = main / ".claude" / "worktrees" / "w"
    git(main, "worktree", "add", "-q", str(worktree), "-b", "w")
    other = tmp_path / "other"
    git(main, "worktree", "add", "-q", str(other), "-b", "o")
    listing = tmp_path / "trusted"
    monkeypatch.setenv(gate_trust.ENV_FILE, str(listing))
    common = gate_git.locate(str(worktree)).common
    listing.write_text(os.path.realpath(main) + "\n")
    assert gate_trust.is_trusted(os.path.realpath(worktree), common)
    assert gate_trust.refusal(os.path.realpath(worktree), common).count(os.path.realpath(main)) >= 1
    listing.write_text(os.path.realpath(worktree) + "\n")
    assert gate_trust.is_trusted(os.path.realpath(worktree), common)
    assert not gate_trust.is_trusted(os.path.realpath(other), common)


# ----------------------------------------------- b. the cache key, and when affected-only is valid


def two_scope_gate(g: Gate) -> None:
    """Two checks, one per file kind, each leaving a mark: what ran is what the diff (or the full gate) selected."""
    marks = g.tmp / "marks"
    commit_rules(g, [
        {"name": "txt", "paths": ["*.txt"], "argv": ["sh", "-c", f"echo txt >> {marks}"]},
        {"name": "md", "paths": ["*.md"], "argv": ["sh", "-c", f"echo md >> {marks}"]},
    ])
    (g.repo / "README.md").write_text("doc\n")
    git(g.repo, "add", "README.md")
    git(g.repo, "commit", "-q", "-m", "doc", "--no-verify")


def marks(g: Gate) -> list:
    path = g.tmp / "marks"
    return sorted(path.read_text().split()) if path.exists() else []


def test_without_a_green_base_the_full_configured_gate_runs_not_the_affected_checks(gate):
    two_scope_gate(gate)
    gate.stage("two\n")  # a one-file change to a .txt file; HEAD was never verified
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "done"
    assert marks(gate) == ["md", "txt"]  # the md check ran although only a txt file changed


def test_with_a_green_base_only_the_checks_that_cover_the_diff_run(gate):
    two_scope_gate(gate)
    gate.stage("two\n")
    assert gate.gate(COMMIT)[0] == 2
    settle(gate)
    gate.commit()
    (gate.tmp / "marks").unlink()
    gate.stage("three\n")  # HEAD's tree now has a green commit record under the same rules
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "done"
    assert marks(gate) == ["txt"]


def test_a_green_commit_record_of_the_base_does_not_vouch_for_a_push(gate):
    two_scope_gate(gate)
    gate.stage("two\n")
    gate.gate(COMMIT)
    settle(gate)
    gate.commit()
    (gate.tmp / "marks").unlink()
    assert gate.gate("git push")[0] == 2
    assert settle(gate)["state"] == "done"
    assert marks(gate) == ["md", "txt"]  # the push is verified in full: its base has no push record


def test_the_key_is_verb_tree_and_a_digest_of_the_effective_rules(gate):
    sys.path.insert(0, str(HOOKS / "lib"))
    import gate_rules  # noqa: E402
    tree = gate.stage("two\n")
    assert gate.gate(COMMIT)[0] == 2
    first = tasks.latest("gate", None, str(gate.repo))
    digest = gate_rules.effective(str(gate.repo), tree).digest
    assert re.fullmatch(f"commit-{tree}-{digest}-[0-9a-f]{{12}}", first["key"])  # verb, tree, rules, runner
    commit_rules(gate, [FAIL_IF_BAD, {"name": "more", "argv": ["true"]}])  # other rules, same tree contents for a.txt
    other = gate_rules.effective(str(gate.repo), gate.stage("two\n")).digest
    assert other != digest


# ---------------------------------------------------------------------- c. fail closed


def no_python_path(tmp_path: Path, tools: tuple = ()) -> str:
    """A PATH holding only ``tools`` (default: nothing at all) and no python of any name."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in tools:
        found = subprocess.run(["sh", "-c", f"command -v {name}"], capture_output=True, text=True).stdout.strip()
        if not (bin_dir / name).exists():
            (bin_dir / name).symlink_to(found)
    return str(bin_dir)


def run_wrapper(tmp_path: Path, script: str, event: dict, tools: tuple = ()) -> tuple:
    out = subprocess.run(["/bin/bash", str(HOOKS / "run-python.sh"), str(HOOKS / script)], input=json.dumps(event),
                         capture_output=True, text=True, env={"PATH": no_python_path(tmp_path, tools), "HOME": str(tmp_path)})
    return out.returncode, out.stderr


def test_without_python_the_commit_gate_refuses_what_can_publish_and_nothing_else(tmp_path):
    rc, err = run_wrapper(tmp_path, "gate-proof.py", payload(COMMIT, tmp_path))
    assert rc == 2 and "no working Python 3" in err and "refused (closed)" in err
    rc, err = run_wrapper(tmp_path, "gate-proof.py", payload("gh pr create --fill", tmp_path))
    assert rc == 2
    rc, err = run_wrapper(tmp_path, "gate-proof.py", {"cwd": "/x", "tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    assert rc == 0  # a call that cannot publish a commit is not blocked: a host without Python can still install one


def test_without_python_every_other_hook_still_fails_open(tmp_path):
    for script in ("gate-start.py", "stop-gate-ledger.py"):
        rc, err = run_wrapper(tmp_path, script, payload(COMMIT, tmp_path))
        assert rc == 0 and "Hook skipped" in err, script


def gate_proof_entries(path: Path) -> list:
    """Every hook object of the manifest whose command runs gate-proof.py, wherever it sits in the document."""
    found: list = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "gate-proof.py" in str(node.get("command", "")):
                found.append(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(json.loads(path.read_text()))
    return found


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".claude-plugin/plugin.json"])
def test_the_commit_gate_is_registered_to_refuse_when_it_cannot_finish(manifest):
    """Claude Code 2.1.301, hook schema `onFailure`: 'continue' (default) = a hook that could not start, timed
    out, exited with a code other than 0 or 2, or printed invalid JSON is reported and the action goes ahead;
    'block' = the failure counts as exit code 2. Without it a killed gate is an open gate (docs/gate.md)."""
    entries = gate_proof_entries(ROOT / manifest)
    assert len(entries) == 1 and entries[0]["onFailure"] == "block"


def test_only_the_commit_gate_asks_for_onfailure_block():
    spec = (ROOT / "hooks" / "hooks.json").read_text()
    assert spec.count('"onFailure"') == 1


def test_every_failing_tip_is_named_on_its_own_line(gate):
    push_green_main_with_failing_feat(gate)
    git(gate.repo, "checkout", "-q", "-b", "other")
    (gate.repo / "bad.txt").write_text("a different failing tree\n")
    git(gate.repo, "add", "bad.txt")
    git(gate.repo, "commit", "-q", "-m", "other", "--no-verify")
    git(gate.repo, "checkout", "-q", "main")
    rc, _, err = gate.gate("git push --all origin")
    assert rc == 2 and "[feat] GATE-PROOF" in err and "\n[other] GATE-PROOF" in err and "[main]" not in err


def test_a_repository_cannot_list_itself_through_the_override(tmp_path, monkeypatch, spawning):
    """A project's settings can set the override variable; a list that lives inside the repository is ignored."""
    sys.path.insert(0, str(HOOKS / "lib"))
    import gate_git  # noqa: E402
    import gate_trust  # noqa: E402
    g = untrusted(tmp_path, monkeypatch, spawning)
    try:
        own = g.repo / ".zetetic" / "trusted"
        own.write_text(os.path.realpath(g.repo) + "\n")
        common = gate_git.locate(str(g.repo)).common
        monkeypatch.setenv(gate_trust.ENV_FILE, str(own))
        assert not gate_trust.is_trusted(os.path.realpath(g.repo), common)  # inside the working tree
        in_git_dir = Path(common) / "trusted"
        in_git_dir.write_text(os.path.realpath(g.repo) + "\n")
        monkeypatch.setenv(gate_trust.ENV_FILE, str(in_git_dir))
        assert not gate_trust.is_trusted(os.path.realpath(g.repo), common)  # inside the git directory
        g.stage("two\n")
        rc, _, err = run_hook("gate-proof.py", payload(COMMIT, g.repo), g.repo, {**g.env, gate_trust.ENV_FILE: str(own)})
        assert rc == 2 and "not in your trusted list" in err and g.started() == []
        outside = tmp_path / "outside-trusted"
        outside.write_text(os.path.realpath(g.repo) + "\n")
        monkeypatch.setenv(gate_trust.ENV_FILE, str(outside))
        assert gate_trust.is_trusted(os.path.realpath(g.repo), common)  # a list outside the repository still works
    finally:
        g.close()
