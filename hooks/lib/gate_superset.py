"""When is one rule set no weaker than another? (docs/gate.md, "Rule changes")

Rules may only grow without the owner. A commit whose rules are not a SUPERSET of HEAD's is a weakening and
needs the owner's acknowledgement (gate_ack). This module decides it, from data alone: no I/O, no command.

``weakenings(old, new)`` returns one sentence per rule of ``old`` that ``new`` does not keep ([] = superset).
``old`` is HEAD's rule set (None: HEAD declares no rules, so there is nothing to weaken) and ``new`` the
commit's (None: the commit declares none). A rule set has `.kind` ("config" | "stack" | "legacy"), `.cfg`
(the validated rules of a config or a stack) and `.script` (the object id of a legacy `scripts/gate.sh`).

The relation is SOUND and deliberately conservative: every case it calls growth really is growth, and a
spelling it cannot prove (a broader glob written another way) is reported, then acknowledged once.

  checks   each check of `old` has a check of `new` with the same argv whose path selection covers it:
           `old` pathless -> `new` pathless; otherwise `new` pathless, or `new` holds every pattern of `old`
           literally, or `**`. Names do not matter. A check may be added; none may be removed or replaced.
  tests    if `old` has a tests block: `new` has one; `argv`, `files` and `same_name` equal (a changed `files`
           or `same_name` changes which tests a change selects, and an empty selection falls back to the whole
           suite, so no change of either is provably a growth); `fast` equal, or both non-empty with `new` a
           superset; `map`: the same set of path patterns, and for each pattern `new` runs every test `old`
           ran (a pattern may gain tests; a new pattern would take paths away from the fallback, so it is not growth)
  full_on  `new` has every entry of `old`
  env      equal (an added variable can disarm a check: `PYTEST_ADDOPTS=--co`)
  link     equal
  kinds    config and stack are compared as rules (a stack is the generated config of its whole suite). A legacy
           script is not comparable with rules: deleting it, making it non-executable, replacing it by another
           script or by rules is a weakening. The content of what a check RUNS (a script it calls) is not a rule
           and is not compared.
"""
from __future__ import annotations

LEGACY = "scripts/gate.sh"  # source: the legacy gate script path declared in gate_config.LEGACY_SCRIPT


def _covers(new_paths: list | None, old_paths: list | None) -> bool:
    """True when a check selecting by ``new_paths`` selects everything one selecting by ``old_paths`` does."""
    if new_paths is None:
        return True
    # an `old` with no paths also runs for a deletion, which no pattern matches: only a pathless `new` covers it
    return old_paths is not None and ("**" in new_paths or set(old_paths) <= set(new_paths))


def _checks(old: list, new: list) -> list:
    out = []
    for check in old:
        if any(n["argv"] == check["argv"] and _covers(n.get("paths"), check.get("paths")) for n in new):
            continue
        kept = any(n["name"] == check["name"] for n in new)
        out.append(f'check "{check["name"]}" was ' + ("replaced (argv or paths differ)" if kept else "removed"))
    return out


def _map_tests(entries: list) -> dict:
    """pattern -> every test pattern some entry runs for it."""
    found: dict = {}
    for entry in entries:
        for pattern in entry["paths"]:
            found.setdefault(pattern, set()).update(entry["tests"])
    return found


def _map(old: list, new: list) -> list:
    before, after = _map_tests(old), _map_tests(new)
    out = [f'tests.map: path pattern "{p}" was removed' for p in sorted(set(before) - set(after))]
    out += [f'tests.map: path pattern "{p}" was added (a new pattern takes paths from the fallback)' for p in sorted(set(after) - set(before))]
    for pattern in sorted(set(before) & set(after)):
        lost = sorted(before[pattern] - after[pattern])
        out += [f'tests.map: "{pattern}" no longer runs {t}' for t in lost]
    return out


def _fast(old: list, new: list) -> list:
    if not old and not new:
        return []
    if old and set(old) <= set(new):
        return []
    return ["tests.fast changed" + (" (it was empty: the fallback would no longer be the whole suite)" if not old else " (an entry was removed)")]


def _tests(old: dict | None, new: dict | None) -> list:
    if not old:
        return []
    if not new:
        return ["tests were removed"]
    out = []
    if old["argv"] != new["argv"]:
        out.append("tests.argv was replaced")
    if sorted(old.get("files", [])) != sorted(new.get("files", [])):
        out.append("tests.files changed")
    if old.get("same_name", "") != new.get("same_name", ""):
        out.append("tests.same_name changed")
    return out + _fast(old.get("fast", []), new.get("fast", [])) + _map(old.get("map", []), new.get("map", []))


def _setup(old: dict, new: dict) -> list:
    out = [f'full_on entry "{p}" was removed' for p in sorted(set(old.get("full_on", [])) - set(new.get("full_on", [])))]
    if old.get("env", {}) != new.get("env", {}):
        out.append("env changed (a variable can disarm a check)")
    if sorted(old.get("link", [])) != sorted(new.get("link", [])):
        out.append("link changed")
    return out


def _rules(old: dict, new: dict) -> list:
    return _checks(old.get("checks", []), new.get("checks", [])) + _tests(old.get("tests"), new.get("tests")) + _setup(old, new)


def _gone(old: dict, why: str) -> list:
    """Every rule of ``old`` is gone: say so once, then name each."""
    return [why] + _rules(old, {})


def weakenings(old, new) -> list:
    """The rules of ``old`` that ``new`` does not keep, one sentence each; [] when ``new`` is a superset."""
    if old is None:
        return []
    if old.kind == "legacy":
        if new is None:
            return [f"{LEGACY} is deleted or no longer executable: nothing judges the commit any more"]
        if new.kind != "legacy":
            return [f"{LEGACY} no longer judges: the commit declares {new.kind} rules instead, which cannot be compared with a script"]
        return [] if new.script == old.script else [f"{LEGACY} was replaced: its content cannot be compared with the one HEAD has"]
    if new is None:
        return _gone(old.cfg, "the gate is no longer declared (.zetetic/gate.json deleted, or \"off\": true)")
    if new.kind == "legacy":
        return _gone(old.cfg, f"the rules were replaced by {LEGACY}, which cannot be compared with them")
    return _rules(old.cfg, new.cfg)
