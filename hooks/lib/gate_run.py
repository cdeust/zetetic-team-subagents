#!/usr/bin/env python3
"""The gate task's command: verify ONE tree, exactly as committed, and exit 0 only if every check passed.

    gate_run.py run --repo TOP --tree TREE --base BASE|- --kind commit|push --trusted TREE --rules DIGEST

Started detached by tools/lib/tasks.py as task `gate-<TREE>` (hooks/lib/gate_state.py); its stdout/stderr
are the task's output file. Contract:

  pre   TREE is a tree object of the repository at TOP; BASE is the tree the change is measured from
        (`-`: the empty tree).
  post  exit 0  <=> every selected check passed on the files of TREE.
        The checks run in a private checkout of TREE (never in the working tree), so a verdict is a
        function of TREE alone: editing the working tree while this runs cannot change it.
        The checkout is removed on every exit path.

Which checks run: the EFFECTIVE rules (gate_rules): those of the trusted tree (--trusted, HEAD's at the
time the hook judged) plus those of TREE when they differ, each planned and run on its own, with its own
environment. A change cannot choose its own rules. The selection of a rule set is gate_config.plan(): the
checks that cover the diff, valid only when BASE has a green record of the same kind under the same rules
(gate_state.base_is_green); otherwise the full configured gate. Legacy `scripts/gate.sh` is run from the
trusted tree's copy of `scripts/`. The worker runs only for a repository the user listed (gate_trust).

On every exit the verdict is appended to the ledger (gate_ledger): the Stop hook reads it.
"""
from __future__ import annotations

import argparse
import hashlib
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
import gate_state as state  # noqa: E402
import gate_trust as trust  # noqa: E402

LEGACY = "legacy-gate"
_PY_NAMES = (os.path.join("bin", "python"), os.path.join("Scripts", "python.exe"))


def _say(text: str) -> None:
    print(text, flush=True)


def _clean_env() -> dict:
    """The caller's environment without GIT_*: a variable such as GIT_DIR or GIT_OBJECT_DIRECTORY must not
    redirect the plumbing or the checks away from the tree being verified."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(top: str, args: list, env: dict | None = None) -> bytes:
    out = subprocess.run(["git", "-C", top, *args], env=env or _clean_env(), stdin=subprocess.DEVNULL,
                         capture_output=True, check=False)
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


def changed_files(top: str, base: str, tree: str) -> list:
    """Paths that differ between the two trees (additions, modifications, deletions), repo-relative."""
    base = _git(top, ["hash-object", "-t", "tree", "--stdin"]).decode().strip() if base == "-" else base
    raw = _git(top, ["diff-tree", "-r", "--name-only", "--no-renames", "-z", base, tree])
    return [os.fsdecode(p) for p in raw.split(b"\0") if p]


def materialize(top: str, tree: str, dest: str) -> None:
    """Check ``tree`` out into the empty directory ``dest`` through a private index (the real index is untouched)."""
    index = dest + ".index"
    env = {**_clean_env(), "GIT_INDEX_FILE": index}
    try:
        _git(top, ["read-tree", tree], env)
        _git(top, ["checkout-index", "--all", "--force", f"--prefix={dest}/"], env)
    finally:
        if os.path.exists(index):
            os.unlink(index)
    subprocess.run(["git", "-C", dest, "init", "-q"], check=False, capture_output=True)  # tools that expect a repo


def resolve_python(top: str, common: str) -> str:
    """The checkout's own venv python, else the main checkout's (a linked worktree has none), else ours."""
    for base in (top, os.path.dirname(common)):
        for name in _PY_NAMES:
            cand = os.path.join(base, ".venv", name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return sys.executable


def _substitute(argv: list, python: str) -> list:
    return [python if token == config.PY else token for token in argv]


def _check_env(extra: dict) -> dict:
    return {**_clean_env(), "PYTHONDONTWRITEBYTECODE": "1", **extra}


def execute(steps: list, cwd: str, python: str, extra_env: dict | None = None) -> int:
    """Run each step in ``cwd``; stop at the first failure. 0 only if all passed."""
    for step in steps:
        env = _check_env({**(extra_env or {}), **(step.env or {})})
        argv = _substitute(step.argv, python)
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
        os.chmod(target, member.mode & 0o777)


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
    """What a verification runs against: the repository, the private checkout of the tree, the arguments."""
    top: str
    snap: str
    common: str
    args: argparse.Namespace


def _steps_of(rule_set: rules_mod.RuleSet, job: Job, changed: list, full: bool) -> tuple[list, list]:
    """(steps, links) of ONE rule set. Each step carries the environment of the rules that declared it."""
    if rule_set.kind == "legacy":  # the trusted tree's script judges the real checkout (it needs .git)
        script = export_scripts(job.top, rule_set.scripts, os.path.join(job.snap + ".legacy", rule_set.scripts[:12]))
        return [config.Step(LEGACY, ["sh", script, job.args.kind], job.top)], []
    env, links = config.setup_for(rule_set.cfg, job.top, job.common)
    return [step._replace(env=env) for step in config.plan(rule_set.cfg, job.snap, changed, full)], links


def _plan_for(job: Job, rules: rules_mod.Rules) -> tuple[list, list]:
    """(steps, links) for the tree checked out in ``job.snap``: every effective rule set planned on its own."""
    args = job.args
    if not rules.sets:
        _say("[gate] no gate is declared for this tree: nothing to verify")
        return [], []
    full = not state.base_is_green(job.top, args.kind, None if args.base == "-" else args.base, rules.digest)
    if full:
        _say(f"[gate] no green {args.kind} record for base {args.base[:12]} under these rules: the full configured gate runs")
    changed = changed_files(job.top, args.base, args.tree)
    _say(f"[gate] {len(changed)} changed path(s) against {args.base[:12]}: {' '.join(changed[:20])}")
    steps: list = []
    links: list = []
    for rule_set in rules.sets:
        more, link = _steps_of(rule_set, job, changed, full)
        steps += [step for step in more if step not in steps]
        links += [rel for rel in link if rel not in links]
    if not steps:
        _say("[gate] no check applies to this change")
    return steps, links


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


def _link(top: str, snap: str, paths: list) -> None:
    """Symlink untracked dependency directories from the checkout into the private one (never overwrite)."""
    for rel in paths:
        source, target = os.path.join(top, rel), os.path.join(snap, rel)
        if os.path.exists(source) and not os.path.lexists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(source, target)


def _snapshot_dir(tree: str, common: str) -> str:
    """A fresh private directory named by (tree, repository). A leftover of an attempt that was SIGKILLed
    (nothing can clean up after that) is replaced: the task layer starts a new attempt only once the
    previous one's process group is gone, so the leftover has no owner."""
    owner = hashlib.sha1(os.path.realpath(common).encode()).hexdigest()[:8]
    path = os.path.join(tempfile.gettempdir(), f"zetetic-gate-{tree[:16]}-{owner}")
    shutil.rmtree(path, ignore_errors=True)
    os.mkdir(path)
    return path


def _refuse(top: str, common: str, rules: rules_mod.Rules, args: argparse.Namespace) -> str | None:
    """Why this verification must not run, or None. The worker is startable without the hooks (tools/task.sh),
    so the trust check and the rules check are made here too."""
    if not trust.is_trusted(top, common):
        return trust.refusal(top, common)
    if rules.digest != args.rules:
        return f"the effective rules changed since this verification was requested ({args.rules} -> {rules.digest}); request it again"
    return None


def run(args: argparse.Namespace) -> int:
    top = args.repo
    common = locate(top)
    if common is None:
        _say(f"[gate] {top} is not a git repository")
        return 1
    snap = _snapshot_dir(args.tree, common)
    try:
        rules = rules_mod.effective(top, args.tree, args.trusted, _clean_env())
        why = _refuse(top, common, rules, args)
        if why:
            _say(f"[gate] {why}")
            return 1
        shutil.rmtree(snap + ".legacy", ignore_errors=True)  # a leftover of a SIGKILLed attempt has no owner (see _snapshot_dir)
        materialize(top, args.tree, snap)
        steps, links = _plan_for(Job(top, snap, common, args), rules)
        _link(top, snap, links)
        rc = execute(steps, snap, resolve_python(top, common))
        if rc == 0 and any(step.name == LEGACY for step in steps) and not legacy_proof_names(common, args.kind, args.tree):
            _say(f"[gate:{LEGACY}] exited 0 but left no green proof for tree {args.tree}: it proved a different tree")
            return 1
        return rc
    except (config.ConfigError, RuntimeError, gitq.Unavailable) as exc:  # FAILS_ON: invalid gate config, or a tree could not be read
        _say(f"[gate] {exc}")
        return 1
    finally:
        shutil.rmtree(snap, ignore_errors=True)
        shutil.rmtree(snap + ".legacy", ignore_errors=True)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="gate_run.py")
    sub = parser.add_subparsers(dest="verb", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--repo", required=True)
    runner.add_argument("--tree", required=True)
    runner.add_argument("--base", required=True)
    runner.add_argument("--kind", choices=("commit", "push"), required=True)
    runner.add_argument("--trusted", required=True)
    runner.add_argument("--rules", required=True)
    args = parser.parse_args(argv)
    if not all(gitq.TREE_RE.match(t) for t in (args.tree, args.trusted)) or (args.base != "-" and not gitq.TREE_RE.match(args.base)):
        parser.error("--tree, --trusted and --base must be tree hashes")
    rc = run(args)
    ledger.record(args.repo, ledger.Result(args.kind, args.tree, state.task_key(args.kind, args.tree, args.rules), rc))
    return rc


def _lower_priority() -> None:
    if hasattr(os, "nice"):
        os.nice(10)  # the verification must not starve the session that started it


if __name__ == "__main__":
    _lower_priority()
    sys.exit(main(sys.argv[1:]))
