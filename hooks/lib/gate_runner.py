"""What a check runs with, besides the tree and the rules: its environment and the interpreter `{python}`.

A verdict is a function of (tree, rules, runner), and the runner is the third component of the cache key
(gate_state.task_key), so a verdict is never reused under another runner. Nothing a check sees may come from
the repository's working copy, which the agent edits: only the tree (checked out privately, gate_run), the
rules (read from git objects, gate_rules) and the runner below.

  environment  a fixed allowlist of the caller's variables (ALLOWED) plus PYTHONDONTWRITEBYTECODE=1; the rule
               set's own `env` is added per step (gate_run). Everything else is dropped: PYTEST_ADDOPTS=--co
               (it disarms pytest), PYTHONPATH, NODE_OPTIONS, CLAUDE_PLUGIN_ROOT (Claude Code exports it to
               plugin hooks; this repository's own tests read it). PATH keeps only absolute entries outside the
               repository (its working tree, its main checkout, its git directory): a relative entry or one
               inside the repository lets an untracked file (`.venv/bin`, `node_modules/.bin`) stand in for a
               command a check runs.
  {python}     the interpreter that runs the gate itself (sys.executable, chosen by hooks/run-python.sh): the
               hooks already trust it to judge. Never the repository's `.venv`. Its identity is what a check
               sees when it starts it (one run with the check environment, PROBE): the executable, its real
               path, its version, its prefixes, its import path and the distributions in its site directories
               (a `pip install` into it changes the key). An interpreter that would import from the repository
               (it lives there, or an editable install of the working copy is on its path) is refused.
  digest       12 hex of the canonical form of both: the runner component of the key.

Pure data except ``interpreter``, which starts the interpreter once (no network, no timer: what bounds it is
the interpreter's own start-up and a listing of its site directories).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from typing import NamedTuple

import gate_config as config

ALLOWED = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
           "LC_MESSAGES", "TZ", "TERM", "SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR")  # source: POSIX (XBD 8.3) user, locale and temp variables, and the Windows ones a process needs to start
FIXED = {"PYTHONDONTWRITEBYTECODE": "1"}  # source: the checks run in a private checkout that is removed; no .pyc is written next to it
PROBE = (
    "import json, os, site, sys, sysconfig\n"
    "from importlib import metadata\n"
    "dirs = [*site.getsitepackages(), sysconfig.get_paths()['purelib'], sysconfig.get_paths()['platlib']]\n"
    "if site.ENABLE_USER_SITE:\n"
    "    dirs.append(site.getusersitepackages())\n"
    "dirs = [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]\n"
    "dists = sorted({(d.metadata['Name'] or '', d.version or '') for d in metadata.distributions(path=dirs)})\n"
    "print(json.dumps({'executable': sys.executable, 'real': os.path.realpath(sys.executable),\n"
    "                  'version': sys.version, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,\n"
    "                  'path': [p for p in sys.path if p], 'dists': dists}))\n"
)  # source: what `{python} -m <module>` imports from: sys.path after site processing, and what is installed there


class Refused(Exception):
    """The runner would make the verdict depend on the working copy; the gate refuses (closed)."""


class Runner(NamedTuple):
    env: dict  # the environment every check starts from (the rule set's env is added per step)
    python: dict | None  # the identity of {python} (PROBE), or None when no rule uses it
    digest: str


def _inside(path: str, directory: str) -> bool:
    inner, outer = os.path.realpath(path), os.path.realpath(directory)
    return inner == outer or inner.startswith(outer + os.sep)


def repository_dirs(top: str, common: str) -> tuple:
    """The directories that belong to the repository: the working tree, its main checkout, the git directory."""
    root = os.path.dirname(common) if os.path.basename(common) == ".git" else top
    return tuple(dict.fromkeys((top, root, common)))


def _path(value: str, repo: tuple) -> str:
    kept = [p for p in value.split(os.pathsep) if os.path.isabs(p) and not any(_inside(p, d) for d in repo)]
    return os.pathsep.join(dict.fromkeys(kept))


def environment(source: dict, repo: tuple) -> dict:
    """The allowlisted variables of ``source`` (PATH without entries in ``repo``), plus FIXED."""
    env = {k: source[k] for k in ALLOWED if k in source}
    if "PATH" in env:
        env["PATH"] = _path(env["PATH"], repo)
    return {**env, **FIXED}


def uses_python(rule_sets: list) -> bool:
    """True when a check or the tests of one of ``rule_sets`` start ``{python}``."""
    for rule_set in rule_sets:
        cfg = rule_set.cfg or {}
        argvs = [c["argv"] for c in cfg.get("checks", [])] + ([cfg["tests"]["argv"]] if cfg.get("tests") else [])
        if any(config.PY in argv for argv in argvs):
            return True
    return False


def interpreter(env: dict) -> dict:
    """The identity of sys.executable as a check started with ``env`` sees it. Raises Refused when it cannot run."""
    try:
        out = subprocess.run([sys.executable, "-c", PROBE], env=env, cwd=os.path.abspath(os.sep),
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
    except OSError as exc:  # FAILS_ON: the interpreter cannot be started with the check environment
        raise Refused(f"{sys.executable} cannot be started: {exc!r}") from exc
    if out.returncode != 0:
        raise Refused(f"{sys.executable} cannot describe itself (exit {out.returncode}): {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout)


def _refuse_repository_imports(python: dict, repo: tuple) -> None:
    where = [python["executable"], *python["path"]]
    inside = [p for p in where if os.path.isabs(p) and any(_inside(p, d) for d in repo)]
    if inside:
        raise Refused(f"the interpreter {python['executable']} imports from the repository ({inside[0]}), so a "
                      "verdict would depend on files that are not in the tree. Start Claude Code with a python3 "
                      "outside the repository on PATH")


def digest_of(env: dict, python: dict | None) -> str:
    canon = json.dumps({"env": env, "python": python}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def resolve(top: str, common: str, rule_sets: list, source: dict | None = None) -> Runner:
    """The runner of a verification in the repository at ``top`` under ``rule_sets``. Raises Refused."""
    repo = repository_dirs(top, common)
    env = environment(os.environ if source is None else source, repo)
    python = None
    if uses_python(rule_sets):
        python = interpreter(env)
        _refuse_repository_imports(python, repo)
    return Runner(env, python, digest_of(env, python))


def describe(runner: Runner) -> str:
    """One line naming the interpreter, for the worker's output and the denial."""
    if runner.python is None:
        return "no {python} in these rules"
    version = runner.python["version"].split()[0]
    return f"{{python}} = {runner.python['executable']} (Python {version}, {len(runner.python['dists'])} distributions)"
