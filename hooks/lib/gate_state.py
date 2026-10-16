"""The gate's verdict on a tree, read from (and started in) the async task `gate-<verb>-<tree>-<rules>`.

The decision is a function of the task record alone (docs/async-tasks.md, docs/gate.md); nothing here
waits, sleeps, or compares elapsed time. The task is keyed by what the verdict depends on:

  verb     `commit` or `push`: a push needs a push-kind green record; a commit's never stands in for it
           (a repository's push-only gates, e.g. scripts/gate.sh push, would otherwise be lost)
  tree     the tree judged
  rules    the digest of the effective rules (gate_rules): a verdict is never reused under other rules

  disposition  record                  verdict
  cached       done, rc 0              allow (the cached proof)
  failed       failed                  deny, naming the output file
  started      queued (just launched)  deny: verification started, retry when it finishes
  in-flight    queued/running, alive   deny: verification running, retry when it finishes
  stale        in flight, worker dead  requeue once (explicit, counted), then as `started`

Before any task starts, two refusals that need no task: an invalid gate config (closed), and a repository
that is not in the user's trusted list (gate_trust): nothing declared by an untrusted repository runs.
``check`` is the only entry that judges and starts; ``begin`` only starts; ``peek`` only reads.
"""
from __future__ import annotations

import os
import sys
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_paths  # noqa: E402
PLUGIN_ROOT = gate_paths.PLUGIN_ROOT
import gate_ack as ack  # noqa: E402
import gate_config as config  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_rules as rules_mod  # noqa: E402
import gate_superset as superset  # noqa: E402
import gate_trust as trust  # noqa: E402
import tasks  # noqa: E402
import task_store  # noqa: E402

KIND = "gate"
RUN = os.path.join(HERE, "gate_run.py")
CLI = os.path.join(HERE, "gate_task.py")
TASK_SH = os.path.join(PLUGIN_ROOT, "tools", "task.sh")
_TAIL_LINES = 12  # source: enough of the failing check's output to see the assertion without opening the file


class Verdict(NamedTuple):
    allow: bool
    message: str


def commit_trees(top: str, amend: bool, allow_empty: bool) -> tuple[str, str | None] | None:
    """(tree, base) of the commit about to be made, or None when it would be refused anyway (empty index)."""
    tree, head = gitq.staged_tree(top), gitq.tree_of(top, "HEAD")
    if not (amend or allow_empty) and tree == (head or gitq.empty_tree(top)):
        return None
    return tree, (gitq.tree_of(top, "HEAD^") if amend else head)


def push_trees(top: str) -> tuple[str, str | None]:
    """(tree, base) of what a push publishes: HEAD's tree, measured from its parent."""
    tree = gitq.tree_of(top, "HEAD")
    if tree is None:
        raise gitq.Unavailable("cannot compute the tree of HEAD (no commit yet?)")
    return tree, gitq.tree_of(top, "HEAD^")


class Plan(NamedTuple):
    """What a verification of one tree is: enough to start it, find it, and describe it."""
    top: str
    verb: str
    tree: str
    base: str | None
    rules: rules_mod.Rules

    @property
    def key(self) -> str:
        return task_key(self.verb, self.tree, self.rules.digest)

    @property
    def id(self) -> str:
        return task_store.task_id(KIND, self.key)

    @property
    def argv(self) -> list:
        return job_argv(self)


def task_key(verb: str, tree: str, digest: str) -> str:
    return f"{verb}-{tree}-{digest}"


def job_argv(plan: Plan) -> list:
    """The command the worker runs. ``verb`` is `commit` or `push`; ``base`` is the tree the change is measured from."""
    return [sys.executable, "-B", RUN, "run", "--repo", plan.top, "--tree", plan.tree, "--base", plan.base or "-",
            "--kind", plan.verb, "--trusted", plan.rules.trusted, "--rules", plan.rules.digest]


def _floor(top: str, common: str, rules: rules_mod.Rules) -> Verdict | None:
    """The refusal of a commit whose rules are not a superset of HEAD's and that the owner has not
    acknowledged (gate_superset, gate_ack); None when the rules only grew or the state is acknowledged."""
    weakened = superset.weakenings(rules.old, rules.new)
    state = rules_mod.state_hash(rules.new)
    if not weakened or ack.acknowledged(top, common, state):
        return None
    return Verdict(False, ack.refusal(top, common, state, weakened))


def prepare(top: str, verb: str, tree: str, base: str | None) -> "Plan | Verdict":
    """The plan for ``tree``, or the final Verdict when no task is needed: not gated (allow), the config is
    invalid (deny, closed), the repository is not trusted (deny, with the line to add), or a commit weakens
    the rules HEAD has (deny, naming each rule and the acknowledgement line)."""
    try:
        rules = rules_mod.effective(top, tree)
    except config.ConfigError as exc:
        return Verdict(False, f"GATE-PROOF: the gate config of {top} is invalid ({exc}): refused (closed).")
    if not rules.sets:
        return Verdict(True, "")
    repo = gitq.locate(top)
    if repo is None:
        raise gitq.Unavailable(f"{top} is not a repository")
    if not trust.is_trusted(top, repo.common):
        return Verdict(False, trust.refusal(top, repo.common))
    if verb == "commit":
        refused = _floor(top, repo.common, rules)
        if refused:
            return refused
    return Plan(top, verb, tree, base, rules)


def _status_cmd(top: str, tid: str) -> str:
    return f"{TASK_SH} status {tid} --repo {top}"


def status_command(top: str, key: str) -> str:
    """The command that shows the task with ``key`` (a ledger row carries it)."""
    return _status_cmd(top, task_store.task_id(KIND, key))


def _tail(rec: dict) -> str:
    lines = (rec.get("result_excerpt") or "").strip().splitlines()[-_TAIL_LINES:]
    return "\n".join("    " + line for line in lines)


def failed_message(plan: Plan, rec: dict) -> str:
    cause = rec.get("reason") or f"rc={rec.get('rc')}" + (f", signal {rec['signal']}" if rec.get("signal") else "")
    return (f"GATE-PROOF: verification FAILED for tree {plan.tree} ({plan.verb}; {cause}).\n"
            f"Output: {rec.get('output_path')}\n{_tail(rec)}\n"
            f"Fix the cause and restage (a different tree starts a new verification). After an "
            f"infrastructure failure only: python3 {CLI} requeue --repo {plan.top} --kind {plan.verb}")


def pending_message(plan: Plan, rec: dict, started: bool) -> str:
    what = "started" if started else "running"
    return (f"GATE-PROOF: verification {what} for tree {plan.tree}; retry the {plan.verb} when it finishes "
            f"(status: {_status_cmd(plan.top, rec['id'])}). This hook does not wait.")


def _requeue_stale(plan: Plan) -> Verdict:
    again = tasks.requeue(KIND, plan.key, plan.argv, plan.top)
    if again.disposition == "orphaned":
        return Verdict(False, (f"GATE-PROOF: the verification worker for tree {plan.tree} died while its command "
                               f"is still running (process group {again.record.get('pgid')}); inspect with "
                               f"{_status_cmd(plan.top, again.record['id'])} and see docs/async-tasks.md (orphaned)."))
    return Verdict(False, pending_message(plan, again.record, started=True) +
                   f" (attempt {again.record['attempt']}: the previous worker died without a result)")


def verdict_of(plan: Plan, started: tasks.Started) -> Verdict:
    rec, disp = started.record, started.disposition
    if disp == "cached":
        return Verdict(True, "")
    if disp == "failed":
        return Verdict(False, failed_message(plan, rec))
    if disp == "stale":
        return _requeue_stale(plan)
    return Verdict(False, pending_message(plan, rec, started=disp == "started"))


def check(top: str, verb: str, tree: str, base: str | None) -> Verdict:
    """Start-or-find the task for ``tree`` and judge it. Returns at once, whatever the task is doing."""
    plan = prepare(top, verb, tree, base)
    if isinstance(plan, Verdict):
        return plan
    return verdict_of(plan, tasks.start(KIND, plan.key, plan.argv, top))


def begin(top: str, verb: str, tree: str, base: str | None) -> tasks.Started | None:
    """Start-or-find the task without judging it (the PostToolUse head start). None: nothing may run."""
    plan = prepare(top, verb, tree, base)
    return None if isinstance(plan, Verdict) else tasks.start(KIND, plan.key, plan.argv, top)


def record_of_key(top: str, key: str) -> dict | None:
    """The record of the task with ``key`` (a ledger row carries it) or None. Reads only."""
    return tasks.status(task_store.task_id(KIND, key), top)


def peek(plan: Plan) -> dict | None:
    """The record of the plan's task or None. Reads only."""
    return tasks.status(plan.id, plan.top)


def base_is_green(top: str, verb: str, base: str | None, digest: str) -> bool:
    """True when ``base``'s tree has a green record of the same verb under the same rules (read only).

    Affected-only selection is valid only then: it assumes everything outside the diff was verified.
    """
    return base is not None and tasks.is_green(tasks.status(task_store.task_id(KIND, task_key(verb, base, digest)), top))
