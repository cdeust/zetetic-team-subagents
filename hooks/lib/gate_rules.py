"""The rules that judge a tree, and the key they give a verification.

A change must not choose the rules it is judged by. A staged `.zetetic/gate.json` with `"checks": ["true"]`
or `"off": true` would otherwise approve itself, so the rules are read from a TRUSTED tree, never from the
working copy and never from the tree being judged alone:

  trusted tree   HEAD's tree. With no HEAD yet (the first commit) there is nothing older to trust, and the
                 judged tree is its own trusted tree: the rules of a repository's first commit are its own.
  effective      the rules of the trusted tree, plus the rules of the judged tree when they differ. Never
                 fewer: the judged tree can add checks, it cannot remove or replace HEAD's. A config
                 change is therefore judged by the union (each rule set is planned and run on its own).
  floor          the rules a commit leaves behind may not be weaker than the trusted tree's (gate_superset),
                 or the union above would lag one commit behind: commit A deletes the config and passes
                 because HEAD's old checks still pass, commit B is then judged by a HEAD with no rules.
                 A weakening needs the owner's acknowledgement (gate_ack); `state_hash` names the state.
  digest         12 hex of the canonical form of the effective rule sets: one component of the cache key
                 of a verification (gate_state), so a verdict is never reused under other rules.

The rule sets are data read from git objects (gate_source.GitSource); nothing here runs a command.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import NamedTuple

import gate_config as config
import gate_git as gitq
import gate_source as source


class RuleSet(NamedTuple):
    kind: str  # "config" | "legacy" | "stack" (gate_config.declaration)
    cfg: dict | None  # config / stack: the validated rules; legacy: None
    scripts: str | None  # legacy: object id of the `scripts` tree the script runs from; else None
    script: str | None = None  # legacy: object id of scripts/gate.sh itself (what gate_superset compares); else None


class Rules(NamedTuple):
    trusted: str  # tree id the rules were trusted from
    sets: list  # RuleSets, trusted first, no duplicates; empty: the tree is not gated
    digest: str
    old: RuleSet | None = None  # the trusted tree's own rules (None: not gated)
    new: RuleSet | None = None  # the judged tree's own rules (None: not gated)


def of_tree(top: str, tree: str, env: dict | None = None) -> RuleSet | None:
    """The rule set declared by ``tree`` (None: not gated). Raises gate_config.ConfigError if its config is invalid."""
    src = source.GitSource(top, tree, env, config.PROBE_PATHS)
    kind = config.declaration(src)
    if kind is None:
        return None
    if kind == "legacy":
        scripts, script = src.entry("scripts"), src.entry(config.LEGACY_SCRIPT.replace(os.sep, "/"))
        return RuleSet("legacy", None, scripts[2] if scripts else None, script[2] if script else None)
    return RuleSet(kind, config.load(src) or config.stack_config(src), None)


def digest_of(sets: list) -> str:
    canon = json.dumps([[s.kind, s.cfg, s.scripts] for s in sets], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def trusted_tree(top: str, judged: str) -> str:
    return gitq.tree_of(top, "HEAD") or judged


def pair(top: str, judged: str, trusted: str | None = None, env: dict | None = None) -> tuple:
    """(rules of the trusted tree, rules of the judged tree), each a RuleSet or None (not gated).

    Pre: ``judged`` is a tree of the repository at ``top``; ``trusted`` (the worker passes the tree the hook
    trusted, because HEAD may have moved since) defaults to HEAD's tree. Raises gate_config.ConfigError.
    """
    trusted = trusted or trusted_tree(top, judged)
    old = of_tree(top, trusted, env)
    return old, (of_tree(top, judged, env) if judged != trusted else old)


def effective(top: str, judged: str, trusted: str | None = None, env: dict | None = None) -> Rules:
    """Post: the union described above (the trusted tree's rules, plus the judged tree's when they differ)."""
    trusted = trusted or trusted_tree(top, judged)
    old, new = pair(top, judged, trusted, env)
    sets: list = []
    for rule_set in (old, new):
        if rule_set is not None and rule_set not in sets:
            sets.append(rule_set)
    return Rules(trusted, sets, digest_of(sets), old, new)


def state_hash(rule_set: RuleSet | None) -> str:
    """32 hex of the rules state ``rule_set`` (None: no rules): the hash a rule-change acknowledgement names
    (gate_ack). The state a commit would leave behind, not the union it is judged by."""
    canon = json.dumps(None if rule_set is None else [rule_set.kind, rule_set.cfg, rule_set.scripts, rule_set.script],
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:32]  # source: 128 bits of sha256, so a state crafted to collide with an acknowledged one is out of reach


def declared(top: str) -> bool:
    """True when the repository at ``top`` is gated by its trusted tree (HEAD; the staged tree when no HEAD)."""
    tree = gitq.tree_of(top, "HEAD") or gitq.staged_tree(top)
    return of_tree(top, tree) is not None
