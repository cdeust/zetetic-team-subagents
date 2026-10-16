"""Which commits a `git push` / `gh pr create` publishes: the tip of every ref it names, as trees.

The push gate used to judge HEAD's tree whatever the command published, so `git push origin feat`,
`feat:main`, `--all` or `gh pr create --head feat` passed on a green HEAD with a failing `feat`. A push
is judged by the tree of EVERY tip it publishes (gate_state.check, per tip).

Resolution, from the words of the command (gate_pushargs.publish):

  --all / --branches / --mirror   every local branch (mirror: the remote-tracking refs too)
  refspec  `src`, `+src`, `src:dst`   the commit `src` names (a branch, HEAD, a sha, HEAD~2, a TAG: `src` is
                                      resolved whatever `dst` is, so `refs/tags/t:refs/heads/main` publishes the
                                      commit behind `t`); a glob in `src` expands over refs; `:dst` deletes and
                                      publishes nothing
  tags      `--tags`, a refspec whose `dst` is `refs/tags/...`, `tag NAME`: the commit behind each tag, unless the
            remote already has it (a remote-tracking ref of the remote reaches it); a tag that is not a commit
            publishes none. `--follow-tags` (or `push.followTags=true`): the annotated tags whose commit is an ancestor of a pushed tip.
            `--tags` without a refspec pushes tags only, as git does: no current-branch default
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
import gate_pushargs as pushargs


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


class _Ref(NamedTuple):
    name: str  # a ref or a revision, as git would resolve it
    tag: str | None  # "tag v1" when it is published as a tag (the remote may have the commit already), else None


def _tag_label(name: str) -> str:
    return "tag " + name.removeprefix("refs/tags/")


def _expand(top: str, spec: pushargs.Refspec) -> list:
    """The local sides a refspec names: a glob expands over all refs, anything else stands for itself."""
    if spec.deletes:
        return []
    if any(c in spec.src for c in "*?["):
        return [_Ref(r, _tag_label(r) if spec.to_tag else None) for r in _refs(top) if fnmatch.fnmatchcase(r, spec.src)]
    return [_Ref(spec.src, _tag_label(spec.dst) if spec.to_tag else None)]


def _default_specs(top: str, publish: dict) -> list:
    configured = _config(top, f"remote.{_remote_of(top, publish)}.push")
    if configured:
        return configured
    if _config(top, "push.default") == ["matching"]:
        return _refs(top, "refs/heads")
    return [_current_branch(top)]


def _branch_names(top: str, publish: dict) -> list:
    """The refs (or revisions) the command publishes, not counting `--tags`."""
    if publish["gh"]:
        head = publish["gh_head"]
        return [_Ref(f"refs/heads/{head.rpartition(':')[2]}" if head else _current_branch(top), None)]
    if publish["all"] or publish["mirror"]:
        return [_Ref(r, None) for r in _refs(top, "refs/heads") + (_refs(top, "refs/remotes") if publish["mirror"] else [])]
    words = publish["specs"] or ([] if publish["tags"] else _default_specs(top, publish))
    names: list = []
    for spec in pushargs.refspecs(words):
        names += _expand(top, spec)
    return names


def _commit_of(top: str, rev: str) -> str | None:
    """The commit ``rev`` peels to, or None when it is not one (a tag of a blob or a tree)."""
    out = gitq.git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    commit = out.stdout.strip()
    return commit if out.returncode == 0 and gitq.TREE_RE.match(commit) else None


def _remote_name(top: str, publish: dict) -> str:
    try:
        return _remote_of(top, publish)
    except Unresolvable:  # FAILS_ON: a detached HEAD and no remote named; then the conventional name stands in
        return "origin"


def _on_remote(top: str, commit: str, remote: str) -> bool:
    """True when a remote-tracking ref of ``remote`` reaches ``commit``: the remote has it (as of the last fetch)."""
    out = gitq.git(top, "rev-list", "--max-count=1", commit, "--not", f"--remotes={remote}")
    return out.returncode == 0 and not out.stdout.strip()


def _all_tags(top: str) -> list:
    return [_Ref(r, _tag_label(r)) for r in _refs(top, "refs/tags")]


def _follows_tags(top: str, publish: dict) -> bool:
    """`--follow-tags` as written, else `push.followTags` (a boolean in the configuration); `gh` never follows."""
    if publish["gh"]:
        return False
    if publish["follow_tags"] is not None:
        return publish["follow_tags"]
    out = gitq.git(top, "config", "--type=bool", "--get", "push.followTags")
    return out.returncode == 0 and out.stdout.strip() == "true"


def _followed_tags(top: str, tips: list) -> list:
    """The annotated tags whose commit is an ancestor of (or is) a pushed tip: what `--follow-tags` pushes."""
    found = []
    for line in _lines(top, "for-each-ref", "--format=%(objecttype) %(refname)", "refs/tags"):
        kind, _, ref = line.partition(" ")
        commit = _commit_of(top, ref) if kind == "tag" else None
        if commit and any(gitq.git(top, "merge-base", "--is-ancestor", commit, t.commit).returncode == 0 for t in tips):
            found.append(_Ref(ref, _tag_label(ref)))
    return found


def _merge(top: str, refs: list, remote: str, into: dict) -> None:
    """Add the tip of each ref to ``into`` (commit -> [names, Tip]); a tag whose commit the remote has adds none."""
    for ref in refs:
        if ref.tag is None:
            tip = _tip(top, ref.name, ref.name)
            label = tip.name
        else:
            commit = _commit_of(top, ref.name)
            if commit is None or _on_remote(top, commit, remote):
                continue
            tip, label = _tip(top, ref.name, ref.name), ref.tag
        found = into.setdefault(tip.commit, [[], tip])
        if label not in found[0]:
            found[0].append(label)


def resolve(top: str, publish: dict) -> list:
    """The tips ``publish`` (gate_pushargs.publish / gh) would publish, deduplicated by commit.

    Post: every returned Tip has a tree; a commit named twice is one Tip named by all its names; an empty list
    means the command publishes no commit (deletions, tags the remote has). Raises Unresolvable when a named
    ref is not a commit.
    """
    into: dict = {}
    remote = _remote_name(top, publish)
    _merge(top, _branch_names(top, publish), remote, into)
    extra = _all_tags(top) if publish["tags"] else []
    if _follows_tags(top, publish):
        extra += _followed_tags(top, [found[1] for found in into.values()])
    _merge(top, extra, remote, into)
    return [tip._replace(name=", ".join(names)) for names, tip in into.values()]
