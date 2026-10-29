"""A completed merge must still be the merge of the reviewed pull request, and main is never compared."""

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
def test_no_comparison_with_main_is_requested(scenario, already_merged):
    """Owner rule 2026-10-29: the resolver reads PR state only, never main's history."""
    if already_merged:
        scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[2]["merge_commit_sha"] = MERGED
    assert execute(scenario)["tested_sha"] == MERGED
    assert not any(path == COMPARE_PATH or "/compare/" in path for _, path, _ in scenario[-1])


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
def test_unconfirmed_merge_cli_writes_no_output(
    scenario, tmp_path, monkeypatch, already_merged
):
    if already_merged:
        scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", PR_PATH)] = {**scenario[2], "merged": False}
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
