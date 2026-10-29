# The Fix push leaves with the Claude App token

## Observation (2026-10-29)

PR #171: the `Fix` step of run 40820034691 (job `review`) pushed `ae628d6`. Read through GitHub REST:

- the commit's GitHub author and committer are `github-actions[bot]`. Its git identity is `claude[bot]`, `41898282+claude[bot]@users.noreply.github.com`;
- runs 40821184278 (CodeQL), 40821184389 (Pipeline) and 40821184277 (Workflow definition API capability) have `event: pull_request` and `actor: github-actions[bot]`. They stayed `action_required` with no job, the PR came from the same repository, and `pending_deployments` was empty. They started only after a manual `POST /repos/{o}/{r}/actions/runs/{id}/approve` (`triggering_actor: cdeust`, `run_attempt: 2`).

The `review` job log of run 40820034691 shows the cause:

- lines 103-107: `actions/checkout` v7.0.1 (`persist-credentials: true`, the default) writes `http.https://github.com/.extraheader` into `_temp/git-credentials-<uuid>.config`. It links that file through `includeIf.gitdir:<repo>/.git.path`;
- lines 917-923: the action exchanges OIDC for the Claude App token ("App token successfully obtained");
- lines 945-948: "Removing existing git authentication headers... No existing authentication headers to remove", followed by "Updated remote URL with authentication token".

`replaceCheckoutCredentials` in `src/github/operations/git-config.ts` of claude-code-action `8041f1d17e0e7d2f2cfe35002962e9f26237c0bb` (v1.0.263) unsets the header in the local config and in the files named by `include.path`. It never reads `includeIf.*.path`. The upstream default branch had the same code on 2026-10-29. The checkout's `GITHUB_TOKEN` header therefore stays in force, and git sends it instead of the App token that is in the URL.

## Rule (docs.github.com, read 2026-10-29)

From [Triggering a workflow from a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow):

> When you use the repository's `GITHUB_TOKEN` to perform tasks, events triggered by the `GITHUB_TOKEN` will not create a new workflow run, with the following exceptions:
> * `workflow_dispatch` and `repository_dispatch` events always create workflow runs.
> * `pull_request` events with the `opened`, `synchronize`, or `reopened` activity types: when a workflow using `GITHUB_TOKEN` creates or updates a pull request, the resulting `pull_request` event creates workflow runs in an **approval-required** state.

> If you do want to trigger a workflow from within a workflow run, you can use a GitHub App installation access token or a personal access token instead of `GITHUB_TOKEN` [...] Using one of these alternatives also lets `pull_request` workflows run automatically (without the approval prompt described above) when the pull request is created or updated by automation.

The same exception appears in [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). In this repository, the `claude[bot]` App push of `42f3c68` to main (2026-10-21) created five `push` runs without approval: 39679171579, 39679171691, 39679171604, 39679171651 and 39679171620.

## Mechanism reproduction (git 2.54.0)

A local HTTP server logs the `Authorization` header of each request. In the persist case, the checkout layout is replayed: the header goes in a side file linked by `includeIf.gitdir`. Both cases then run the action's cleanup in its own order and `git remote set-url origin http://x-access-token:APP_TOKEN@...`, followed by `git ls-remote origin`:

```text
case=persist action_removed_header=False header_still_effective=True sent=['x-access-token:GITHUB_TOKEN']
case=no-persist action_removed_header=False header_still_effective=False sent=['none', 'x-access-token:APP_TOKEN']
```

With the header persisted, git never sends the App token. Without it, git answers the 401 challenge with the App token.

## Change

On the `review` job's checkout in `templates/ci/pipeline.yml`, `persist-credentials: false` is set, and the workflows are re-rendered with `python3 scripts/lib/render_ci.py .`. After the checkout, the job's git calls are local (`git rev-parse`, `git diff`, `git log` on a `fetch-depth: 0` clone). `gh` reads `GH_TOKEN` from the environment. No secret is added, and the permissions are unchanged.

Options rejected:

- `workflow_dispatch` after the push: the `merge` gate and the `resolve` job consume only `pull_request` runs, so this would mean changing the gate. It also needs `actions: write`.
- Self-approval through `POST .../actions/runs/{id}/approve`: it needs `actions: write`. It cancels the protection the rule describes ("This prevents recursive workflow runs"), and the endpoint is documented for fork pull requests.
- A dedicated `CI_PUSH_TOKEN`: unnecessary, because the action already holds an App installation token with `contents: write`.

## Verification

- Red, previous template: `python3 -m pytest tests/test_ci_template.py -k fix_pushes` -> `AssertionError: assert None is False` (`{'ref': ..., 'fetch-depth': 0}`), `1 failed`.
- Green: the same command -> `1 passed`. `python3 -m pytest tests/test_ci_*.py` -> `510 passed, 33 subtests passed`. `bash tools/tests/render-ci/run-tests.sh` -> `7 passed, 0 failed`. `actionlint` on the three rendered `pipeline*.yml` -> exit 0.
- Limit: this pull request edits `.github/workflows/pipeline.yml`, so its own guard skips the bot steps (bootstrap). The first behavioural proof will be the next `Fix` push on another pull request after the merge. That push should show `actor: claude[bot]` and runs without `action_required`.
