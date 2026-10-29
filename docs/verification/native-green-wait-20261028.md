# Native green-wait discovery correction, 2026-10-28

Base: canonical main `8a26df3` (PR204 merged). Source: the actual
`ci_codex_review_resume.resumption_plan` and `_green_wait` contract, and
Codebase PR466 Claude review comment6460948094:
https://github.com/cdeust/ai-architect-mcp-codebase/issues/466#issuecomment-6460948094

The discovery filter rejected complete unresolved proof when `review` was
successful, including the successful Pipeline route with `merge pending review`.
The authoritative policy permits restarting review in that situation so its
existing repair behavior can consume the findings. A successful CheckRun named
`merge pending review` now permits the full policy to evaluate the candidate.
No authorizer or rerun operation changed.

## Reproduction and checks

Before production edits, the new real-discovery matrix failed only
`route=green_wait, unresolved=True`: discovery returned `[]` although the actual
policy returned `action=review`. The fixture has successful run/jobs and
SUCCESS/SKIPPED pending-job steps, with no failed step left from the merge fixture.

After the fix:

- `python3 -B -m unittest discover -s templates/ci/native/assets/scripts/tests -p 'test_ci_codex*.py' -q`: 96 passed.
- `python3 -B -m pytest -q tests/test_ci_native_schedule.py tests/test_ci_native_renderer.py tests/test_ci_native_resumption.py`: 19 passed.
- Ruff check and format: passed for both changed Python assets.
- Strict zetetic checker: zero errors and warnings.
- Actual Cortex craftsmanship scanner: zero violations for both Python assets.

The matrix checks green-wait, failed readiness and failed merge with both clean
and unresolved proof through real discovery and real policy. Discovery performs
no POST. A genuine failed merge with unresolved proof still returns no candidate
and performs zero REST calls. Existing current-head/authentication checks remain.

The broad repository pytest run used the host Python, whose installed certifi
failed `test_web_consumer_excludes_compromised_emsign_root`. The same consumer
passed with only the repository-locked certifi2026.10.19 installed privately via
`pip --require-hashes --no-deps --target`; shared Python was untouched.
The optional broad run was interrupted by its owned PID after 178.95s:
1425 passed, 33 subtests passed, one failed (the certifi consumer above). It was
not a complete passing run. The parent approved publication on the targeted
contracts; hosted CI uses the repository dependency lock for the full verdict.

## Frozen payload digests

- Helper SHA256: `53acd5512f5b49c3ce42fb36b496a9e5c09ca74afa9604878a2d4c2fbb07d58e`.
- Proof-first test SHA256: `1b046a129447084575e2260b7eac4175342bfdd4fa9ec339d81fc3fb48348403`.

The source receipt updates exactly these two authored-asset digests. Pipeline,
workflow and consumer repositories were not changed in this patch. Parent agent
independently reviewed and approved the production diff and six-case matrix
before publication.
