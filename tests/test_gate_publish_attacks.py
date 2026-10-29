"""What a push publishes (PR #169, round 3, blocking items 2 and 3, and the tags decision).

Each attack passes at ea62083 (the push of a failing commit is allowed) and must be refused here. Real
repository, real hook as a subprocess, a real bare remote for "already published". Event-synchronised only.

  2  tag-to-branch: `refs/tags/tbad:refs/heads/main` and `refs/tags/*:refs/heads/*` publish the commit behind the tag
  3  `-odebug`, `-on`: the rest of a short-option cluster is the value of `-o`, not the flags d and n
  t  `--tags`, `--follow-tags`, an explicit tag refspec: the tagged commits not yet on the remote need a push record
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

from gate_support import GIT_ENV, git
from test_gate_attacks import FAIL_IF_BAD, gate, push_green_main_with_failing_feat, settle  # noqa: F401  (fixture)


def tag_the_failing_commit(g, name: str = "tbad", *flags: str) -> None:
    git(g.repo, "tag", *flags, name, "feat")


# --------------------------------------------------------------------- 2. tag to branch


@pytest.mark.parametrize("command,named", [
    ("git push origin refs/tags/tbad:refs/heads/main", "[refs/tags/tbad]"),
    ("git push origin +refs/tags/tbad:refs/heads/main", "[refs/tags/tbad]"),
    ("git push origin tbad:refs/heads/main", "[tbad]"),
    ("git push origin 'refs/tags/*:refs/heads/*'", "[refs/tags/tbad]"),
    ("git push origin refs/tags/tbad:refs/heads/other", "[refs/tags/tbad]"),
    ("git push origin refs/tags/tbad:refs/tags/copy", "[tag copy]"),
    ("git push origin refs/tags/tbad", "[tag tbad]"),
    ("git push origin tag tbad", "[tag tbad]"),
    ("git push origin feat:refs/tags/viafeat", "[tag viafeat]"),
])
def test_a_tag_on_a_failing_commit_cannot_reach_a_branch_or_a_tag_unjudged(gate, command, named):
    push_green_main_with_failing_feat(gate)
    tag_the_failing_commit(gate)
    rc, _, err = gate.gate(command)
    assert rc == 2 and named in err and "verification" in err, (command, err)


def test_deleting_a_tag_is_not_judged(gate):
    push_green_main_with_failing_feat(gate)
    tag_the_failing_commit(gate)
    for command in ("git push origin :refs/tags/tbad", "git push --delete origin tbad"):
        assert gate.gate(command) == (0, "", ""), command


# --------------------------------------------------------------- 3. option clusters like git


@pytest.mark.parametrize("command", [
    "git push -odebug origin feat",
    "git push -on origin feat",
    "git push -od origin feat",
    "git push -vodebug origin feat",
    "git push -ond origin feat",
    "git push -o d origin feat",
    "git push -o n origin feat",
    "git push -vo n origin feat",
    "git push --push-option=d origin feat",
    "git push --push-option n origin feat",
    "git push --recurse-submodules check origin feat",
    "git push --repo origin feat",
    "git push --exec x origin feat",
])
def test_the_value_of_an_option_is_not_read_as_a_flag(gate, command):
    push_green_main_with_failing_feat(gate)
    rc, _, err = gate.gate(command)
    assert rc == 2 and "[feat]" in err, (command, err)


@pytest.mark.parametrize("command", [
    "git push -n origin feat", "git push -d origin feat", "git push -vn origin feat", "git push -nv origin feat",
    "git push -o d -n origin feat", "git push -vod -n origin feat", "git push --dry-run origin feat",
    "git push --dry origin feat", "git push --del origin feat", "git push --delete origin feat",
])
def test_a_dry_run_or_a_deletion_still_publishes_nothing(gate, command):
    push_green_main_with_failing_feat(gate)
    assert gate.gate(command) == (0, "", ""), command


def options_taking_a_value(help_text: str) -> tuple[set, set]:
    """(short letters, long names) of the options `git push -h` shows with a value: `<arg>` or `(a|b)`."""
    shorts: set = set()
    longs: set = set()
    for line in help_text.splitlines():
        match = re.match(r"\s+(?:-(\w), )?--(?:\[no-\])?([\w-]+)(?:\[=\S+\])?( <[^>]+>| \([^)]+\))?(?:\s|$)", line)
        if match and match.group(3):
            longs.add(match.group(2))
            if match.group(1):
                shorts.add(match.group(1))
    return shorts, longs


def test_the_options_that_take_a_value_are_the_ones_this_git_documents():
    import gate_pushargs  # noqa: E402

    out = subprocess.run(["git", "push", "-h"], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    shorts, longs = options_taking_a_value(out.stderr + out.stdout)
    assert shorts == set(gate_pushargs.SHORT_WITH_VALUE) and longs == set(gate_pushargs.LONG_WITH_VALUE), (shorts, longs)


# ------------------------------------------------------------------------------ tags


@pytest.fixture
def remote(gate):
    """A bare remote called origin; main is published there (with real git: the hook is not involved)."""
    bare = gate.tmp / "remote.git"
    git(gate.tmp, "init", "-q", "--bare", str(bare))
    git(gate.repo, "remote", "add", "origin", str(bare))
    git(gate.repo, "push", "-q", "origin", "main")
    return bare


def commit_bad_then_fix(g, tag_flags: tuple, tag: str) -> None:
    """main: X (adds the failing bad.txt, tagged) then T (removes it). T gets a green push record."""
    (g.repo / "bad.txt").write_text("fails\n")
    git(g.repo, "add", "bad.txt")
    git(g.repo, "commit", "-q", "-m", "x", "--no-verify")
    git(g.repo, "tag", *tag_flags, tag, "HEAD")
    git(g.repo, "rm", "-q", "bad.txt")
    git(g.repo, "commit", "-q", "-m", "t", "--no-verify")
    assert g.gate("git push origin main")[0] == 2
    assert settle(g)["state"] == "done"
    assert g.gate("git push origin main") == (0, "", "")


@pytest.mark.parametrize("command", ["git push --tags", "git push origin --tags", "git push --tags origin",
                                     "git push --tags origin main", "git push origin main --tags"])
def test_push_tags_needs_a_push_record_for_each_unpublished_tagged_commit(gate, remote, command):
    commit_bad_then_fix(gate, ("-a", "-m", "m"), "abad")
    rc, _, err = gate.gate(command)
    assert rc == 2 and "[tag abad]" in err and "verification" in err, (command, err)


def test_push_tags_names_every_tag_that_blocks(gate, remote):
    commit_bad_then_fix(gate, (), "lbad")
    git(gate.repo, "tag", "second", "HEAD~1")
    rc, _, err = gate.gate("git push --tags")
    assert rc == 2 and "lbad" in err and "second" in err


def test_follow_tags_judges_the_annotated_tags_behind_the_pushed_commits(gate, remote):
    commit_bad_then_fix(gate, ("-a", "-m", "m"), "abad")
    rc, _, err = gate.gate("git push --follow-tags origin main")
    assert rc == 2 and "[tag abad]" in err
    assert gate.gate("git push origin main") == (0, "", "")  # without the option the tag is not published


def test_follow_tags_ignores_lightweight_tags_and_tags_that_git_would_not_follow(gate, remote):
    commit_bad_then_fix(gate, (), "lbad")  # a lightweight tag: --follow-tags does not push it
    assert gate.gate("git push --follow-tags origin main") == (0, "", "")
    git(gate.repo, "checkout", "-q", "-b", "feat2", "main~2")
    (gate.repo / "bad.txt").write_text("fails\n")
    git(gate.repo, "add", "bad.txt")
    git(gate.repo, "commit", "-q", "-m", "elsewhere", "--no-verify")
    git(gate.repo, "tag", "-a", "-m", "m", "elsewhere", "HEAD")  # annotated, unpublished, but not reachable from main
    git(gate.repo, "checkout", "-q", "main")
    assert gate.gate("git push --follow-tags origin main") == (0, "", "")


def test_a_tag_on_a_commit_the_remote_already_has_is_not_judged(gate, remote):
    assert gate.gate("git push origin main")[0] == 2  # the push of main itself (the default of two commands below)
    assert settle(gate)["state"] == "done"
    git(gate.repo, "tag", "-a", "-m", "m", "released", "main")  # main is on origin (the fixture pushed it)
    for command in ("git push --tags", "git push origin --tags", "git push --follow-tags", "git push origin refs/tags/released"):
        assert gate.gate(command) == (0, "", ""), command


def test_push_tags_alone_publishes_no_branch(gate, remote):
    """`git push --tags` pushes tags only: a failing branch that is not tagged is not published by it."""
    push_green_main_with_failing_feat(gate)
    assert gate.gate("git push --tags") == (0, "", "")
