"""The gate's verdict on a tree, read from (and started in) the async task `gate-<verb>-<tree>-<rules>-<runner>`.

The decision is a function of the task record alone (docs/async-tasks.md, docs/gate.md); nothing here
waits, sleeps, or compares elapsed time. The task is keyed by what the verdict depends on (Basis):

  verb     `commit` or `push`: a push needs a push-kind green record; a commit's never stands in for it
           (a repository's push-only gates, e.g. scripts/gate.sh push, would otherwise be lost)
  tree     the tree judged
  rules    the digest of the effective rules (gate_rules): a verdict is never reused under other rules
  runner   the digest of the environment and interpreter the checks run with (gate_runner): never reused
           under another runner

  disposition  record                  verdict
  cached       done, rc 0              allow (the cached proof)
  failed       failed                  deny, naming the output file
  started      queued (just launched)  deny: verification started, retry when it finishes
  in-flight    queued/running, alive   deny: verification running, retry when it finishes
  stale        in flight, worker dead  requeue once (explicit, counted), then as `started`

Before any task starts, the refusals that need no task: an invalid gate config (closed), a repository that is
not in the user's trusted list (gate_trust: nothing declared by an untrusted repository runs), a floor that
cannot be read (gate_floor, closed), and rules weaker than a floor anchor that the owner has not acknowledged.
The anchors (gate_floor, docs/gate.md "Rule changes"): HEAD's rules for a commit, each state of the floor the
user keeps for the repository, and for a push the rules of each destination ref as of the last fetch.
``check`` is the only entry that judges and starts; ``begin`` only starts; ``peek`` only reads.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_paths  # noqa: E402
PLUGIN_ROOT = gate_paths.PLUGIN_ROOT
import gate_ack as ack  # noqa: E402
import gate_config as config  # noqa: E402
import gate_floor as floor  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_rules as rules_mod  # noqa: E402
import gate_runner as runner_mod  # noqa: E402
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
    ends: tuple = ()  # the RuleSets (None: no rules) an allowed act leaves in force; () when the floor is not concerned
    head: object = None  # HEAD's RuleSet, observed in force (None: no rules, or not concerned)
    acked: bool = False  # the end state is weaker than an anchor and the owner acknowledged it


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


class Basis(NamedTuple):
    """What a verdict depends on besides the tree: the rules, the runner and the kind of act."""
    rules: str  # gate_rules.Rules.digest
    runner: str  # gate_runner.Runner.digest
    kind: str  # `commit` or `push`


def basis_of(verb: str, rules: rules_mod.Rules, runner: str) -> Basis:
    """The Basis of a ``verb`` verification under ``rules`` and the runner digest ``runner``."""
    return Basis(rules.digest, runner, verb)


def task_key(basis: Basis, tree: str) -> str:
    """`<kind>-<tree>-<rules>-<runner>`: the key of the verification of ``tree`` on ``basis``."""
    return f"{basis.kind}-{tree}-{basis.rules}-{basis.runner}"


class Plan(NamedTuple):
    """What a verification of one tree is: enough to start it, find it, and describe it."""
    top: str
    verb: str
    tree: str
    base: str | None
    rules: rules_mod.Rules
    runner: runner_mod.Runner
    acked: bool = False

    @property
    def basis(self) -> Basis:
        return basis_of(self.verb, self.rules, self.runner.digest)

    @property
    def key(self) -> str:
        return task_key(self.basis, self.tree)

    @property
    def id(self) -> str:
        return task_store.task_id(KIND, self.key)

    @property
    def argv(self) -> list:
        return job_argv(self)


def job_argv(plan: Plan) -> list:
    """The command the worker runs. ``verb`` is `commit` or `push`; ``base`` is the tree the change is measured from.
    The runner travels with it: the interpreter is argv[0] and the checks' environment is ``--env``, both recorded in
    the task's input, so whoever launches the task (the hook, or a requeue from any shell) runs the same runner."""
    return [sys.executable, "-B", RUN, "run", "--repo", plan.top, "--tree", plan.tree, "--base", plan.base or "-",
            "--kind", plan.verb, "--trusted", plan.rules.trusted, "--rules", plan.rules.digest,
            "--runner", plan.runner.digest, "--env", json.dumps(plan.runner.env, sort_keys=True)]


class Change(NamedTuple):
    """What a commit or a push asks to judge: the tree, the tree it is measured from, and for a push the
    remote-tracking refs of the branches it updates (gate_publish.Tip.dests)."""
    tree: str
    base: str | None
    dests: tuple = ()


class Anchors(NamedTuple):
    """What the end state must be no weaker than (docs/gate.md, "Rule changes")."""
    head: object  # HEAD's RuleSet: an anchor of a commit only (None: no rules, or a push)
    kept: list  # the states of the floor the user keeps for the repository (gate_floor)
    where: str  # the floor file, named in the denial
    dests: list  # [(ref, RuleSet)]: the destinations of a push that declare rules


def _weakenings(anchors: Anchors, new: object) -> list:
    """Every rule of an anchor that the end state ``new`` does not keep, one sentence each."""
    out = superset.weakenings(anchors.head, new) + floor.weakened(anchors.kept, new, anchors.where)
    for ref, state in anchors.dests:
        out += [f"{w} (the rules of {ref}, as of the last fetch)" for w in superset.weakenings(state, new)]
    return out


def _floor(repo: gitq.Repo, verb: str, anchors: Anchors, new: object) -> "Verdict | bool":
    """The refusal of rules weaker than an anchor that the owner has not acknowledged (gate_superset, gate_ack);
    else whether the end state passes only by the owner's acknowledgement (True) or because nothing weakens (False)."""
    weakened = _weakenings(anchors, new)
    if not weakened:
        return False
    state = rules_mod.state_hash(new)
    if ack.acknowledged(repo.top, repo.common, state):
        return True
    return Verdict(False, ack.refusal(repo, state, weakened, verb))


def _dest_rules(top: str, dests: tuple) -> list:
    """[(ref, RuleSet)] of the destination refs that exist and declare rules. Raises gate_config.ConfigError
    naming the ref whose config is invalid."""
    pairs = []
    for ref in dests:
        tree = gitq.tree_of(top, ref)
        try:
            state = None if tree is None else rules_mod.of_tree(top, tree)
        except config.ConfigError as exc:
            raise config.ConfigError(f"{ref}: {exc}") from exc
        if state is not None:
            pairs.append((ref, state))
    return pairs


def _anchors(repo: gitq.Repo, verb: str, rules: rules_mod.Rules, change: Change) -> Anchors:
    """Raises gate_config.ConfigError (a destination's config) or gate_floor.Unreadable (the floor)."""
    return Anchors(rules.old if verb == "commit" else None, floor.read(repo.top, repo.common),
                   floor.path_of(repo.top, repo.common), _dest_rules(repo.top, change.dests))


def prepare(top: str, verb: str, tree: str, base: str | None) -> "Plan | Verdict":
    """``plan_for`` a change with no destinations (a commit, the head start, a requeue)."""
    return plan_for(top, verb, Change(tree, base))


def plan_for(top: str, verb: str, change: Change) -> "Plan | Verdict":
    """The plan for ``change.tree``, or the final Verdict when no task is needed: not gated (allow), a config
    is invalid (deny, closed), the floor cannot be read (deny, closed), the repository is not trusted (deny,
    with the line to add), or the end state weakens an anchor (deny, naming each rule and the line to add)."""
    repo = gitq.locate(top)
    if repo is None:
        raise gitq.Unavailable(f"{top} is not a repository")
    try:
        rules = rules_mod.effective(top, change.tree)
        anchors = _anchors(repo, verb, rules, change)
    except config.ConfigError as exc:
        return Verdict(False, f"GATE-PROOF: the gate config of {top} is invalid ({exc}): refused (closed).")
    except floor.Unreadable as exc:
        return Verdict(False, f"GATE-PROOF: the rule floor of {top} cannot be read: {exc}. Refused (closed). "
                              "See docs/gate.md (rule changes).")
    if not (rules.sets or anchors.kept or anchors.dests):
        return Verdict(True, "")
    if rules.sets and not trust.is_trusted(top, repo.common):
        return Verdict(False, trust.refusal(top, repo.common))
    passed = _floor(repo, verb, anchors, rules.new)
    if isinstance(passed, Verdict):
        return passed
    if not rules.sets:
        return Verdict(True, "", (None,), None, passed)
    try:
        runner = runner_mod.resolve(top, repo.common, rules.sets)
    except runner_mod.Refused as exc:
        return Verdict(False, f"GATE-PROOF: {exc}. Refused (closed); nothing was run. See docs/gate.md (the runner).")
    return Plan(top, verb, change.tree, change.base, rules, runner, passed)


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
            f"Runner: {runner_mod.describe(plan.runner)}\n"
            f"Output: {rec.get('output_path')}\n{_tail(rec)}\n"
            f"Fix the cause and restage (a different tree starts a new verification). After an "
            f"infrastructure failure only: python3 {shlex.quote(CLI)} requeue --repo {shlex.quote(plan.top)} "
            f"--id {shlex.quote(rec['id'])}")


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
    return _judged(prepare(top, verb, tree, base))


def judge(top: str, verb: str, change: Change) -> Verdict:
    """``check`` for a change that names its destinations (the tip of a push)."""
    return _judged(plan_for(top, verb, change))


def _judged(plan: "Plan | Verdict") -> Verdict:
    """Post: the Verdict of a planned tree carries what the floor needs (gate-proof records it): the end state
    the call leaves in force, HEAD's state, and whether the end state passed by the owner's acknowledgement."""
    if isinstance(plan, Verdict):
        return plan
    verdict = verdict_of(plan, tasks.start(KIND, plan.key, plan.argv, plan.top))
    return verdict._replace(ends=(plan.rules.new,), head=plan.rules.old, acked=plan.acked)


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


def base_is_green(top: str, basis: Basis, base: str | None) -> bool:
    """True when ``base``'s tree has a green record on the same ``basis`` (rules, runner, and kind for a legacy
    script) (read only). Affected-only selection is valid only then: it assumes everything outside the diff was
    verified."""
    return base is not None and tasks.is_green(tasks.status(task_store.task_id(KIND, task_key(basis, base)), top))
