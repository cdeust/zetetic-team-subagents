#!/usr/bin/env python3
"""The gate task's command: verify ONE tree, exactly as committed, and exit 0 only if every check passed.

    gate_run.py run --repo TOP --tree TREE --base BASE|- --kind commit|push --trusted TREE --rules DIGEST
                    --runner DIGEST --env JSON

Started detached by tools/lib/tasks.py as task `gate-<key>` (hooks/lib/gate_state.py); its stdout/stderr
are the task's output file. Contract:

  pre   TREE is a tree object of the repository at TOP; BASE is the tree the change is measured from
        (`-`: the empty tree).
  post  exit 0  <=> every selected check passed on the files of TREE, run by the runner DIGEST names.
        The checks run in a private checkout of TREE (never in the working tree), with an allowlisted
        environment and an interpreter outside the repository (gate_runner), so a verdict is a function of
        (TREE, rules, runner): editing the working tree, its `.venv` or its `node_modules`, or exporting a
        variable such as PYTEST_ADDOPTS, while this runs or before it starts, cannot change it.
        The private directory is this process's own (mkdtemp) and is removed on every exit path it can
        observe; nothing else is removed.

Which checks run: the EFFECTIVE rules (gate_rules): those of the trusted tree (--trusted, HEAD's at the
time the hook judged) plus those of TREE when they differ, each planned and run on its own, with its own
environment. A change cannot choose its own rules. The selection of a rule set is gate_config.plan(): the
checks that cover the diff, valid only when BASE has a green record on the same basis (gate_state.base_is_green);
otherwise the full configured gate. Legacy `scripts/gate.sh` is run from the trusted tree's copy of `scripts/`.
The worker runs only for a repository the user listed (gate_trust), and only when the rules and the runner
are still the ones the hook keyed the task by.

On every exit the verdict is appended to the ledger (gate_ledger): the Stop hook reads it.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_config as config  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_ledger as ledger  # noqa: E402
import gate_rules as rules_mod  # noqa: E402
import gate_runner as runner_mod  # noqa: E402
import gate_state as state  # noqa: E402
import gate_trust as trust  # noqa: E402

LEGACY = "legacy-gate"


def _say(text: str) -> None:
    print(text, flush=True)


def _clean_env() -> dict:
    """The caller's environment without GIT_*, for the worker's own git plumbing: a variable such as GIT_DIR or
    GIT_OBJECT_DIRECTORY must not redirect it away from the tree being verified. The checks get the runner's."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(top: str, args: list, env: dict | None = None) -> bytes:
    out = gitq.run(top, args, env or _clean_env(), text=False, bounded=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout


def locate(top: str) -> str | None:
    """The absolute git common dir of the repository at ``top`` (clean environment), or None."""
    try:
        common = _git(top, ["rev-parse", "--git-common-dir"]).decode().strip()
    except RuntimeError:
        return None
    return common if os.path.isabs(common) else os.path.normpath(os.path.join(top, common))


def changed_files(top: str, base: str, tree: str) -> config.Diff:
    """The paths that differ between the two trees (additions, modifications, deletions), repo-relative, and
    those ``tree`` adds (status A: what a `"scope": "added"` check judges)."""
    base = _git(top, ["hash-object", "-t", "tree", "--stdin"]).decode().strip() if base == "-" else base
    raw = _git(top, ["diff-tree", "-r", "--name-status", "--no-renames", "-z", base, tree])
    fields = [os.fsdecode(p) for p in raw.split(b"\0") if p]
    pairs = list(zip(fields[0::2], fields[1::2]))
    return config.Diff([path for _, path in pairs], frozenset(path for status, path in pairs if status == "A"))


def materialize(top: str, tree: str, dest: str, index: str) -> None:
    """Check ``tree`` out into the empty directory ``dest`` through the private index file ``index`` (the real
    index is untouched)."""
    env = {**_clean_env(), "GIT_INDEX_FILE": index}
    try:
        _git(top, ["read-tree", tree], env)
        _git(top, ["checkout-index", "--all", "--force", f"--prefix={dest}/"], env)
    finally:
        if os.path.exists(index):
            os.unlink(index)
    gitq.run(dest, ["init", "-q"], _clean_env(), text=False, bounded=False)  # tools that expect a repo; result unused


def _substitute(argv: list, python: str) -> list:
    return [python if token == config.PY else token for token in argv]


def execute(steps: list, cwd: str, runner: runner_mod.Runner) -> int:
    """Run each step in ``cwd`` with the runner's environment plus the step's own; stop at the first failure.
    ``{python}`` is this interpreter, the one ``runner`` describes. 0 only if all passed."""
    for step in steps:
        env = {**runner.env, **(step.env or {})}
        argv = _substitute(step.argv, sys.executable)
        _say(f"[gate:{step.name}] {' '.join(argv)}")
        try:
            rc = subprocess.run(argv, cwd=step.cwd or cwd, env=env, stdin=subprocess.DEVNULL, check=False).returncode
        except OSError as exc:  # FAILS_ON: the check's command is missing or not executable
            _say(f"[gate:{step.name}] cannot start: {exc!r}")
            rc = 127
        if rc != 0:
            _say(f"[gate:{step.name}] FAILED rc={rc}")
            return rc if rc > 0 else 1
    return 0


def _unpack(tar: tarfile.TarFile, member: tarfile.TarInfo, root: str) -> None:
    """Extract one directory or regular file of the archive under ``root``; anything else is not extracted."""
    target = os.path.normpath(os.path.join(root, member.name))
    if target != root and not target.startswith(root + os.sep):
        raise RuntimeError(f"scripts entry {member.name!r} escapes its directory")
    if member.isdir():
        os.makedirs(target, exist_ok=True)
    elif member.isreg():
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            out.write(tar.extractfile(member).read())
        os.chmod(target, 0o700 if member.mode & 0o111 else 0o600)  # private to the user: the copy is only run by the worker


def export_scripts(top: str, oid: str, dest: str) -> str:
    """Write the `scripts` tree ``oid`` (an object of the repository, so a trusted tree's copy) under
    ``dest``/scripts; return the path of its gate.sh. Regular files only: a symlink is not extracted."""
    raw = _git(top, ["archive", "--format=tar", oid])
    root = os.path.join(dest, "scripts")
    os.makedirs(root)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar.getmembers():
            _unpack(tar, member, root)
    return os.path.join(root, os.path.basename(config.LEGACY_SCRIPT))


class Job(NamedTuple):
    """What a verification runs against: the repository, this worker's private directory, the arguments."""
    top: str
    root: str  # this worker's own directory (mkdtemp): the checkout, its private index, the exported scripts
    common: str
    args: argparse.Namespace

    @property
    def snap(self) -> str:
        return os.path.join(self.root, "tree")


def _steps_of(rule_set: rules_mod.RuleSet, job: Job, diff: config.Diff, full: bool) -> list:
    """The steps of ONE rule set. Each step carries the environment of the rules that declared it."""
    if rule_set.kind == "legacy":  # the trusted tree's script judges the real checkout (it needs .git)
        script = export_scripts(job.top, rule_set.scripts, os.path.join(job.root, "legacy", rule_set.scripts[:12]))
        return [config.Step(LEGACY, ["sh", script, job.args.kind], job.top)]
    env = config.check_env(rule_set.cfg, job.snap, job.common)
    return [step._replace(env=env) for step in config.plan(rule_set.cfg, job.snap, diff, full)]


def _plan_for(job: Job, rules: rules_mod.Rules, basis: state.Basis) -> list:
    """The steps for the tree checked out in ``job.snap``: every effective rule set planned on its own."""
    args = job.args
    if not rules.sets:
        _say("[gate] no gate is declared for this tree: nothing to verify")
        return []
    full = not state.base_is_green(job.top, basis, None if args.base == "-" else args.base)
    if full:
        _say(f"[gate] no green record for base {args.base[:12]} under these rules and this runner: the full configured gate runs")
    diff = changed_files(job.top, args.base, args.tree)
    _say(f"[gate] {len(diff.paths)} changed path(s) against {args.base[:12]}: {' '.join(diff.paths[:20])}")
    steps: list = []
    for rule_set in rules.sets:
        steps += [step for step in _steps_of(rule_set, job, diff, full) if step not in steps]
    if not steps:
        _say("[gate] no check applies to this change")
    return steps


def legacy_proof_names(common: str, kind: str, tree: str) -> bool:
    """True when the legacy script left a green proof for exactly ``tree`` (the old hook's own check).

    The script computes its own tree at run time (`write-tree` of the index NOW). If the index moved after
    this task started, it proved another tree and exits 0; the task for ``tree`` must not turn green on that.
    """
    path = os.path.join(common, "zetetic-gates", f"{kind}-{tree}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            proof = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(proof, dict) and proof.get("tree") == tree and proof.get("rc") == 0 and not isinstance(proof.get("rc"), bool)


def _refuse(job: Job, rules: rules_mod.Rules) -> str | None:
    """Why this verification must not run, or None. The worker is startable without the hooks (tools/task.sh),
    so the trust check and the rules check are made here too (and the runner check, _runner_changed, after them:
    an untrusted repository's runner is not even probed)."""
    args = job.args
    if not trust.is_trusted(job.top, job.common):
        return trust.refusal(job.top, job.common)
    if rules.digest != args.rules:
        return f"the effective rules changed since this verification was requested ({args.rules} -> {rules.digest}); request it again"
    return None


def _runner_changed(args: argparse.Namespace, runner: runner_mod.Runner) -> str | None:
    if runner.digest == args.runner:
        return None
    return (f"the runner changed since this verification was requested ({args.runner} -> {runner.digest}; "
            f"{runner_mod.describe(runner)}); request it again")


def run(args: argparse.Namespace) -> int:
    """Verify the tree and append the verdict to the ledger. No repository: nothing to verify, nothing to record
    (its task directory would otherwise be created under the user's home)."""
    common = locate(args.repo)
    if common is None:
        _say(f"[gate] {args.repo} is not a git repository")
        return 1
    rc, basis = _verify(args, args.repo, common)
    ledger.record(args.repo, ledger.Result(args.kind, args.tree, state.task_key(basis, args.tree), rc))
    return rc


def given_env(text: str) -> dict:
    """The checks' environment the task was keyed with (``--env``, recorded in the task's input), so the runner is
    the hook's whoever launches the worker. It is filtered again by the allowlist (gate_runner.resolve): a worker
    started by hand with another variable gets another runner digest and refuses. Raises RuntimeError."""
    try:
        env = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"--env is not JSON: {exc}") from exc
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise RuntimeError("--env must be a JSON object of string values")
    return env


def _verify(args: argparse.Namespace, top: str, common: str) -> tuple[int, state.Basis]:
    """(exit code, the basis the verdict is recorded on: the one the arguments name, which the worker checks)."""
    root = tempfile.mkdtemp(prefix=f"zetetic-gate-{args.tree[:16]}-")  # this attempt's own: no other worker shares it
    basis = state.Basis(args.rules, args.runner, args.kind)
    try:
        rules = rules_mod.effective(top, args.tree, args.trusted, _clean_env())
        job = Job(top, root, common, args)
        why = _refuse(job, rules)
        runner = None if why else runner_mod.resolve(top, common, rules.sets, given_env(args.env))
        why = why or _runner_changed(args, runner)
        if why:
            _say(f"[gate] {why}")
            return 1, basis
        _say(f"[gate] runner: {runner_mod.describe(runner)}")
        materialize(top, args.tree, job.snap, os.path.join(root, "index"))
        steps = _plan_for(job, rules, basis)
        rc = execute(steps, job.snap, runner)
        if rc == 0 and any(step.name == LEGACY for step in steps) and not legacy_proof_names(common, args.kind, args.tree):
            _say(f"[gate:{LEGACY}] exited 0 but left no green proof for tree {args.tree}: it proved a different tree")
            return 1, basis
        return rc, basis
    except (config.ConfigError, RuntimeError, gitq.Unavailable, runner_mod.Refused) as exc:  # FAILS_ON: invalid gate config, a tree could not be read, or the runner is refused
        _say(f"[gate] {exc}")
        return 1, basis
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="gate_run.py")
    sub = parser.add_subparsers(dest="verb", required=True)
    runner = sub.add_parser("run")
    for option in ("--repo", "--tree", "--base", "--trusted", "--rules", "--runner", "--env"):
        runner.add_argument(option, required=True)
    runner.add_argument("--kind", choices=("commit", "push"), required=True)
    args = parser.parse_args(argv)
    if not all(gitq.TREE_RE.match(t) for t in (args.tree, args.trusted)) or (args.base != "-" and not gitq.TREE_RE.match(args.base)):
        parser.error("--tree, --trusted and --base must be tree hashes")
    return run(args)


def _lower_priority() -> None:
    if hasattr(os, "nice"):
        os.nice(10)  # the verification must not starve the session that started it


if __name__ == "__main__":
    _lower_priority()
    sys.exit(main(sys.argv[1:]))
