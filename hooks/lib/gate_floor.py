"""The rule floor kept by the USER: the strongest rules that have been in force for a repository.

Round 3 floored a commit on HEAD's rules alone, and HEAD can be moved by commands the gate does not judge:
after `git checkout --orphan x` (the index is kept) or `git reset --soft <a commit before the gate>`, HEAD has no
rules, so a commit that drops `.zetetic/gate.json` weakened nothing, the next failing commit was ungated, and
`git push -f origin x:main` published it (PR #169, review round 3, a1_floor). So the floor is ALSO kept outside
every repository, where no command run in one can move it:

    ~/.claude/zetetic/gate-rule-floor/<32 hex>.jsonl   one file per repository; the hex is the sha256 of its identity
    identity   the real path of the repository's main checkout (gate_userfile.repo_root), as for the ack file

Each line is one change of the floor, appended in one O_APPEND write, so concurrent hooks neither interleave
lines nor lose an update (the floor is the replay of the file, in line order):

    {"repo": <identity>, "op": "raise" | "set", "states": [<rule state>, ...]}
    rule state  {"kind": "config" | "stack" | "legacy", "cfg": ..., "scripts": ..., "script": ...} (gate_rules.RuleSet)

    floor   the replay, from the empty floor: `raise` keeps the maximal states of floor + states, `set` the
            maximal states of states. The floor is a SET because rule states are only partially ordered
            (gate_superset): two branches may each add a check the other lacks, and both are kept. A rule state
            satisfies the floor when it is no weaker than each of its states.
    raise   an allowed commit or push leaves states in force that the floor does not cover, or the hook observes
            HEAD's rules (in force by definition) that it does not cover
    set     an allowed act left behind a state the owner acknowledged (gate_ack) although it is weaker than the
            floor: the owner lowered the floor, to what that act leaves in force

The hooks append; nothing else here is written, and only `record` writes. Closed by default: a file that exists
but cannot be read, a line that is not of the form above, a line naming another repository, a location that the
repository itself controls (an override inside it: gate_userfile.usable) all raise Unreadable, and the hook
denies with the reason. An absent file is the empty floor: a repository whose rules the hooks never saw in force
starts with none.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import gate_config as config
import gate_git as gitq
import gate_rules as rules_mod
import gate_superset as superset
import gate_userfile as userfile

ENV_DIR = "ZETETIC_GATE_RULE_FLOOR"  # source: path override of the floor directory, as gate_ack.ENV_FILE is for the ack file
DIR_NAME = "gate-rule-floor"
_OPS = ("raise", "set")
_OID = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")  # source: the object ids gate_git.TREE_RE accepts
_KEYS = {"kind", "cfg", "scripts", "script"}


class Unreadable(Exception):
    """The floor of a repository cannot be known; the message says why. The hook denies (closed)."""


def identity(top: str, common: str) -> str:
    return os.path.realpath(userfile.repo_root(top, common))


def _files(top: str, common: str) -> list:
    """The floor files of the repository, the one written first: in the override directory when it is set, and
    always in the default one, so an override pointing at an empty directory cannot hide the floor already kept.
    Raises Unreadable when a directory is the repository's own claim (inside it)."""
    name = hashlib.sha256(identity(top, common).encode()).hexdigest()[:32] + ".jsonl"
    override = os.environ.get(ENV_DIR)
    places = ([(override, False)] if override else []) + [(userfile.default(DIR_NAME), True)]
    for directory, is_default in places:
        if not userfile.usable(directory, is_default, top, common):
            raise Unreadable(f"the rule-floor directory {directory} is inside the repository, which cannot keep its own floor")
    return [os.path.join(directory, name) for directory, _ in places]


def path_of(top: str, common: str) -> str:
    """The floor file the hooks append to (the override directory's when set). Raises Unreadable (see _files)."""
    return _files(top, common)[0]


def _decode(raw: object) -> rules_mod.RuleSet:
    if not isinstance(raw, dict) or set(raw) != _KEYS or raw["kind"] not in ("config", "stack", "legacy"):
        raise ValueError("a rule state is an object with kind, cfg, scripts and script")
    if raw["kind"] == "legacy":
        # a legacy state always has both ids: it is declared by an executable scripts/gate.sh (gate_config.declaration)
        if raw["cfg"] is not None or not all(isinstance(v, str) and _OID.match(v) for v in (raw["scripts"], raw["script"])):
            raise ValueError("a legacy state has no cfg and the object ids of scripts and of scripts/gate.sh")
        return rules_mod.RuleSet("legacy", None, raw["scripts"], raw["script"])
    if raw["scripts"] is not None or raw["script"] is not None:
        raise ValueError(f"a {raw['kind']} state has no scripts and no script")
    try:
        return rules_mod.RuleSet(raw["kind"], config.validate(raw["cfg"]), None)
    except config.ConfigError as exc:
        raise ValueError(f"its rules are invalid ({exc})") from exc


def _encode(state: rules_mod.RuleSet) -> dict:
    return {"kind": state.kind, "cfg": state.cfg, "scripts": state.scripts, "script": state.script}


def covers(new: rules_mod.RuleSet | None, old: rules_mod.RuleSet | None) -> bool:
    """True when ``new`` is no weaker than ``old`` (gate_superset)."""
    return not superset.weakenings(old, new)


def maximal(states: list) -> list:
    """The states no other state covers, without duplicates (equal hash) and without None (no rules); of two that
    cover each other (the same rules spelled differently) the one with the smaller hash stays. Order: by hash."""
    unique = sorted({rules_mod.state_hash(s): s for s in states if s is not None}.items())
    return [s for i, (_, s) in enumerate(unique)
            if not any(j != i and covers(t, s) and (j < i or not covers(s, t)) for j, (_, t) in enumerate(unique))]


def _replay(lines: list, who: str, where: str) -> list:
    floor: list = []
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or set(row) != {"repo", "op", "states"} or row["op"] not in _OPS:
                raise ValueError('a line is {"repo", "op": "raise" | "set", "states"}')
            if row["repo"] != who:
                raise ValueError(f"it names another repository ({row['repo']!r})")
            if not isinstance(row["states"], list):
                raise ValueError("states is a list")
            states = [_decode(s) for s in row["states"]]
        except ValueError as exc:
            raise Unreadable(f"line {n} of {where} is not a floor record: {exc}") from exc
        floor = maximal((floor if row["op"] == "raise" else []) + states)
    return floor


def _read_file(where: str, who: str) -> list:
    try:
        with open(where, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:  # FAILS_ON: a floor that exists and cannot be read
        raise Unreadable(f"{where} cannot be read ({exc.__class__.__name__}: {exc})") from exc
    return _replay([line for line in text.split("\n") if line.strip()], who, where)


def read(top: str, common: str) -> list:
    """The floor of the repository: the maximal states of every floor file of it (a list of RuleSets; [] when
    there is none). Raises Unreadable (see above)."""
    who = identity(top, common)
    return maximal([state for where in _files(top, common) for state in _read_file(where, who)])


def _same(a: list, b: list) -> bool:
    return sorted(map(rules_mod.state_hash, a)) == sorted(map(rules_mod.state_hash, b))


def record(top: str, common: str, in_force: list, lowered: bool) -> None:
    """Append the change ``in_force`` makes to the floor: `set` when ``lowered`` (the owner acknowledged a weaker
    state), else `raise`. Nothing is written when the floor would not change.
    Raises Unreadable when the floor cannot be read, OSError when it cannot be written."""
    current = read(top, common)
    states = maximal(in_force)
    if _same(current, states if lowered else maximal(current + states)):
        return
    where = path_of(top, common)
    os.makedirs(os.path.dirname(where), mode=0o700, exist_ok=True)
    line = json.dumps({"repo": identity(top, common), "op": "set" if lowered else "raise",
                       "states": [_encode(s) for s in states]}, sort_keys=True, separators=(",", ":"))
    data = (line + "\n").encode()
    fd = os.open(where, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if os.write(fd, data) != len(data):  # one write, so concurrent appends never interleave
            raise OSError(f"short write to {where}")
    finally:
        os.close(fd)


def kept_for(directory: str) -> bool:
    """True when the user keeps a floor for the repository of ``directory`` (or its location is the repository's
    own claim, which is not known to be empty). Reads nothing but the directory entry."""
    repo = gitq.locate(directory)
    if repo is None:
        return False
    try:
        return any(os.path.exists(where) for where in _files(repo.top, repo.common))
    except Unreadable:
        return True


def weakened(floor: list, new: rules_mod.RuleSet | None, where: str) -> list:
    """One sentence per rule of a floor state that ``new`` does not keep, each saying where the floor is kept."""
    out: list = []
    for state in floor:
        out += [f"{w} (the floor recorded for this repository in {where})" for w in superset.weakenings(state, new)]
    return list(dict.fromkeys(out))
