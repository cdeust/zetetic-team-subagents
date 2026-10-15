"""hooks/lib/gate_publish.py and gate_rules.py: which commits a push publishes, and the rules that judge a tree.

In-process against a real repository; no worker is started and nothing waits.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from gate_support import git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_actions as ga  # noqa: E402
import gate_config as cfg  # noqa: E402
import gate_publish as pub  # noqa: E402
import gate_rules as rules  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    for n in (1, 2):
        (path / "a").write_text(f"{n}\n")
        git(path, "add", "a")
        git(path, "commit", "-q", "-m", f"c{n}")
    git(path, "checkout", "-q", "-b", "feat")
    (path / "a").write_text("feat\n")
    git(path, "commit", "-q", "-am", "feat")
    git(path, "tag", "v1")
    git(path, "checkout", "-q", "main")
    return path


def publish_of(command: str) -> dict:
    (act,) = [a for a in ga.actions(command, "/x") if a["kind"] == "push"]
    return act["publish"]


def resolve(repo: Path, command: str) -> dict:
    return {tip.name: tip for tip in pub.resolve(str(repo), publish_of(command))}


def tree(repo: Path, rev: str) -> str:
    return git(repo, "rev-parse", f"{rev}^{{tree}}")


def test_a_named_branch_is_resolved_to_its_tip_its_tree_and_its_parents_tree(repo):
    (tip,) = resolve(repo, "git push origin feat").values()
    assert (tip.name, tip.tree, tip.base) == ("feat", tree(repo, "feat"), tree(repo, "feat^"))
    assert tip.commit == git(repo, "rev-parse", "feat")


@pytest.mark.parametrize("command,names", [
    ("git push", ["main"]),
    ("git push origin", ["main"]),
    ("git push origin HEAD", ["HEAD"]),
    ("git push origin HEAD~1", ["HEAD~1"]),
    ("git push origin feat:main", ["feat"]),
    ("git push origin +feat:x", ["feat"]),
    ("git push --all", ["feat", "main"]),
    ("git push --mirror", ["feat", "main"]),
    ("git push origin 'refs/heads/*:refs/heads/*'", ["feat", "main"]),
    ("git push origin refs/heads/feat main", ["feat", "main"]),
    ("gh pr create", ["main"]),
    ("gh pr create --head feat", ["feat"]),
    ("gh pr create --head me:feat", ["feat"]),
])
def test_what_each_command_publishes(repo, command, names):
    assert sorted(resolve(repo, command)) == sorted(names)


def test_two_names_for_one_commit_are_one_tip(repo):
    assert list(resolve(repo, "git push origin main HEAD")) == ["main"]  # first name wins; the commit is judged once


@pytest.mark.parametrize("specs", [[":feat"], ["refs/tags/v1"], ["refs/tags/*:refs/tags/*"], ["+:feat"]])
def test_deletions_and_tags_publish_no_commit(repo, specs):
    assert pub.resolve(str(repo), {**publish_of("git push origin feat"), "specs": specs}) == []


def test_a_name_that_is_not_a_commit_is_unresolvable_with_the_name_in_the_reason(repo):
    with pytest.raises(pub.Unresolvable, match="cannot resolve 'ghost'"):
        pub.resolve(str(repo), publish_of("git push origin ghost"))
    with pytest.raises(pub.Unresolvable, match="cannot resolve 'refs/heads/ghost'"):
        pub.resolve(str(repo), publish_of("gh pr create --head ghost"))


def test_detached_head_and_a_named_ref_or_not(repo):
    git(repo, "checkout", "-q", "--detach")
    with pytest.raises(pub.Unresolvable, match="detached"):
        pub.resolve(str(repo), publish_of("git push"))
    with pytest.raises(pub.Unresolvable, match="detached"):
        pub.resolve(str(repo), publish_of("gh pr create"))
    assert list(resolve(repo, "git push origin HEAD")) == ["HEAD"]  # naming the ref is enough


def test_the_remote_configuration_decides_what_a_bare_push_publishes(repo):
    git(repo, "config", "remote.origin.push", "refs/heads/feat:refs/heads/feat")
    assert list(resolve(repo, "git push origin")) == ["feat"]
    git(repo, "config", "--unset-all", "remote.origin.push")
    git(repo, "config", "branch.main.remote", "up")
    git(repo, "config", "remote.up.push", "feat")
    assert list(resolve(repo, "git push")) == ["feat"]  # the current branch's remote, not `origin`
    git(repo, "config", "--unset-all", "remote.up.push")
    git(repo, "config", "push.default", "matching")
    assert sorted(resolve(repo, "git push")) == ["feat", "main"]
    git(repo, "config", "push.default", "simple")
    assert list(resolve(repo, "git push")) == ["main"]


def test_the_first_commit_has_no_parent_tree(repo):
    git(repo, "checkout", "-q", "--orphan", "root")
    git(repo, "commit", "-q", "-m", "root", "--allow-empty")
    (tip,) = pub.resolve(str(repo), publish_of("git push origin root"))
    assert tip.base is None and tip.tree == tree(repo, "root")


# ----------------------------------------------------------------------------- rules


def commit_files(repo: Path, files: dict, message: str = "x") -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD^{tree}")


def config_text(*names: str, **extra) -> str:
    return json.dumps({"version": 1, "checks": [{"name": n, "argv": ["true"]} for n in names], **extra})


def test_a_tree_without_a_declaration_has_no_rules(repo):
    assert rules.of_tree(str(repo), tree(repo, "main")) is None
    found = rules.effective(str(repo), tree(repo, "main"))
    assert found.sets == [] and found.trusted == tree(repo, "main")


def test_the_rules_are_head_s_plus_the_judged_trees_never_fewer(repo):
    head = commit_files(repo, {".zetetic/gate.json": config_text("old")})
    (repo / ".zetetic" / "gate.json").write_text(config_text("new"))
    git(repo, "add", "-A")
    judged = git(repo, "write-tree")
    found = rules.effective(str(repo), judged)
    assert found.trusted == head
    assert [s.cfg["checks"][0]["name"] for s in found.sets] == ["old", "new"]  # trusted first, then the change's


def test_off_in_the_judged_tree_removes_nothing_and_off_in_head_switches_the_gate_off(repo):
    commit_files(repo, {".zetetic/gate.json": config_text("old")})
    (repo / ".zetetic" / "gate.json").write_text(json.dumps({"version": 1, "off": True}))
    git(repo, "add", "-A")
    judged = git(repo, "write-tree")
    assert [s.cfg["checks"][0]["name"] for s in rules.effective(str(repo), judged).sets] == ["old"]
    off_head = commit_files(repo, {})  # commits the staged off switch: HEAD itself now says off
    assert rules.effective(str(repo), off_head).sets == [] and rules.declared(str(repo)) is False


def test_identical_rules_are_one_rule_set_and_a_digest_is_stable_and_sensitive(repo):
    head = commit_files(repo, {".zetetic/gate.json": config_text("a")})
    one = rules.effective(str(repo), head)
    commit_files(repo, {"b.txt": "x\n"})
    again = rules.effective(str(repo), tree(repo, "HEAD"))
    assert len(one.sets) == 1 and one.digest == again.digest == rules.digest_of(one.sets) and len(one.digest) == 12
    other = rules.effective(str(repo), commit_files(repo, {".zetetic/gate.json": config_text("a", "b")}))
    assert other.digest != one.digest
    assert rules.digest_of([rules.RuleSet("config", {"version": 1}, None)]) != rules.digest_of([rules.RuleSet("legacy", None, "a" * 40)])


def test_a_legacy_script_is_a_rule_set_named_by_its_scripts_tree(repo):
    commit_files(repo, {"scripts/gate.sh": "#!/bin/sh\nexit 0\n"})
    (repo / "scripts" / "gate.sh").chmod((repo / "scripts" / "gate.sh").stat().st_mode | stat.S_IXUSR)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    found = rules.of_tree(str(repo), tree(repo, "HEAD"))
    assert found.kind == "legacy" and found.cfg is None
    assert found.scripts == git(repo, "rev-parse", "HEAD:scripts")
    commit_files(repo, {"scripts/other.sh": "#!/bin/sh\n"})  # another file in scripts/: other rules
    assert rules.of_tree(str(repo), tree(repo, "HEAD")).scripts != found.scripts


def test_with_no_head_the_judged_tree_is_its_own_trusted_tree_and_an_invalid_config_raises(repo, tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    (fresh / ".zetetic").mkdir()
    (fresh / ".zetetic" / "gate.json").write_text(config_text("only"))
    git(fresh, "add", "-A")
    staged = git(fresh, "write-tree")
    found = rules.effective(str(fresh), staged)
    assert found.trusted == staged and len(found.sets) == 1 and rules.declared(str(fresh)) is True
    (fresh / ".zetetic" / "gate.json").write_text("{torn")
    git(fresh, "add", "-A")
    with pytest.raises(cfg.ConfigError):
        rules.effective(str(fresh), git(fresh, "write-tree"))


def test_the_digest_does_not_depend_on_the_order_of_keys():
    one = rules.RuleSet("config", {"version": 1, "checks": [{"name": "a", "argv": ["x"]}]}, None)
    two = rules.RuleSet("config", {"checks": [{"argv": ["x"], "name": "a"}], "version": 1}, None)
    assert rules.digest_of([one]) == rules.digest_of([two])
    assert rules.digest_of([one]) != rules.digest_of([rules.RuleSet("config", {"version": 1, "checks": []}, None)])


def test_a_git_failure_while_listing_refs_is_unresolvable_with_the_command_named(repo, monkeypatch):
    import subprocess
    failing = subprocess.CompletedProcess([], 128, "", "fatal: broken repository\n")
    monkeypatch.setattr(pub.gitq, "git", lambda *a, **k: failing)
    with pytest.raises(pub.Unresolvable, match="git for-each-ref failed: fatal: broken repository"):
        pub.resolve(str(repo), publish_of("git push --all"))
