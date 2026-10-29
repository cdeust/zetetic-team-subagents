# Native Claude review on Dependabot runs, 2026-10-29

## Observed failure

cortex-viz PR 212 (authlib bump) and PR 209 (setup-python bump), both opened by
Dependabot. `Claude review` run 40819127887 (job 123267179895):

- `Secret source: Dependabot`
- `CLAUDE_CODE_OAUTH_TOKEN:` and `ANTHROPIC_API_KEY:` empty
- `Actor dependabot[bot] is in allowed_bots list, skipping human actor check`
- `##[error]Action failed with error: Environment variable validation failed:
  Either ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or workload identity
  federation ... is required`

`gh secret list --repo cdeust/cortex-viz --app dependabot` lists no secret;
`--app actions` lists `CLAUDE_CODE_OAUTH_TOKEN`.

## Cause

GitHub, "Troubleshooting Dependabot on GitHub Actions": a workflow triggered by
Dependabot receives only Dependabot secrets, and the page gives
`if: github.actor != 'dependabot[bot]'` for this case. The native asset admitted
`dependabot[bot]` in `allowed_bots` and had no actor condition, so the job always
ran without a credential. Decision 5 of
`docs/superpowers/specs/2026-10-22-single-ci-design.md` states that no Dependabot
secret is created, and the legacy review job already skips this actor.

## Change

- `claude-review.yml`: job condition adds `github.actor != 'dependabot[bot]'`;
  `allowed_bots` is `claude[bot],chatgpt-codex-connector[bot]`.
- `source.json`: adaptation `dependabot-secret-scope`, delivered sha256
  `399afc0409e0125cfbdb37764297a10e7fcabe9646e310c6a8937ff161456bbd`; the
  pinned Cortex source sha256 is unchanged (the receipt test undoes the change).
- `tests/test_ci_native_renderer.py`: new test
  `test_native_claude_review_skips_dependabot_runs_without_actions_secrets`
  (failed before the change, passes after).

`Claude review` is not a required check (cortex-viz protection: `merge` only),
so this removes a red check and does not change any merge decision.

## Verification (local, CPython 3.13.7)

- `pytest tests/ -k 'ci_ or native or render'`: 594 passed.
- `actionlint` on the asset: clean.
- Full suite: `tests/test_certifi_trust_roots.py::test_web_consumer_excludes_compromised_emsign_root`
  fails identically on a pristine `origin/main` export (local certifi bundle), so
  it is not caused by this change.
