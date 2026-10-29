"""`git push` arguments, parsed the way git parses them (git 2.50 `git push -h`; tests/test_gate_publish_attacks.py
compares the option table below with what the installed git documents, so a git that grows a valued option fails a test).

Pure words in, structure out: no I/O, no git.

  short options   a cluster `-xyz` is read letter by letter; the letters `d` (delete) and `n` (dry-run) are flags
                  only while they ARE letters. `-o` takes a value: the REST of the cluster if there is any
                  (`-odebug`, `-on`, `-vodebug`), else the next word. So `-on` is the option `-o` with the value `n`.
  long options    `--name`, `--name=value`, `--no-name`; git accepts any unambiguous PREFIX (`--dry`, `--dele`).
                  A valued option (`--repo`, `--receive-pack`, `--exec`, `--push-option`, `--recurse-submodules`)
                  takes the next word when written without `=`. An unknown or ambiguous option is a git error:
                  nothing is published, so it changes nothing here.
  positional      `[<remote> [<refspec>...]]`; with `--repo` the remote is its value and every positional is a refspec.
  refspec         `[+]src[:dst]`, `:dst` deletes, `tag NAME` is `refs/tags/NAME:refs/tags/NAME`.
"""
from __future__ import annotations

from typing import NamedTuple

# long option -> takes its value as the next word when written without `=` (git push -h)
LONG_OPTIONS = {
    "verbose": False, "quiet": False, "repo": True, "all": False, "branches": False, "mirror": False,
    "delete": False, "tags": False, "dry-run": False, "porcelain": False, "force": False,
    "force-with-lease": False, "force-if-includes": False, "recurse-submodules": True, "thin": False,
    "receive-pack": True, "exec": True, "set-upstream": False, "progress": False, "prune": False,
    "verify": False, "follow-tags": False, "signed": False, "atomic": False, "push-option": True,
    "ipv4": False, "ipv6": False,
}
LONG_WITH_VALUE = frozenset(name for name, valued in LONG_OPTIONS.items() if valued)
SHORT_WITH_VALUE = frozenset("o")
_FLAG_OF = {"delete": "delete", "dry-run": "dry", "tags": "tags", "follow-tags": "follow_tags", "all": "all",
            "branches": "all", "mirror": "mirror"}


class Refspec(NamedTuple):
    src: str  # "" for a deletion
    dst: str  # the remote side; the source's own name when none is written

    @property
    def deletes(self) -> bool:
        return not self.src

    @property
    def to_tag(self) -> bool:
        return self.dst.startswith("refs/tags/")


def _long_name(name: str) -> tuple[str | None, bool]:
    """(canonical option, negated) of ``name`` (without the dashes): an exact name, or a unique prefix."""
    negated = name not in LONG_OPTIONS and name.startswith("no-")
    stem = name[3:] if negated else name
    if stem in LONG_OPTIONS:
        return stem, negated
    candidates = [n for n in LONG_OPTIONS if n.startswith(stem)]
    return (candidates[0], negated) if len(candidates) == 1 and stem else (None, negated)


def _apply_long(arg: str, flags: dict) -> tuple[str | None, bool]:
    """Apply `--name[=value]` to ``flags``; (canonical option or None, True when its value is the NEXT word)."""
    name, eq, value = arg[2:].partition("=")
    canon, negated = _long_name(name)
    if canon is None:
        return None, False
    if canon in _FLAG_OF:
        flags[_FLAG_OF[canon]] = not negated
    if canon == "repo":
        flags["repo"] = None if negated else value
    return canon, canon in LONG_WITH_VALUE and not eq and not negated


def _apply_short(cluster: str, flags: dict) -> bool:
    """Apply a `-xyz` cluster; True when its last letter is `-o` with nothing after it (its value is the next word)."""
    for k, letter in enumerate(cluster):
        if letter in SHORT_WITH_VALUE:
            return k == len(cluster) - 1  # anything after the letter is its value, not more flags
        if letter == "d":
            flags["delete"] = True
        elif letter == "n":
            flags["dry"] = True
    return False


def parse(args: list[str]) -> tuple[dict, list[str]]:
    """(flags, positional words) of ``git push ARGS``. flags: delete, dry, tags, follow_tags, all, mirror, repo."""
    flags = {"delete": False, "dry": False, "tags": False, "follow_tags": None, "all": False, "mirror": False, "repo": None}
    positional: list[str] = []
    i = 0
    while i < len(args):  # termination: i grows by >= 1 per iteration
        word = args[i]
        i += 1
        if word == "--":
            positional += args[i:]
            break
        if word.startswith("--"):
            canon, takes_next = _apply_long(word, flags)
            if takes_next and canon == "repo" and i < len(args):
                flags["repo"] = args[i]
            i += takes_next
        elif word.startswith("-") and len(word) > 1:
            i += _apply_short(word[1:], flags)
        else:
            positional.append(word)
    return flags, positional


def refspecs(words: list[str]) -> list[Refspec]:
    """The refspecs among ``words`` (the positionals after the remote)."""
    found: list[Refspec] = []
    i = 0
    while i < len(words):
        word = words[i]
        i += 1
        if word == "tag" and i < len(words):
            name = f"refs/tags/{words[i]}"
            found.append(Refspec(name, name))
            i += 1
            continue
        src, colon, dst = word.lstrip("+").partition(":")
        found.append(Refspec(src, dst if colon else src))
    return found


def publish(args: list[str]) -> dict:
    """What a `git push` names, as words (gate_publish.resolve turns it into the commits published).

    all/mirror: every local branch (mirror: the remote-tracking refs too); tags / follow_tags: the options of
    those names (follow_tags None: not written, `push.followTags` decides); remote: the remote written (the
    value of --repo, else the first positional; None: not written); specs: the refspecs written, as words (none:
    the current branch, or what the configuration says).
    """
    flags, positional = parse(args)
    if flags["repo"] is not None:
        remote, rest = (flags["repo"] or None), positional
    elif positional:
        remote, rest = positional[0], positional[1:]
    else:
        remote, rest = None, []
    return {"all": flags["all"], "mirror": flags["mirror"], "tags": flags["tags"], "follow_tags": flags["follow_tags"],
            "remote": remote, "specs": rest, "gh_head": None, "gh": False}


def publishes_no_commit(args: list[str]) -> bool:
    """True when the push cannot publish a commit: a deletion (`--delete`, `:dst` only) or a dry run."""
    flags, positional = parse(args)
    if flags["delete"] or flags["dry"]:
        return True
    if flags["all"] or flags["mirror"] or flags["tags"] or flags["follow_tags"]:  # None (unwritten) is not a reason
        return False
    rest = positional if flags["repo"] is not None else positional[1:]
    specs = refspecs(rest)
    return bool(specs) and all(spec.deletes for spec in specs)
