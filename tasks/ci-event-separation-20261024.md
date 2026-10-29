# CI event separation, 2026-10-24

Owner requirement: fix the CodeQL trust boundary without dismissing alerts or
suppressing a query. Cortex PR792 is the acceptance target; other consumers are
outside this publication scope.

## Approved design

The direct Pipeline keeps its PR and main-push entry points, path and job names.
It cannot be called by another workflow. Its contract checks github.sha and has
no dependency on a resolver. PR review is present only in this direct workflow.

The completion listener calls pipeline-post-merge.yml. This engine contains the
resolver and contract, followed by the five existing test categories and tag.
It has no review or merge-gate job and no Claude action. Its contract requires a
successful resolver with run_tests=true and uses only the resolver's tested SHA.
There is no fallback to github.sha. The listener passes only RELEASE_TAG_SSH_KEY;
its permissions exclude issues and id-token writes.

The five job bodies come from templates/ci/pipeline.yml. The standard-library
renderer selects explicit job sets and specializes the event gates. Unknown or
duplicate jobs and changed source substitutions fail before destination writes.
The three rendered files are prepared together. A write failure restores files
already replaced, unless another process has edited them in the meantime.

The existing protected merge receipt and ancestry checks remain unchanged.
Both publication paths check out trusted main and tag the explicit tested commit.
The direct tag path accepts only push on refs/heads/main; the completion tag path
requires workflow_run. Both require the contract and all five categories to pass.

## Sources and acceptance

[GitHub reusable workflow documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#github-context)
states that the reusable inherits the caller's event context. The same reference
documents permission narrowing and named secret mappings. This is why the
completion engine retains workflow_run checks even though its sole entry is
workflow_call.

- [x] Four structural tests failed with the previous renderer and passed after
  separating the entry points.
- [x] Renderer mutation tests cover unknown/duplicate jobs, missing resolver
  dependencies, fallback SHA changes and a caller redirected to the direct path.
- [x] Delivery tests cover failure rollback for new and existing files, invalid
  destination paths and dry-run preservation.
- [x] Final shared-CI suite: 391 passed in 12.90 seconds. Renderer: 7 passed,
  0 failed. Actionlint accepted the canonical template and all generated files;
  Ruff and craftsmanship passed with zero errors or warnings.
- [x] Inventory independently reviewed the event graph, source parity and
  rollback tests without findings. Root review precedes publication.
- [x] Root requested an executable action mutation instead of a comment marker.
  The test now replaces the unit checkout with the pinned Claude action from
  the review job and verifies the parsed step. All 17 affected renderer and
  separation tests passed in 1.10 seconds afterward; Ruff and craftsmanship
  passed. The three rendered hashes did not change.
- [ ] Publish the reviewed source and provide the complete rendered set to Cortex.
- [ ] Execute native Cortex CodeQL and confirm no open alert for this boundary.

No dismissal, suppression, query change or action-name substitution is part of
this correction. A local structural test does not establish native CodeQL success.

Canonical template blob: 25a0493fb6c1d58ac6307fb2dc38f3ff82c09785.
Renderer blob: 14dbc7b28f3f67a9db304bed96921717414a4520.
Direct Pipeline blob: fae952c8822bdc9b9d450f8ab8e259a7a15505b4.
Completion engine blob: a047811da230b8bf5f2b8bae2856551a5430c164.
Completion caller blob: b23071bec38110c30cc7d7d0dc9d80d326f6b0ab.
