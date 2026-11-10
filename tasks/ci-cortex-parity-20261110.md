# Default CI profile follows Cortex

Date: 2026-11-10. Owner direction, 2026-11-09: the Cortex workflow is the source of
truth, the other repositories replicate it, and every repository gets the Claude
reviews Cortex has.

## Change

- `templates/ci/pipeline.yml`: `resolve` and `close-issues` are Cortex's jobs
  (cdeust/Cortex main at 7b81ab15), `merge` is Cortex's aggregate, the `review` job is
  removed. `LOW_RISK_FILES` names the manifests and locks of the ecosystems the
  consumers declare (uv, npm, pnpm, cargo), matched by file name, never under `.github/`.
- `tools/ci_post_merge.py`: the same resolver, byte for byte.
- `templates/ci/pipeline-after-merge.yml`: listens to `Pipeline` and `PR Review`;
  `issues: write` for `close-issues`.
- `scripts/lib/render_ci.py`: default job order `resolve, close-issues, contract, five
  categories, merge, tag`; the native profile keeps `review`; the completion caller may
  hold `issues: write`.
- `.github/workflows/claude-review.yml` and `scripts/ci_review_budget.py`: Cortex's.
- Tests: review-job tests removed, resolver fixtures give each head a review run and a
  verdict, six Cortex test files added under `tests/`.

## Reason

Under the 2026-10-29 rule the review posted and never blocked, and since 2026-11-03 the
`merge` job armed GitHub auto-merge: a pull request merged on green tests whatever the
review said, and in this repository `claude-review.yml` had no verdict line and no cap.
Cortex decides the merge on the verdict of the reviewed head (ADR-1121), caps reviews at
three (ADR-1119), lets low-risk dependency updates through without a review (ADR-1126)
and merges whichever of the review and the Pipeline ends last (ADR-1127).

## Result

- `python3 -m pytest tests/ -q`: 3994 passed (3975 before the change). The tests of the
  deleted review job are removed and six Cortex test files are added.
- `tools/ci_post_merge.py`: 99 % line coverage (222 statements, 2 missed) from
  `tests/test_ci_*.py`.
- `bash tools/doc-count-check.sh`: 32 claims, 0 problems. `bash tools/doc-command-check.sh`:
  17 commands, 0 missing.

## Not done here

- The native profile (`templates/ci/native/`) still ships the Codex review assets Cortex
  removed (ADR-1120). Aligning or retiring it is a separate change.
- `bash tools/craftsmanship-checker.sh --staged` reports 7 errors, all in code taken from
  Cortex byte for byte: more than four parameters (`_merge_open_pr`, `candidate_runs`,
  `budget`, two test helpers) and nesting deeper than three in two tests. They are fixed
  in Cortex first, then replicated, so the copies stay identical.
- The Pipeline no longer repairs a red head by itself; `claude.yml` (`@claude`) remains.
- Hosted behaviour is proven only by the first pull requests after the merge: the
  resolver that merges this change is the one on `main`.
