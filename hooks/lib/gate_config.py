"""The gate's per-repo configuration and the rule that turns a change into the checks to run.

``.zetetic/gate.json`` (docs/gate.md) declares the checks. This module is pure: it reads the config
file and the file tree it is given, and returns data. It runs nothing, writes nothing, takes no git.

Declaration, in order (``declaration(top)``):
  1. ``.zetetic/gate.json`` with ``"off": true``, or the legacy ``.zetetic-gate.json`` with
     ``"off": true``                                     -> not gated
  2. ``.zetetic/gate.json``                              -> "config"
  3. an executable ``scripts/gate.sh``                   -> "legacy" (the repo's own script is the check)
  4. a recognised stack (Cargo.toml, package.json with a lint/test script, pytest project, go.mod)
                                                         -> "stack" (that stack's whole suite)
  5. otherwise                                           -> not gated
"""
from __future__ import annotations

import json
import os
import re
from typing import NamedTuple

CONFIG_REL = os.path.join(".zetetic", "gate.json")
LEGACY_OFF = ".zetetic-gate.json"
LEGACY_SCRIPT = os.path.join("scripts", "gate.sh")
PY = "{python}"  # whole-argv-element placeholder: the interpreter the gate resolved
FILES = "{files}"  # whole-argv-element placeholder: the changed files this check applies to
TESTS = "{tests}"  # whole-argv-element placeholder: the selected test paths
DEFAULT_FULL_ON = [".zetetic/gate.json"]  # source: a change to the rules runs every check the new rules declare (always in full_on)
_TOP_KEYS = {"version", "off", "full_on", "checks", "tests", "env", "link"}
_CHECK_KEYS = {"name", "paths", "argv"}
_TESTS_KEYS = {"argv", "files", "map", "same_name", "fast"}


class ConfigError(ValueError):
    """The config file exists but is not valid; the gate refuses rather than guess."""


class Step(NamedTuple):
    name: str
    argv: list


# ------------------------------------------------------------------------ glob


def glob_regex(pattern: str) -> re.Pattern:
    """``**/`` any directories (or none), ``**`` anything, ``*`` within one segment, ``?`` one character."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(patterns: list, path: str) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


# ------------------------------------------------------------------ the file


def _list_of_str(value: object, where: str) -> list:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return value


def _validate_check(check: object, n: int) -> None:
    if not isinstance(check, dict) or set(check) - _CHECK_KEYS or not {"name", "argv"} <= set(check):
        raise ConfigError(f"checks[{n}] must be an object with name and argv (and optionally paths)")
    if not isinstance(check["name"], str) or not check["name"]:
        raise ConfigError(f"checks[{n}].name must be a non-empty string")
    if not _list_of_str(check["argv"], f"checks[{n}].argv"):
        raise ConfigError(f"checks[{n}].argv must not be empty")
    if "paths" in check:
        _list_of_str(check["paths"], f"checks[{n}].paths")


def _validate_tests(tests: object) -> None:
    if not isinstance(tests, dict) or set(tests) - _TESTS_KEYS or "argv" not in tests:
        raise ConfigError("tests must be an object with argv (keys: " + ", ".join(sorted(_TESTS_KEYS)) + ")")
    if TESTS not in _list_of_str(tests["argv"], "tests.argv"):
        raise ConfigError(f"tests.argv must contain the element {TESTS}")
    for key in ("files", "fast"):
        _list_of_str(tests.get(key, []), f"tests.{key}")
    if not isinstance(tests.get("same_name", ""), str):
        raise ConfigError("tests.same_name must be a string")
    for n, entry in enumerate(tests.get("map", [])):
        if not isinstance(entry, dict) or set(entry) != {"paths", "tests"}:
            raise ConfigError(f"tests.map[{n}] must be an object with paths and tests")
        _list_of_str(entry["paths"], f"tests.map[{n}].paths")
        _list_of_str(entry["tests"], f"tests.map[{n}].tests")


def _validate_setup(cfg: dict) -> None:
    env = cfg.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ConfigError("env must be an object of string values")
    for rel in _list_of_str(cfg.get("link", []), "link"):
        if os.path.isabs(rel) or ".." in rel.split("/") or not rel:
            raise ConfigError(f"link entries are paths inside the repository, got {rel!r}")


def validate(cfg: object) -> dict:
    """Pre: ``cfg`` is parsed JSON. Post: the same object, or ConfigError naming the first problem."""
    if not isinstance(cfg, dict) or set(cfg) - _TOP_KEYS:
        raise ConfigError("the gate config must be an object with keys: " + ", ".join(sorted(_TOP_KEYS)))
    if cfg.get("version") != 1:
        raise ConfigError('"version" must be 1')
    _list_of_str(cfg.get("full_on", []), "full_on")
    _validate_setup(cfg)
    checks = cfg.get("checks", [])
    if not isinstance(checks, list):
        raise ConfigError("checks must be a list")
    for n, check in enumerate(checks):
        _validate_check(check, n)
    if "tests" in cfg:
        _validate_tests(cfg["tests"])
    if not checks and "tests" not in cfg and not cfg.get("off"):
        raise ConfigError('a gate with no "checks" and no "tests" verifies nothing; declare one or set "off": true')
    return cfg


def _read_json(path: str) -> object:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path} is unreadable or not JSON: {exc}") from exc


def load(root: str) -> dict | None:
    """The validated ``.zetetic/gate.json`` under ``root``, or None when absent."""
    raw = _read_json(os.path.join(root, CONFIG_REL))
    return None if raw is None else validate(raw)


# --------------------------------------------------------------- declaration


def _is_exec(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _npm(top: str) -> list:
    try:
        with open(os.path.join(top, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    if isinstance(scripts.get("lint"), str):
        out.append({"name": "lint", "argv": ["npm", "run", "lint", "--silent"]})
    test = scripts.get("test")
    if isinstance(test, str) and "no test specified" not in test:
        out.append({"name": "test", "argv": ["npm", "test", "--silent"]})
    return out


def _python(top: str) -> list:
    marks = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    has_project = any(os.path.isfile(os.path.join(top, m)) for m in marks)
    has_tests = os.path.isdir(os.path.join(top, "tests")) or any(
        n.startswith("test_") and n.endswith(".py") for n in os.listdir(top))
    return [{"name": "test", "argv": [PY, "-m", "pytest", "-q"]}] if has_project and has_tests else []


def stack_config(top: str) -> dict | None:
    """The documented default (rule 4): the whole suite of the stack found in ``top``, as a config.

    Dependencies live outside the tree (node_modules, a cargo target dir), so the config links the first
    from the main checkout and points the second at a directory shared by every verification.
    """
    checks: list = []
    env: dict = {}
    if os.path.isfile(os.path.join(top, "Cargo.toml")):
        checks += [{"name": "fmt", "argv": ["cargo", "fmt", "--all", "--check"]},
                   {"name": "clippy", "argv": ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"]},
                   {"name": "test", "argv": ["cargo", "test", "--workspace"]}]
        env["CARGO_TARGET_DIR"] = "{common}/zetetic-gate-target"
    npm = _npm(top)
    checks += npm + _python(top)
    if os.path.isfile(os.path.join(top, "go.mod")):
        checks += [{"name": "vet", "argv": ["go", "vet", "./..."]}, {"name": "test", "argv": ["go", "test", "./..."]}]
    if not checks:
        return None
    return {"version": 1, "checks": checks, "env": env, "link": ["node_modules"] if npm else []}


def setup_for(cfg: dict, top: str, common: str) -> tuple[dict, list]:
    """(environment additions, repository paths to link from ``top``), placeholders {top} and {common} resolved."""
    env = {k: v.replace("{top}", top).replace("{common}", common) for k, v in cfg.get("env", {}).items()}
    return env, list(cfg.get("link", []))


def declaration(top: str) -> str | None:
    """"config" | "legacy" | "stack" | None (not gated). Raises ConfigError for an invalid config file."""
    for off_file in (CONFIG_REL, LEGACY_OFF):
        raw = _read_json(os.path.join(top, off_file))
        if isinstance(raw, dict) and raw.get("off") is True:
            return None
    if load(top) is not None:
        return "config"
    if _is_exec(os.path.join(top, LEGACY_SCRIPT)):
        return "legacy"
    return "stack" if stack_config(top) else None


def declared_above(start: str) -> bool:
    """Git-independent fallback: an ancestor carries an EXPLICIT declaration (config or legacy script).

    Used when git cannot answer. The stack default is not consulted: guessing a stack from an ancestor
    of a non-repository would gate unrelated directories.
    """
    cur = os.path.abspath(start)
    while True:
        try:
            if declaration(cur) in ("config", "legacy"):
                return True
        except ConfigError:
            return True  # an invalid config is still a declaration: refuse rather than assume ungated
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


# ----------------------------------------------------------------- selection


def _walk(root: str) -> list:
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        found += [os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/") for f in files]
    return sorted(found)


def _expand(root: str, patterns: list) -> list:
    """Paths under ``root`` matching any pattern (a literal path is a pattern)."""
    if not any(set(p) & set("*?") for p in patterns):
        return [p for p in patterns if os.path.exists(os.path.join(root, p))]
    return [p for p in _walk(root) if matches(patterns, p)]


def _expand_argv(argv: list, placeholder: str, values: list) -> list:
    out: list = []
    for token in argv:
        out += values if token == placeholder else [token]
    return out


def _file_steps(cfg: dict, root: str, changed: list, full: bool) -> list:
    live = [p for p in changed if os.path.lexists(os.path.join(root, p))]
    universe = _walk(root) if full else live
    steps = []
    for check in cfg.get("checks", []):
        hit = [p for p in universe if "paths" not in check or matches(check["paths"], p)]
        if hit or "paths" not in check:  # no `paths`: runs whenever anything changed, deletions included
            steps.append(Step(check["name"], _expand_argv(check["argv"], FILES, hit)))
    return steps


def _select_tests(tests: dict, root: str, changed: list) -> list:
    chosen: list = []
    for entry in tests.get("map", []):
        if any(matches(entry["paths"], p) for p in changed):
            chosen += _expand(root, entry["tests"])
    template = tests.get("same_name", "")
    for p in changed:
        stem = os.path.splitext(os.path.basename(p))[0].replace("-", "_")  # a hook script's name is a test module's
        if template and not matches(tests.get("files", []), p):
            chosen += _expand(root, [template.replace("{stem}", stem)])
        if matches(tests.get("files", []), p) and os.path.lexists(os.path.join(root, p)):
            chosen.append(p)
    return list(dict.fromkeys(chosen))


def _test_step(cfg: dict, root: str, changed: list, full: bool) -> list:
    tests = cfg.get("tests")
    if not tests or not changed:
        return []
    chosen = [] if full else _select_tests(tests, root, changed)
    if not full and not chosen:
        chosen = _expand(root, tests.get("fast", []))
    if chosen:
        return [Step("tests", _expand_argv(tests["argv"], TESTS, chosen))]
    return [Step("tests-full", _expand_argv(tests["argv"], TESTS, []))]


def plan(cfg: dict, root: str, changed: list) -> list:
    """The steps to run for ``changed`` (repo-relative paths, deletions included) in the tree ``root``.

    Rules (docs/gate.md): a change to any ``full_on`` path runs every check over every file and the whole
    test suite. Otherwise a check runs iff a changed file still present matches its ``paths`` (no
    ``paths``: always), with {files} the matching ones; tests are the union of ``tests.map`` entries
    whose paths match a changed path, the ``same_name`` test of each changed file ({stem}: its name without extension, '-' as '_'), and changed test files
    themselves; none selected -> ``tests.fast``; still none -> the whole suite. No change -> no steps.
    """
    if not changed:
        return []
    full_on = DEFAULT_FULL_ON + cfg.get("full_on", [])
    full = any(matches(full_on, p) for p in changed)
    return _file_steps(cfg, root, changed, full) + _test_step(cfg, root, changed, full)
