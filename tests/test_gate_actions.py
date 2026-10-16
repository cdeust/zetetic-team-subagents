"""hooks/lib/gate_actions.py + gate_shell.py: which gated invocations does a Bash command contain.

Pure parsing (ported from the ~/.claude/hooks gate-proof tests): mentions are not invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_actions as ga  # noqa: E402
import gate_pushargs as pushargs  # noqa: E402
import gate_shell as sh  # noqa: E402

BASE = "/repo"


def kinds(command: str, base: str = BASE) -> list:
    return [(a["kind"], a["dir"]) for a in ga.actions(command, base)]


@pytest.mark.parametrize("command", [
    'echo "git commit"', "echo 'git push origin main'", "git log --grep commit",
    "git log --oneline -5 | grep 'git commit'", "git commit-tree HEAD^{tree} -m x", "git push-options",
    "git status", "git diff --cached", "grep -rn 'gh pr create' .", "# git commit -m x",
    "cat <<EOF\ngit commit -m x\ngit push origin main\ngh pr create\nEOF",
    "cat <<'EOF' > notes.txt\nfirst\ngit commit -a\nEOF", "cat <<-EOF\n\tgh pr create\n\tEOF",
    'echo "run: git commit" && ls', "ls git-commit-helper", "gh pr view 12", "gh pr list --search 'pr create'",
    "git commit --dry-run", "git push --delete origin feat",
    "git push -d origin feat", "git push origin :feat", "git push origin :refs/tags/v1",
    "git push -n origin main", "gh pr create --help", "gh pr create -h",
])
def test_mentions_and_non_publishing_calls_are_not_gated(command):
    assert [k for k, _ in kinds(command) if k != "stage"] == []


@pytest.mark.parametrize("command,cwd,expected", [
    ("git commit -m x", BASE, ("commit", BASE)),
    ("cd /elsewhere && git commit -m x", BASE, ("commit", "/elsewhere")),
    ("git -C /other commit -m x", BASE, ("commit", "/other")),
    ("git -C /other -c user.name=x --no-pager commit -m x", BASE, ("commit", "/other")),
    ("env FOO=1 git commit -m x", BASE, ("commit", BASE)),
    ("FOO=1 BAR=2 git commit -m x", BASE, ("commit", BASE)),
    ("true; git commit -m x", BASE, ("commit", BASE)),
    ("echo hi | tee /dev/null && git commit -m x", BASE, ("commit", BASE)),
    ("sudo -u nobody git commit -m x", BASE, ("commit", BASE)),
    ("git push origin main", BASE, ("push", BASE)),
    ("git push -u origin main", BASE, ("push", BASE)),
    ("gh pr create --fill", BASE, ("push", BASE)),
    ("gh -R o/r pr create", BASE, ("push", BASE)),
    ("cd /w && gh pr create", BASE, ("push", "/w")),
    ("git commit -m \"docs: explain gh pr create and git push\"", BASE, ("commit", BASE)),
    ("git commit -F - <<'EOF'\nfeat: x\n\nrun git push then gh pr create\nEOF", BASE, ("commit", BASE)),
])
def test_invocations_are_found_in_the_right_directory(command, cwd, expected):
    assert kinds(command, cwd) == [expected]


@pytest.mark.parametrize("command", [
    "git commit -a -m x", "git commit -am x", "git commit --all -m x", "git commit -m x -- a.txt",
    "git commit -m x a.txt", "git commit --only a.txt", "git commit -i a.txt -m x", "git commit -p",
    "git add . && git commit -m x", "git rm a && git commit -m x",
])
def test_commits_whose_index_cannot_be_judged_carry_a_reason(command):
    commit = [a for a in ga.actions(command, BASE) if a["kind"] == "commit"][0]
    assert commit["why"]


@pytest.mark.parametrize("command", [
    'git commit -m "-a fix --all"', "git commit -m 'use -am here'", "git commit -F msg.txt",
    "git commit -m x 2>&1", "git commit -S -m x", "git commit --amend --no-edit", "git commit -m x -s",
])
def test_message_text_and_harmless_flags_are_not_index_flags(command):
    commit = [a for a in ga.actions(command, BASE) if a["kind"] == "commit"][0]
    assert commit["why"] == []


def test_amend_and_allow_empty_are_reported():
    commit = ga.actions("git commit --amend --allow-empty -m x", BASE)[0]
    assert (commit["amend"], commit["allow_empty"]) == (True, True)


@pytest.mark.parametrize("command", ["git add a", "git rm a", "git mv a b", "git restore --staged a",
                                     "git reset a", "git -C /o add .", "cd /o && git add ."])
def test_index_changers_are_reported_as_stage(command):
    assert [k for k, _ in kinds(command)] == ["stage"]


def test_lexer_resolves_quotes_heredocs_and_redirections():
    words = lambda cmd: [w for kind, w in sh.lex(cmd) if kind == "w"]  # noqa: E731
    assert words("echo 'a b' \"c d\" e\\ f") == ["echo", "a b", "c d", "e f"]
    assert words("cmd 2>&1 > out.txt arg") == ["cmd", "arg"]
    assert words("cat <<EOF\nbody git commit\nEOF\nnext") == ["cat", "next"]
    assert words("cat <<<word tail") == ["cat", "tail"]
    assert words("a \\\nb") == ["a", "b"]  # line continuation
    assert words("a # comment git commit\nb") == ["a", "b"]
    assert words("echo $(git status)") == ["echo", "git", "status"]


def test_segments_and_prefix_stripping():
    segs = sh.segments(sh.lex("FOO=1 env -u X git add . && time sudo -u me git commit; ls"))
    assert [sh.strip_prefix(s) for s in segs] == [["git", "add", "."], ["git", "commit"], ["ls"]]


def commit_of(command: str) -> dict:
    return [a for a in ga.actions(command, BASE) if a["kind"] == "commit"][0]


def test_a_plain_commit_is_neither_an_amend_nor_allow_empty():
    plain = commit_of("git commit -m x")
    assert (plain["amend"], plain["allow_empty"], plain["why"]) == (False, False, [])


@pytest.mark.parametrize("command", ["git commit -s -m x", "git commit -v -m x", "git commit --signoff -m x"])
def test_flags_without_an_argument_do_not_swallow_the_next_word(command):
    assert commit_of(command)["why"] == []


def test_an_option_with_an_inline_value_does_not_swallow_the_next_word():
    assert commit_of("git commit --message=x --amend")["amend"] is True
    assert commit_of("git commit --message x --amend")["amend"] is True  # separate value consumed, flag still seen


def test_a_staging_reason_comes_first():
    why = commit_of("git add . && git commit -a -m x")["why"]
    assert why[0].startswith("stages") and len(why) == 2


@pytest.mark.parametrize("command", ["git push", "git push origin", "git push --force origin main",
                                     "git push --force-with-lease", "git push -u origin main",
                                     "git push --repo=x origin main", "git push --push-option ci.skip origin main"])
def test_pushes_that_can_publish_are_gated(command):
    assert [k for k, _ in kinds(command)] == ["push"]


@pytest.mark.parametrize("command", ["git push --push-option ci.skip origin :feat", "git push -o ci.skip origin :feat",
                                     "git push --push-option=ci.skip origin :feat"])
def test_push_option_values_are_not_refspecs(command):
    assert kinds(command) == []


def test_gh_pr_create_with_a_trailing_word_and_flags_is_gated():
    assert [k for k, _ in kinds("gh pr create extra")] == ["push"]
    assert [k for k, _ in kinds("gh pr create --title t --body b")] == ["push"]


def test_cd_without_a_target_goes_home_and_cd_dash_stays():
    import os
    assert kinds("cd && git commit -m x") == [("commit", os.path.expanduser("~"))]
    assert kinds("cd - && git commit -m x", BASE) == [("commit", BASE)]
    assert kinds("pushd /w && git commit -m x") == [("commit", "/w")]


def test_a_git_with_no_subcommand_or_a_dangling_option_is_ignored():
    assert ga.actions("git", BASE) == [] and ga.actions("git -C", BASE) == [] and ga.actions("git -C /d", BASE) == []


def test_global_options_with_a_value_are_skipped_whole():
    assert kinds("git -c a=b commit -m x") == [("commit", BASE)]
    assert kinds("git --git-dir /d --work-tree /w commit -m x") == [("commit", BASE)]
    assert kinds("git -C /one -C /two commit -m x") == [("commit", "/two")]


def words(command: str) -> list:
    return [w for kind, w in sh.lex(command) if kind == "w"]


def test_lexer_operators_without_spaces_and_here_strings():
    assert words("a;b|c&d") == ["a", "b", "c", "d"]
    assert words("(a)b") == ["a", "b"]
    assert words("cat <<<x tail") == ["cat", "tail"]  # a one-character here-string is still a redirection target
    assert words("a#b") == ["a#b"]  # `#` inside a word is not a comment
    assert words("a # comment") == ["a"]


def test_lexer_unterminated_constructs_end_at_the_end_of_input():
    assert words("echo 'open") == ["echo", "open"]
    assert words('echo "open') == ["echo", "open"]
    assert words('echo "a\\"b" c') == ["echo", 'a"b', "c"]
    assert words('echo "a\\') == ["echo", "a\\"]
    assert words("echo a\\") == ["echo", "a"]
    assert words("cat <<EOF\nbody") == ["cat"]
    assert words("cat <<EOF\nbody\nEOF") == ["cat"]
    assert words("cat <<EOF") == ["cat"]


def test_lexer_dash_heredoc_with_spaces_before_the_delimiter():
    assert words("cat <<- EOF\n\tbody git commit\n\tEOF\nnext") == ["cat", "next"]
    assert words("cat <<   EOF\nbody\nEOF\nnext") == ["cat", "next"]


def test_wrapper_flags_consume_only_what_they_take():
    assert sh.strip_prefix(["env", "-i", "git", "commit"]) == ["git", "commit"]
    assert sh.strip_prefix(["env", "-u", "X", "git", "commit"]) == ["git", "commit"]
    assert sh.strip_prefix(["sudo", "-E", "git", "commit"]) == ["git", "commit"]
    assert sh.strip_prefix(["git", "-u", "x"]) == ["git", "-u", "x"]  # `-u` after the real command is its own


def test_a_short_option_cluster_ending_in_o_is_not_confused_with_a_single_dash_o():
    assert kinds("git push -u origin :feat") == []  # `-u` takes no value: `origin` is the remote, `:feat` a deletion


def test_lexer_one_character_arguments_after_escapes_quotes_and_redirections():
    assert words("a\\b") == ["ab"]
    assert words("a '' b") == ["a", "", "b"]
    assert words('"\\"') == ['"']  # unterminated double quote ending in an escaped quote
    assert words("cat <<-EOF\n\tx\n\tEOF\nnext") == ["cat", "next"]
    assert words("cmd >x arg") == ["cmd", "arg"]
    assert words("cmd >>x arg 2>&1") == ["cmd", "arg"]


def publish(command: str) -> dict:
    (act,) = [a for a in ga.actions(command, BASE) if a["kind"] == "push"]
    return act["publish"]


@pytest.mark.parametrize("command,specs,remote", [
    ("git push", [], None),
    ("git push origin", [], "origin"),
    ("git push origin feat", ["feat"], "origin"),
    ("git push -u origin feat:main", ["feat:main"], "origin"),
    ("git push origin +feat:refs/heads/x HEAD", ["+feat:refs/heads/x", "HEAD"], "origin"),
    ("git push --force-with-lease origin feat", ["feat"], "origin"),
    ("git push -o ci.skip origin feat", ["feat"], "origin"),
    ("git push --repo=origin feat", ["feat"], "origin"),  # --repo names the remote: every positional is a refspec
    ("git push --repo origin feat", ["feat"], "origin"),
    ("git push --recurse-submodules check origin feat", ["feat"], "origin"),
    ("git push -odebug origin feat", ["feat"], "origin"),
    ("git push -vo debug origin feat", ["feat"], "origin"),
    ("git push -- origin feat", ["feat"], "origin"),
])
def test_a_push_names_the_refs_it_publishes(command, specs, remote):
    found = publish(command)
    assert (found["specs"], found["remote"]) == (specs, remote)
    assert (found["all"], found["mirror"], found["gh"]) == (False, False, False)


@pytest.mark.parametrize("command,flag", [("git push --all origin", "all"), ("git push --branches origin", "all"),
                                          ("git push --mirror origin", "mirror")])
def test_all_and_mirror_publish_every_branch(command, flag):
    assert publish(command)[flag] is True


@pytest.mark.parametrize("args,expected", [
    (["--all", "--tags", "origin"], False), (["--mirror", "origin"], False),
    (["--repo", "origin", "refs/tags/v1"], False),  # a tag publishes the commit behind it (gate_publish judges it)
    (["--repo", "origin", ":refs/tags/v1"], True),  # --repo: no positional remote to skip; a deletion publishes nothing
    (["origin", "--tags"], False), (["--follow-tags", "origin", "main"], False), (["origin", "tag", "v1"], False),
    (["origin", ":feat", "main"], False), (["origin", ":feat", ":other"], True), (["--delete", "origin", "feat"], True),
    (["-d", "origin", "feat"], True), (["-n", "origin", "feat"], True), (["-on", "origin", "feat"], False),
    (["-odebug", "origin", "feat"], False), (["-vod", "origin", "feat"], False), (["-o", "d", "origin", "feat"], False),
    (["-o", "d", "-n", "origin", "feat"], True), (["--dry", "origin", "feat"], True), (["--del", "origin", "feat"], True),
    (["--dele", "--no-delete", "origin", "feat"], False),
])
def test_what_publishes_no_commit(args, expected):
    assert pushargs.publishes_no_commit(args) is expected


@pytest.mark.parametrize("command,head", [
    ("gh pr create", None), ("gh pr create --fill", None), ("gh pr create --head feat", "feat"),
    ("gh pr create --head=feat", "feat"), ("gh pr create -H feat", "feat"), ("gh pr create -Hfeat", "feat"),
    ("gh pr create -R o/r --head me:feat --title t", "me:feat"), ("gh pr create --head", ""),
])
def test_gh_pr_create_names_its_head_branch(command, head):
    found = publish(command)
    assert found["gh"] is True and found["gh_head"] == head and found["specs"] == []


def test_the_gh_publish_record_is_exactly_a_head_branch_and_nothing_else():
    assert publish("gh pr create --head x") == {"all": False, "mirror": False, "tags": False, "follow_tags": None,
                                                "remote": None, "specs": [], "gh_head": "x", "gh": True}
    assert publish("git push origin feat") == {"all": False, "mirror": False, "tags": False, "follow_tags": None,
                                               "remote": "origin", "specs": ["feat"], "gh_head": None, "gh": False}


@pytest.mark.parametrize("command", ["git push --tags", "git push origin --tags", "git push origin refs/tags/v1",
                                     "git push origin tag v1", "git push --follow-tags", "git push origin refs/tags/t:refs/heads/main"])
def test_a_push_that_can_publish_a_tagged_commit_is_a_push_to_judge(command):
    assert [k for k, _ in kinds(command) if k != "stage"] == ["push"]


def test_tags_and_follow_tags_are_named_in_the_publish_record():
    assert (publish("git push --tags")["tags"], publish("git push --tags")["follow_tags"]) == (True, None)
    assert (publish("git push --follow-tags origin")["tags"], publish("git push --follow-tags origin")["follow_tags"]) == (False, True)
    assert publish("git push --no-tags origin feat")["tags"] is False
    assert publish("git push --no-follow-tags origin feat")["follow_tags"] is False
