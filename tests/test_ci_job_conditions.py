"""Fail-closed job gates after a skipped resolve ancestor (run40018808255)."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = yaml.safe_load((ROOT / "templates/ci/pipeline.yml").read_text())["jobs"]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
GUARDED = (*CATEGORIES, "tag")


def dependencies(job):
    needs = JOBS[job]["needs"]
    return [needs] if isinstance(needs, str) else needs


def allows(job, results, **context):
    """Evaluate this fixture's conjunctions; hosted execution remains required."""
    expression = JOBS[job]["if"]
    expression = re.sub(
        r"needs\.(\w+)\.result", lambda m: repr(results[m[1]]), expression
    )
    expression = expression.replace(
        "github.event_name", repr(context.get("event", "pull_request"))
    )
    expression = expression.replace(
        "github.ref", repr(context.get("ref", "refs/heads/main"))
    )
    expression = expression.replace(
        "!cancelled()", repr(not context.get("cancelled", False))
    )
    expression = expression.replace("&&", " and ").replace("||", " or ")
    assert re.fullmatch(r"[\s()'a-zA-Z_=/]+", expression)
    return eval(expression.strip(), {"__builtins__": {}}, {})


@pytest.mark.parametrize("job", GUARDED)
def test_explicit_status_function_and_each_declared_dependency_required(job):
    condition = JOBS[job]["if"]
    assert "!cancelled()" in condition
    assert "always()" not in condition
    assert set(re.findall(r"needs\.(\w+)\.result", condition)) == set(dependencies(job))
    assert "resolve" not in dependencies(job)


@pytest.mark.parametrize("job", GUARDED)
@pytest.mark.parametrize("state", ["failure", "skipped", "cancelled", "timed_out", ""])
def test_every_unsuccessful_dependency_blocks_each_downstream_job(job, state):
    results = {name: "success" for name in dependencies(job)}
    for dependency in dependencies(job):
        mutated = {**results, dependency: state}
        assert not allows(job, mutated, event="push"), (job, dependency, state)


@pytest.mark.parametrize("job", GUARDED)
def test_cancellation_vetoes_even_successful_dependencies(job):
    results = {name: "success" for name in dependencies(job)}
    assert not allows(job, results, event="push", cancelled=True)


@pytest.mark.parametrize("job", CATEGORIES)
@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_run"])
def test_categories_run_after_successful_direct_dependencies_with_skipped_resolve(
    job, event
):
    results = {name: "success" for name in dependencies(job)}
    results["resolve"] = "skipped"
    assert allows(job, results, event=event)


@pytest.mark.parametrize(
    "event,expected", [("push", True), ("workflow_run", True), ("pull_request", False)]
)
def test_tag_only_publishes_supported_events_after_all_success(event, expected):
    results = {name: "success" for name in dependencies("tag")}
    assert allows("tag", results, event=event) is expected


@pytest.mark.parametrize("ref", ["refs/heads/feature", "refs/tags/release"])
def test_reusable_pipeline_cannot_publish_from_another_push_ref(ref):
    results = {name: "success" for name in dependencies("tag")}
    assert not allows("tag", results, event="push", ref=ref)
