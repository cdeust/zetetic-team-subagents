"""Native merge gate: a red merge names the condition that made it red.

Source: Pipeline merge job of cdeust/Cortex run 40583904933 (a deliberate
"do not merge" title), reported as "closed, draft, held, or no longer at the
tested head". Attribution of every failed gate of 2026-10-27/28:
docs/verification/native-gate-patience-20261029.md. The step runs under the
shell GitHub uses (`bash --noprofile --norc -eo pipefail`) through the harness
of test_ci_pr_safety, so an empty or failed `gh pr view` is exercised as in CI.
"""

import json
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from test_ci_pr_safety import GH_STUB, execute
from test_ci_template import heredoc

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"
SHA = "a" * 40
MOVED = "b" * 40
STEP = "Verify live PR eligibility"


@pytest.fixture(scope="module")
def jobs():
    return yaml.safe_load((NATIVE / "pipeline.yml").read_text())["jobs"]


def run_eligibility(jobs, tmp_path, payload, rc="0"):
    """Run the merge job's eligibility step against a stubbed `gh pr view`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = next(s["run"] for s in jobs["merge"]["steps"] if s.get("name") == STEP)
    result = execute(
        script,
        tmp_path,
        {"FIXTURE_PR": payload, "FIXTURE_VIEW_RC": rc, "HEAD_SHA": SHA, "REVIEW_STATE": "success"},
        GH_STUB,
    )
    return result.returncode, result.stdout


def pull(**changes):
    live = {"state": "OPEN", "isDraft": False, "headRefOid": SHA, "title": "fix: x"}
    return {**live, "labels": [], **changes}


@pytest.mark.parametrize(
    "changes, cause",
    [
        ({"state": "MERGED"}, "is not open (MERGED)"),
        ({"state": "CLOSED"}, "is not open (CLOSED)"),
        ({"isDraft": True}, "is a draft"),
        ({"headRefOid": MOVED}, f"head moved: tested {SHA}, live {MOVED}"),
        ({"title": "do not merge: probe"}, "is held by title"),
        ({"title": "Fix: Do Not Merge yet"}, "is held by title"),
        ({"labels": [{"name": "Hold"}]}, "is held by label"),
        ({"labels": [{"name": "DO-NOT-MERGE"}]}, "is held by label"),
    ],
)
def test_red_merge_names_the_condition_that_failed(jobs, tmp_path, changes, cause):
    assert run_eligibility(jobs, tmp_path / "ok", json.dumps(pull()))[0] == 0  # control
    code, out = run_eligibility(jobs, tmp_path / "red", json.dumps(pull(**changes)))
    assert code == 1
    assert f"::error::PR {cause}." in out


@pytest.mark.parametrize(
    "payload",
    ["", "   ", "\n\t", "\ufeff", "\ufeff  \n"],
    ids=["empty", "spaces", "blank", "bom", "bom-blank"],
)
def test_payload_without_a_value_is_refused_not_passed(jobs, tmp_path, payload):
    # Fail-open before: jq prints nothing for these inputs (it skips a BOM), so
    # no cause was found and the step passed with rc=0. The single-sentence form
    # (`jq -e`, rc=4) failed here.
    code, out = run_eligibility(jobs, tmp_path, payload)
    assert code == 1
    assert "::error::PR state is unreadable." in out


# Characterization, green on e4c16fc by construction: a future `|| true` or
# `2>/dev/null` around jq would break these.
@pytest.mark.parametrize("payload", ["not json", "{"], ids=["text", "truncated"])
def test_unparsable_payload_from_gh_is_refused(jobs, tmp_path, payload):
    code, out = run_eligibility(jobs, tmp_path, payload)
    assert code == 1
    assert "::error::PR state is unreadable." in out


@pytest.mark.parametrize("rc", ["1", "4"])
def test_failed_gh_read_is_refused_and_named(jobs, tmp_path, rc):
    # rc=4 failed on e4c16fc with rc=4 and no annotation.
    code, out = run_eligibility(jobs, tmp_path, json.dumps(pull()), rc=rc)
    assert code == 1
    assert "::error::PR state is unreadable." in out


def test_two_json_documents_are_refused(jobs, tmp_path):
    two = json.dumps(pull()) + "\n" + json.dumps(pull())
    assert run_eligibility(jobs, tmp_path, two)[0] == 1


# Characterization of the native `resolve` job (pipeline-post-merge.yml). Green on
# origin/main by construction: they pin an invariant this change must not break.
# tests/test_ci_post_merge.py covers tools/ci_post_merge.py, which has no
# `merge pending review` branch, so the inline native resolver had no test.
RUNNERS = ("ubuntu-latest", "macos-latest", "windows-latest")
MATRIX = [f"{kind} ({runner})" for kind in ("environment", "install") for runner in RUNNERS]


def resolver(jobs, tmp_path):
    """The native resolve job's inline source, loaded as a module."""
    step = next(s for s in jobs["resolve"]["steps"] if s.get("name") == "Resolve protected merge")
    command = step["run"]
    source = heredoc(command, "python3")
    module = ModuleType("native_resolve")
    module.__file__ = str(tmp_path / "native_resolve.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def source_run(head, repository):
    return {
        "id": 9, "event": "pull_request", "status": "completed",
        "conclusion": "success", "head_branch": "topic", "run_attempt": 1,
        "head_sha": head, "path": ".github/workflows/pipeline.yml",
        "name": "Pipeline", "head_repository": {"full_name": repository},
        "pull_requests": [{"number": 7}], "actor": {"login": "owner"},
    }


def open_pull(head, repository):
    repo = {"full_name": repository}
    return {
        "number": 7, "state": "open", "draft": False, "title": "fix", "labels": [],
        "head": {"sha": head, "repo": repo}, "base": {"ref": "main", "repo": repo},
    }


def green_jobs(head, merge_job):
    names = ["contract", "unit", "regression", "e2e", "review", merge_job, *MATRIX]
    return [
        {"id": 100 + n, "name": name, "run_attempt": 1, "run_id": 9,
         "head_sha": head, "status": "completed", "conclusion": "success"}
        for n, name in enumerate(names)
    ]


class FakeGitHub:
    def __init__(self, tested, live, merge_job):
        self.calls = []
        self.run = source_run(tested, "o/r")
        self.pr = open_pull(live, "o/r")
        self.jobs = green_jobs(tested, merge_job)

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if path.endswith("/actions/runs/9"):
            return self.run
        if path.endswith("/pulls/7"):
            return self.pr
        raise AssertionError(f"unexpected request {method} {path}")

    def records(self, path, key=None):
        self.calls.append(("GET", path))
        return iter(self.jobs)

    def merges(self):
        return [call for call in self.calls if call[0] == "PUT"]


def resolve(module, api):
    event = {"repository": {"full_name": "o/r"}, "workflow_run": dict(api.run)}
    return module.resolve(event, "o/r", api)


def test_superseded_run_does_not_trigger_merge(jobs, tmp_path):
    # The PR head moved after this run tested SHA: the new head's run decides.
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, MOVED, "merge")
    with pytest.raises(module.PostMergeError, match="head advanced"):
        resolve(module, api)
    assert api.merges() == []


def test_pending_run_does_not_trigger_merge(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge pending review")
    assert resolve(module, api)["run_tests"] == "false"
    assert api.merges() == []


def rerun_jobs(head, attempts):
    """One job record per (attempt, name); ids stay unique across attempts."""
    rows = []
    for attempt, names in enumerate(attempts, start=1):
        for name in names:
            rows.append({
                "id": 100 * attempt + len(rows), "name": name, "run_attempt": attempt,
                "run_id": 9, "head_sha": head, "status": "completed", "conclusion": "success",
            })
    return rows


def test_stale_merge_attempt_cannot_authorize_a_pending_rerun(jobs, tmp_path):
    # Source: Codex finding session-optimizer PR87 discussion_r4409903427.
    # Attempt 1 passed `merge`; the partial rerun of review (attempt 2) now waits
    # for reviews. Only the newest logical merge job may decide.
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.run["run_attempt"] = 2
    api.jobs = rerun_jobs(SHA, [
        ["contract", "unit", "regression", "e2e", "review", "merge", *MATRIX],
        ["review", "merge pending review"],
    ])
    assert resolve(module, api)["run_tests"] == "false"
    assert api.merges() == []


def test_merge_aliases_in_one_attempt_are_rejected(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.jobs = rerun_jobs(SHA, [
        ["contract", "unit", "regression", "e2e", "review", "merge",
         "merge pending review", *MATRIX],
    ])
    with pytest.raises(module.PostMergeError, match="duplicate job name in one attempt"):
        resolve(module, api)
    assert api.merges() == []
