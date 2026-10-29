"""The owner's acknowledgement of a change that weakens the gate's rules.

Rules may only grow without the owner (gate_superset). A commit whose rules are not a superset of HEAD's is
denied with the sentences that name each weakened rule and ONE line to add to

    ~/.claude/zetetic/gate-rule-changes     `<absolute repository path> <hash of the new rules state>` per line

The hash (gate_rules.state_hash) names the rules state the commit would leave behind, so a line covers that
one state in that one repository: acknowledging "delete the config" does not acknowledge the next, different
weakening. This module never writes the file; adding the line is the owner's act. The location, the override
variable and the rule for a file inside the repository are gate_userfile's, as for the trusted list.
"""
from __future__ import annotations

import os

import gate_userfile as userfile

ENV_FILE = "ZETETIC_GATE_RULE_CHANGES"  # source: path override of the acknowledgement file, as gate_trust.ENV_FILE is for the trusted list
FILE_NAME = "gate-rule-changes"


def ack_file() -> str:
    return userfile.location(ENV_FILE, FILE_NAME)[0]


def _entries() -> set:
    """{(real path, hash)} of the well-formed lines. A line with more or fewer than two fields, or whose first
    field is not an absolute path (a blank line, a `# note`), names nothing."""
    pairs = (line.split() for line in userfile.lines(ack_file()))
    return {(os.path.realpath(p[0]), p[1]) for p in pairs if len(p) == 2 and os.path.isabs(p[0])}


def acknowledged(top: str, common: str, state: str) -> bool:
    path, is_default = userfile.location(ENV_FILE, FILE_NAME)
    # an acknowledgement that lives in the repository is the repository's own claim, not the owner's: `usable` is False for it
    return userfile.usable(path, is_default, top, common) and any(
        (os.path.realpath(where), state) in _entries() for where in (top, userfile.repo_root(top, common)))


def refusal(repo: tuple, state: str, weakened: list, verb: str) -> str:
    """The denial of a ``verb`` (commit or push) whose end state ``state`` weakens the rules: each weakened rule,
    and the line that acknowledges that state. ``repo`` is (top, git common dir), as gate_git.Repo."""
    top, common = repo
    named = "\n".join(f"  - {w}" for w in weakened)
    return (f"GATE-PROOF: this {verb} weakens the gate rules of {top}; rules may only grow without you. Nothing was run.\n"
            f"{named}\n"
            f"If you intend this, add this line to {ack_file()} (create the file if it is absent):\n"
            f"{os.path.realpath(userfile.repo_root(top, common))} {state}\n"
            f"It covers this one rules state only. Then retry. See docs/gate.md (rule changes).")
