"""CI partitions one dynamic suite inventory without losing failure evidence."""

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def add_suite(root, path, label, result=0):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "{label}" >> "$TRACE"\nexit {result}\n'
    )


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "repository"
    (root / "tests").mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/run-all.sh", root / "tests/run-all.sh")
    # run-all.sh resolves the pytest interpreter through tools/dev-python.sh (#171).
    (root / "tools").mkdir()
    shutil.copy2(ROOT / "tools/dev-python.sh", root / "tools/dev-python.sh")
    binary = root / "bin"
    binary.mkdir()
    python = binary / "fixture-python"
    python.write_text("""#!/bin/bash
if [[ "$1" == -c ]]; then
  [[ "$2" != *sysconfig* ]] || printf '%s\n' "$FIXTURE_BIN"
  [[ "$2" != 'import pytest' || "${PYTEST_MISSING:-0}" != 1 ]]
else
  printf '%s\n' pytest >> "$TRACE"
  exit "${PYTEST_EXIT:-0}"
fi
""")
    python.chmod(0o755)
    trace = tmp_path / "trace"
    env = {
        **os.environ,
        "PYTHON_BIN": str(python),
        "TRACE": str(trace),
        "FIXTURE_BIN": str(binary),
    }
    add_suite(root, "tools/tests/first/run-tests.sh", "tool")
    add_suite(root, "scripts/test-extra.sh", "script")
    add_suite(root, "scripts/test-memory-first.sh", "memory")
    return root, env, trace


def run(fixture, *args):
    root, env, trace = fixture
    result = subprocess.run(
        ["bash", str(root / "tests/run-all.sh"), *args],
        env=env,
        text=True,
        capture_output=True,
    )
    events = trace.read_text().splitlines() if trace.exists() else []
    return result, events


def test_default_retains_python_and_every_discovered_shell_suite(fixture):
    result, events = run(fixture)
    assert result.returncode == 0, result.stderr + result.stdout
    assert Counter(events) == Counter(["pytest", "tool", "script", "memory"])


@pytest.mark.parametrize(
    "group,expected", [("regression", ["tool", "script"]), ("e2e", ["memory"])]
)
def test_ci_categories_execute_only_their_discovered_shell_suites(
    fixture, group, expected
):
    result, events = run(fixture, "--group", group)
    assert result.returncode == 0, result.stderr + result.stdout
    assert Counter(events) == Counter(expected)


def test_new_suites_are_discovered_without_registration_and_partitions_are_exact(
    fixture,
):
    root, _env, _trace = fixture
    add_suite(root, "tools/tests/new-suite/run-tests.sh", "new-tool")
    add_suite(root, "scripts/test-new.sh", "new-script")
    add_suite(root, "scripts/test-memory-new.sh", "new-memory")
    all_suites, events = run(fixture, "--list")
    regression, _ = run(fixture, "--list", "--group", "regression")
    e2e, _ = run(fixture, "--group", "e2e", "--list")
    assert all_suites.returncode == regression.returncode == e2e.returncode == 0
    actual = set(all_suites.stdout.splitlines()[1:])
    reg, memory = set(regression.stdout.splitlines()), set(e2e.stdout.splitlines())
    assert actual == reg | memory
    assert not reg & memory
    assert "scripts/test-memory-new.sh" in memory
    assert "tools/tests/new-suite/run-tests.sh" in reg
    assert "scripts/test-new.sh" in reg
    assert events == []


@pytest.mark.parametrize("group", ["regression", "e2e"])
def test_orphan_blocks_every_category_before_any_suite_executes(fixture, group):
    add_suite(fixture[0], "tools/tests/first/nested/run-tests.sh", "orphan")
    result, events = run(fixture, "--group", group)
    assert result.returncode != 0
    assert "not discovered" in result.stderr
    assert events == []


@pytest.mark.parametrize(
    "group,remove", [("regression", "non-memory"), ("e2e", "memory")]
)
def test_empty_category_fails_even_when_another_category_has_tests(
    fixture, group, remove
):
    root = fixture[0]
    paths = (
        list(root.glob("scripts/test-memory-*.sh"))
        if remove == "memory"
        else [root / "scripts/test-extra.sh", root / "tools/tests/first/run-tests.sh"]
    )
    for path in paths:
        path.unlink()
    result, events = run(fixture, "--group", group)
    assert result.returncode != 0
    assert "0 shell suites" in result.stderr
    assert events == []


@pytest.mark.parametrize(
    "group,path",
    [
        ("regression", "scripts/test-failing.sh"),
        ("e2e", "scripts/test-memory-failing.sh"),
    ],
)
def test_failure_is_collected_and_cannot_be_hidden_by_a_later_success(
    fixture, group, path
):
    add_suite(fixture[0], path, "failure", result=1)
    result, events = run(fixture, "--group", group)
    assert result.returncode == 1
    assert "failure" in events
    assert len(events) > 1
    assert path in result.stdout
    assert "pytest" not in events


def test_default_still_reports_missing_pytest_as_failure(fixture):
    fixture[1]["PYTEST_MISSING"] = "1"
    result, events = run(fixture)
    assert result.returncode == 1
    assert "pytest is not installed" in result.stdout
    assert set(events) == {"tool", "script", "memory"}


@pytest.mark.parametrize("group", ["regression", "e2e"])
def test_the_shell_groups_resolve_no_python(fixture, group):
    # The regression and e2e jobs run shell suites only; a full run alone needs
    # pytest, so only it calls tools/dev-python.sh (#171), which may create a venv.
    root = fixture[0]
    stub = root / "tools/dev-python.sh"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" dev-python >> "$TRACE"\nexit 1\n')
    stub.chmod(0o755)
    for args in (("--group", group), ("--list", "--group", group)):
        result, events = run(fixture, *args)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "dev-python" not in events
    fixture[2].unlink()  # the trace of the shell-group runs above
    result, events = run(fixture)
    assert result.returncode == 1
    assert events == ["dev-python"]
    assert "FATAL: tools/dev-python.sh" in result.stderr


@pytest.mark.parametrize("args", [("--group",), ("--group", "unknown"), ("--unknown",)])
def test_invalid_selection_fails_without_execution(fixture, args):
    result, events = run(fixture, *args)
    assert result.returncode == 2
    assert events == []


def test_real_repository_discovery_matches_disk_and_both_ci_partitions():
    def listing(*args):
        return subprocess.check_output(
            ["bash", str(ROOT / "tests/run-all.sh"), "--list", *args], text=True
        ).splitlines()

    all_suites = listing()[1:]
    regression = listing("--group", "regression")
    e2e = listing("--group", "e2e")
    disk = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("tools/tests/**/run-tests.sh", "scripts/test-*.sh")
        for path in ROOT.glob(pattern)
    }
    assert set(all_suites) == disk == set(regression) | set(e2e)
    assert len(all_suites) == len(set(all_suites))
    assert not set(regression) & set(e2e)
    assert regression and e2e


def install_template_wrapper(fixture):
    root, env, _trace = fixture
    wrapper = root / "tools/tests/ci-template/run-tests.sh"
    wrapper.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tools/tests/ci-template/run-tests.sh", wrapper)
    template = root / "templates/ci/pipeline.yml"
    template.parent.mkdir(parents=True)
    template.write_text("name: fixture\n")
    actionlint = root / "bin/actionlint"
    actionlint.write_text("#!/bin/sh\nexit 0\n")
    actionlint.chmod(0o755)
    return wrapper, env


def test_regression_wrapper_does_not_repeat_python_assertions(fixture):
    install_template_wrapper(fixture)
    result, events = run(fixture, "--group", "regression")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pytest" not in events


def test_standalone_template_wrapper_preserves_python_assertions(fixture):
    wrapper, env = install_template_wrapper(fixture)
    env.pop("RUN_ALL_GROUP", None)
    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert fixture[2].read_text().splitlines() == ["pytest"]


def test_ci_assigns_the_disjoint_groups_and_keeps_python_coverage_in_unit():
    config = json.loads((ROOT / "ci.json").read_text())
    assert "coverage run -m pytest -q" in config["unit"]
    assert "bash tests/run-all.sh --group regression" in config["regression"]
    assert "bash tests/run-all.sh --group e2e" in config["e2e"]
