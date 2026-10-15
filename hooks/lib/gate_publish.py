"""Which commits a `git push` / `gh pr create` publishes: the tip of every ref it names, as trees.

The push gate used to judge HEAD's tree whatever the command published, so `git push origin feat`,
`feat:main`, `--all` or `gh pr create --head feat` passed on a green HEAD with a failing `feat`. A push
is judged by the tree of EVERY tip it publishes (gate_state.check, per tip).

Resolution, from the words of the command (gate_actions.push_publish):

  --all / --branches / --mirror   every local branch (mirror: the remote-tracking refs too)
  refspec  `src`, `+src`, `src:dst`   the commit `src` names (a branch, HEAD, a sha, HEAD~2); a glob in
                                      `src` expands over refs; `:dst` deletes and `refs/tags/*` is a tag:
                                      neither publishes a commit
  no refspec                      what git would push: `remote.<remote>.push` when set; with
                                  `push.default=matching`, every local branch (the safe superset of
                                  "matching"); else the current branch. A detached HEAD publishes nothing
                                  nameable: refused with the reason
  gh pr create                    `--head [owner:]branch`, else the current branch

Anything that does not resolve to a commit raises ``Unresolvable`` with the reason: the hook denies
(closed by default) instead of judging a tree it was not asked about. No call here touches the network
or the working tree (gate_git).
"""
from __future__ import annotations

import fnmatch
from typing import NamedTuple

import gate_git as gitq


class Unresolvable(Exception):
    """A published ref cannot be resolved to a commit; the message is the reason shown to the user."""


class Tip(NamedTuple):
    name: str  # as the user wrote it (a branch without `refs/heads/`), for messages
    commit: str
    tree: str
    base: str | None  # the tree of the tip's first parent, the tree the change is measured from


def _lines(top: str, *args: str) -> list:
    out = gitq.git(top, *args)
    if out.returncode != 0:
        raise Unresolvable(f"git {args[0]} failed: {out.stderr.strip()[:200]}")
    return [line for line in out.stdout.splitlines() if line]


def _refs(top: str, *prefixes: str) -> list:
    return _lines(top, "for-each-ref", "--format=%(refname)", *prefixes)


def _tip(top: str, name: str, rev: str) -> Tip:
    out = gitq.git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    commit = out.stdout.strip()
    if out.returncode != 0 or not gitq.TREE_RE.match(commit):
        raise Unresolvable(f"cannot resolve {name!r} to a commit in {top}: the tree being published cannot be judged")
    tree = gitq.tree_of(top, commit)
    if tree is None:
        raise Unresolvable(f"cannot read the tree of {name!r} ({commit[:12]})")
    return Tip(name.removeprefix("refs/heads/"), commit, tree, gitq.tree_of(top, f"{commit}^"))


def _current_branch(top: str) -> str:
    out = gitq.git(top, "symbolic-ref", "--quiet", "HEAD")
    if out.returncode != 0:
        raise Unresolvable("HEAD is detached and no ref was named: nothing to resolve the push to; name the ref")
    return out.stdout.strip()


def _config(top: str, key: str) -> list:
    out = gitq.git(top, "config", "--get-all", key)
    return [line for line in out.stdout.splitlines() if line] if out.returncode == 0 else []


def _remote_of(top: str, publish: dict) -> str:
    if publish["remote"]:
        return publish["remote"]
    branch = _current_branch(top)
    configured = _config(top, f"branch.{branch.removeprefix('refs/heads/')}.remote")
    return configured[0] if configured else "origin"


def _expand(top: str, spec: str) -> list:
    """The local sides a refspec names: a glob expands over all refs, anything else stands for itself."""
    src = spec.lstrip("+").partition(":")[0]
    if not src or src.startswith("refs/tags/"):
        return []
    if any(c in src for c in "*?["):
        return [r for r in _refs(top) if fnmatch.fnmatchcase(r, src)]
    return [src]


def _default_specs(top: str, publish: dict) -> list:
    configured = _config(top, f"remote.{_remote_of(top, publish)}.push")
    if configured:
        return configured
    if _config(top, "push.default") == ["matching"]:
        return _refs(top, "refs/heads")
    return [_current_branch(top)]


def _names(top: str, publish: dict) -> list:
    """The local ref names (or revs) the command publishes."""
    if publish["gh"]:
        head = publish["gh_head"]
        return [f"refs/heads/{head.rpartition(':')[2]}"] if head else [_current_branch(top)]
    if publish["all"] or publish["mirror"]:
        return _refs(top, "refs/heads") + (_refs(top, "refs/remotes") if publish["mirror"] else [])
    specs = publish["specs"] or _default_specs(top, publish)
    names: list = []
    for spec in specs:
        names += _expand(top, spec)
    return names


def resolve(top: str, publish: dict) -> list:
    """The tips ``publish`` (gate_actions.push_publish / gh) would publish, deduplicated by commit.

    Post: every returned Tip has a tree; an empty list means the command publishes no commit (tags, deletions).
    Raises Unresolvable when a named ref is not a commit.
    """
    tips: dict = {}
    for name in _names(top, publish):
        tip = _tip(top, name, name)
        tips.setdefault(tip.commit, tip)
    return list(tips.values())
