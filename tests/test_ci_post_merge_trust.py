"""A completed merge must still belong to the trusted main branch."""

from copy import deepcopy
import json

import pytest

from test_ci_post_merge import (
    COMPARE_PATH,
    HEAD,
    MERGED,
    PR_PATH,
    PUSH_PATH,
    REPO,
    execute,
    resolver,
)
from test_ci_post_merge import scenario as scenario


@pytest.mark.parametrize("already_merged", [False, True])
@pytest.mark.parametrize(
    "comparison",
    [
        {"status": "ahead", "merge_base_commit": {"sha": MERGED}},
        {"status": "diverged", "merge_base_commit": {"sha": MERGED}},
        {"status": "behind", "merge_base_commit": {"sha": HEAD}},
        {"status": "identical", "merge_base_commit": {}},
        {},
    ],
)
def test_merge_outside_main_never_authorizes_tests_or_dedup(
    scenario, already_merged, comparison
):
    if already_merged:
        scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", COMPARE_PATH)] = comparison
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert not any(path == PUSH_PATH for _, path, _ in scenario[-1])


@pytest.mark.parametrize(
    "field,value",
    [
        ("base", {"ref": "untrusted", "repo": {"full_name": REPO}}),
        ("head", {"sha": "c" * 40, "repo": {"full_name": REPO}}),
    ],
)
def test_retarget_or_head_change_during_merge_never_returns_sha(scenario, field, value):
    def merge_after_change():
        scenario[2][field] = value
        return {"merged": True, "sha": MERGED}

    scenario[3][("PUT", PR_PATH + "/merge")] = merge_after_change
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)


@pytest.mark.parametrize("status", ["behind", "identical"])
def test_confirmed_main_membership_is_checked_before_output(scenario, status):
    scenario[3][("GET", COMPARE_PATH)]["status"] = status
    assert execute(scenario)["tested_sha"] == MERGED
    assert scenario[-1][-2:] == [("GET", PR_PATH, None), ("GET", COMPARE_PATH, None)]


@pytest.mark.parametrize("changes", [{"merged": False}, {"merge_commit_sha": HEAD}])
def test_after_merge_pr_must_confirm_the_exact_returned_commit(scenario, changes):
    original = deepcopy(scenario[2])

    def changed_reply():
        if any(method == "PUT" for method, _, _ in scenario[-1]):
            return {**scenario[2], **changes}
        return original

    scenario[3][("GET", PR_PATH)] = changed_reply
    with pytest.raises(resolver.PostMergeError, match="confirm the returned merge"):
        execute(scenario)


@pytest.mark.parametrize("already_merged", [False, True])
def test_foreign_merge_cli_writes_no_output(
    scenario, tmp_path, monkeypatch, already_merged
):
    if already_merged:
        scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", COMPARE_PATH)] = {"status": "ahead"}
    event = tmp_path / "event.json"
    event.write_text(json.dumps(scenario[0]))
    output = tmp_path / "output"
    for key, value in {
        "GITHUB_EVENT_NAME": "workflow_run",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": REPO,
        "GH_TOKEN": "fixture-token",
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    assert resolver.main() == 1
    assert not output.exists()
    assert not any(path == PUSH_PATH for _, path, _ in scenario[-1])
