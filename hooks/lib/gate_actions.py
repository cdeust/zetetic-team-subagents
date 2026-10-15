"""Which gated git/gh invocations does a Bash command contain, and in which directory?

Pure parsing on top of gate_shell: no I/O, no git. ``actions(command, base_cwd)`` returns dicts

  {"kind": "commit", "dir", "why", "amend", "allow_empty"}   `git commit` (why: flags that make the
                                                              index at hook time unreliable)
  {"kind": "push",   "dir", "why": []}                       `git push` that can publish a commit, `gh pr create`
  {"kind": "stage",  "dir"}                                  `git add|rm|mv|...`: the index may have changed

Mentions (in quotes, heredocs, comments, `git commit-tree`, `--dry-run`) are not invocations.
"""
from __future__ import annotations

import os
from typing import Iterator, NamedTuple

import gate_shell as shell

# git subcommands that change the index (chained before a commit, the staged tree is unverifiable).
INDEX_CHANGERS = frozenset(
    {"add", "rm", "mv", "update-index", "apply", "restore", "reset", "stash", "checkout", "switch"}
)
# `git commit` options taking a separate argument.
_COMMIT_LONG_ARG = frozenset(
    {"message", "file", "author", "date", "template", "fixup", "squash", "reuse-message",
     "reedit-message", "cleanup", "pathspec-from-file", "trailer"}
)
_COMMIT_SHORT_ARG = frozenset("mFcCt")
_COMMIT_SHORT_ATTACHED = frozenset("uS")  # optional-argument options: rest of cluster is the value.
_PUSH_LONG_ARG = frozenset({"push-option", "repo", "receive-pack", "exec"})
_GIT_GLOBAL_ARG = frozenset({"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
_COMMIT_INDEX_LONG = ("all", "include", "only", "patch", "interactive")


class _Call(NamedTuple):
    dir: str
    sub: str
    args: list


def _resolve(base: str, target: str) -> str:
    return os.path.normpath(os.path.join(base, os.path.expanduser(target)))


def _commit_long(a: str, info: dict) -> bool:
    """Apply one `--name[=value]` commit option to ``info``; True when it consumes the next word."""
    name, eq, _ = a[2:].partition("=")
    if name in _COMMIT_INDEX_LONG:
        info["why"].append(f"uses --{name}")
    elif name == "pathspec-from-file":
        info["why"].append("uses --pathspec-from-file")
    elif name in ("amend", "allow-empty", "dry-run"):
        info[name.replace("-", "_")] = True
    return name in _COMMIT_LONG_ARG and not eq


def _commit_short(a: str, info: dict) -> bool:
    """Apply one `-xyz` option cluster; True when its last option consumes the next word."""
    cluster = a[1:]
    for k, ch in enumerate(cluster):
        if ch in _COMMIT_SHORT_ARG:
            return k == len(cluster) - 1
        if ch in _COMMIT_SHORT_ATTACHED:
            return False
        if ch in "aAiop":
            info["why"].append(f"uses -{ch}")
    return False


def commit_info(args: list[str]) -> dict:
    """Parse `git commit` arguments: which flags make the index at hook time unreliable."""
    info = {"amend": False, "allow_empty": False, "dry_run": False, "why": []}
    i = 0
    while i < len(args):  # termination: i grows by >= 1 per iteration
        a = args[i]
        i += 1
        if a == "--":
            if i < len(args):
                info["why"].append("commits explicit paths")
            break
        if a.startswith("--"):
            i += _commit_long(a, info)
        elif a.startswith("-") and len(a) > 1:
            i += _commit_short(a, info)
        else:
            info["why"].append("commits explicit paths")
    return info


def _push_flags(args: list[str]) -> tuple[dict, list[str]]:
    flags = {"tags": False, "delete": False, "dry": False}
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            positional += args[i:]
            break
        if a.startswith("--"):
            name = a[2:].partition("=")[0]
            for flag, long_name in (("tags", "tags"), ("delete", "delete"), ("dry", "dry-run")):
                flags[flag] |= name == long_name
            i += name in _PUSH_LONG_ARG and "=" not in a
        elif a.startswith("-") and len(a) > 1:
            flags["delete"] |= "d" in a[1:]
            flags["dry"] |= "n" in a[1:]
            i += a[1:].endswith("o") and len(a) == 2
        else:
            positional.append(a)
    return flags, positional


def push_only_tags_or_delete(args: list[str]) -> bool:
    """True when the push cannot publish a commit: tags only, deletion, or dry-run."""
    flags, positional = _push_flags(args)
    if flags["delete"] or flags["dry"]:
        return True
    refspecs = positional[1:]  # positional[0] is the remote
    if refspecs and refspecs[0] == "tag":
        return True
    if refspecs:
        return all(r.startswith("refs/tags/") or r.startswith(":") for r in refspecs)
    return flags["tags"]


def _git_call(words: list[str], cwd: str) -> _Call | None:
    """Split `git [global options] SUB ARGS` (``words`` starts with `git`), resolving -C against ``cwd``."""
    gdir, i = cwd, 1
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            gdir = _resolve(gdir, words[i + 1])
            i += 2
        elif w in _GIT_GLOBAL_ARG:
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return _Call(gdir, w, words[i + 1 :])
    return None


def _gh_is_pr_create(words: list[str]) -> bool:
    rest, plain, i = words[1:], [], 0
    while i < len(rest):
        if rest[i] in ("-R", "--repo"):
            i += 2
            continue
        if not rest[i].startswith("-"):
            plain.append(rest[i])
        i += 1
    return plain[:2] == ["pr", "create"] and not any(w in ("-h", "--help") for w in rest)


def _cd_target(words: list[str], cwd: str) -> str:
    target = next((w for w in words[1:] if w == "-" or not w.startswith("-")), None)
    if target and target != "-":
        return _resolve(cwd, target)
    return os.path.expanduser("~") if target is None else cwd


def _git_action(call: _Call, staged_before: bool) -> dict | None:
    if call.sub in INDEX_CHANGERS:
        return {"kind": "stage", "dir": call.dir}
    if call.sub == "commit":
        info = commit_info(call.args)
        if info["dry_run"]:
            return None
        why = list(info["why"])
        if staged_before:
            why.insert(0, "stages (add/rm/mv/...) in the same call before the commit")
        return {"kind": "commit", "dir": call.dir, "why": why,
                "amend": info["amend"], "allow_empty": info["allow_empty"]}
    if call.sub == "push" and not push_only_tags_or_delete(call.args):
        return {"kind": "push", "dir": call.dir, "why": []}
    return None


def _simple_commands(command: str) -> Iterator[list[str]]:
    for seg in shell.segments(shell.lex(command)):
        words = shell.strip_prefix(seg)
        if words:
            yield words


def actions(command: str, base_cwd: str) -> list[dict]:
    """Every gated invocation in ``command``, each with the directory it runs in."""
    acts: list[dict] = []
    cwd, staged_before = base_cwd, False
    for words in _simple_commands(command):
        prog = os.path.basename(words[0])
        if prog in ("cd", "pushd"):
            cwd = _cd_target(words, cwd)
        elif prog == "git":
            call = _git_call(words, cwd)
            act = _git_action(call, staged_before) if call else None
            staged_before |= call is not None and call.sub in INDEX_CHANGERS
            if act:
                acts.append(act)
        elif prog == "gh" and _gh_is_pr_create(words):
            acts.append({"kind": "push", "dir": cwd, "why": []})
    return acts
