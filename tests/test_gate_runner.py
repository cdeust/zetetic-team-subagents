"""hooks/lib/gate_runner.py on data: what a check runs with besides the tree and the rules (review round 5, B2).

In-process: the allowlist, PATH without the repository, the interpreter's identity and its refusals. The hook-level
attacks (a `.venv` shim, PYTEST_ADDOPTS, CLAUDE_PLUGIN_ROOT, another interpreter) are tests/test_gate_hermetic.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_rules  # noqa: E402
import gate_runner as runner  # noqa: E402

REPO = ("/w/repo", "/w/repo", "/w/repo/.git")
PY_CHECK = {"version": 1, "checks": [{"name": "c", "argv": ["{python}", "-c", "pass"]}]}
SH_CHECK = {"version": 1, "checks": [{"name": "c", "argv": ["sh", "-c", "true"]}]}


def test_the_environment_is_the_allowlist_and_path_loses_the_repository(tmp_path):
    source = {"PATH": os.pathsep.join(["/usr/bin", "/w/repo/node_modules/.bin", "relative/bin", ".", "/w/repo/.git/x",
                                       "/usr/bin", "/opt/tools"]),
              "HOME": "/h", "LANG": "C", "PYTEST_ADDOPTS": "--co", "CLAUDE_PLUGIN_ROOT": "/p", "PYTHONPATH": "/x",
              "GH_TOKEN": "secret"}
    env = runner.environment(source, REPO)
    assert env == {"PATH": os.pathsep.join(["/usr/bin", "/opt/tools"]), "HOME": "/h", "LANG": "C",
                   "PYTHONDONTWRITEBYTECODE": "1"}  # no token, no pytest option, no repository entry, no duplicate


def test_the_repository_directories_include_the_main_checkout_of_a_worktree():
    assert runner.repository_dirs("/w/repo/.claude/worktrees/x", "/w/repo/.git") == (
        "/w/repo/.claude/worktrees/x", "/w/repo", "/w/repo/.git")
    assert runner.repository_dirs("/w/bare-ish", "/w/store.git") == ("/w/bare-ish", "/w/store.git")


@pytest.mark.parametrize("rule_set,uses", [
    (gate_rules.RuleSet("config", PY_CHECK, None), True), (gate_rules.RuleSet("config", SH_CHECK, None), False),
    (gate_rules.RuleSet("stack", {"version": 1, "tests": {"argv": ["{python}", "-m", "pytest", "{tests}"]}}, None), True),
    (gate_rules.RuleSet("legacy", None, "a" * 40, "b" * 40), False),
])
def test_python_is_measured_only_when_a_rule_starts_it(rule_set, uses):
    assert runner.uses_python([rule_set]) is uses


def test_the_identity_is_what_a_check_sees_and_it_is_in_the_digest():
    env = runner.environment(dict(os.environ), REPO)
    found = runner.interpreter(env)
    assert found["executable"] == sys.executable and found["version"] == sys.version
    assert all(isinstance(d, list) and len(d) == 2 for d in found["dists"])
    other = {**found, "dists": found["dists"] + [["injected", "1.0"]]}
    assert runner.digest_of(env, found) != runner.digest_of(env, other)  # a pip install changes the key
    assert runner.digest_of(env, found) != runner.digest_of({**env, "LANG": "x"}, found)


def test_an_interpreter_that_cannot_describe_itself_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.sys, "executable", str(tmp_path / "absent-python"))
    with pytest.raises(runner.Refused, match="cannot be started"):
        runner.interpreter({"PATH": "/usr/bin"})
    failing = tmp_path / "python"
    failing.write_text("#!/bin/sh\necho broken >&2\nexit 3\n")
    failing.chmod(0o755)
    monkeypatch.setattr(runner.sys, "executable", str(failing))
    with pytest.raises(runner.Refused, match="exit 3"):
        runner.interpreter({"PATH": "/usr/bin"})


@pytest.mark.parametrize("where", [{"executable": "/w/repo/.venv/bin/python", "path": []},
                                   {"executable": "/usr/bin/python3", "path": ["/usr/lib/python3", "/w/repo/src"]}])
def test_an_interpreter_that_imports_from_the_repository_is_refused(where):
    with pytest.raises(runner.Refused, match="imports from the repository"):
        runner._refuse_repository_imports(where, REPO)
    runner._refuse_repository_imports({"executable": "/usr/bin/python3", "path": ["/usr/lib", "relative"]}, REPO)


def test_the_description_names_the_interpreter_or_says_there_is_none():
    assert runner.describe(runner.Runner({}, None, "d" * 12)) == "no {python} in these rules"
    told = runner.describe(runner.Runner({}, {"executable": "/usr/bin/python3", "version": "3.9.6 (default)",
                                              "dists": [["a", "1"]]}, "d" * 12))
    assert told == "{python} = /usr/bin/python3 (Python 3.9.6, 1 distributions)"
