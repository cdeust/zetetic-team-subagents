# Disjoint CI suites, 2026-10-24

At source commit 902bb471, ci.json unit runs all pytest tests under coverage.
Regression invokes tests/run-all.sh, which runs the same pytest suite again at
lines103-104 before discovering 42 shell suites. Its discovery includes the six
scripts/test-memory-*.sh suites also run by e2e. The ci-template shell wrapper
additionally runs tests/test_ci_template.py, already included in unit.

Owner-approved scope: partition this discovery without changing the three
generated workflows, their renderer, coverage thresholds or native test commands.

- [x] Create registered worktree pr189-disjoint-suites at 902bb471.
- [x] Write executable fixture tests for category selection and failures.
- [x] Keep default run-all behavior; add explicit regression/e2e groups and lists.
- [x] Preserve central discovery, orphan refusal and empty-category failure.
- [x] Route ci.json regression/e2e through those groups; preserve dependency setup.
- [x] Retain standalone ci-template Python checks; its CI regression mode owns
  only shell assertions, while unit owns the Python assertions.
- [x] Verify real discovery union/disjointness and collect the Python module.
- [x] Run focused tests and checks, then submit for root review before publication.

The default command remains the contributor entry point for every suite. No
fixed inventory of suite filenames is introduced. CI groups are determined by
the existing memory-suite path convention; new matching suites are discovered.

## Validation before review

The new fixture tests failed before the implementation: 12 failed, 6 passed.
After the implementation all 18 passed in 1.69 seconds. They exercise actual
runner subprocesses, successful and failing suites, new discovered paths,
orphans, empty groups and standalone wrapper behavior. Synthetic pytest calls
used by existing regression fixtures remain untouched.

The real inventory contains 42 shell suites: 36 regression suites and 6 memory
E2E suites. The test compares the dynamic listings against the recursive on-disk
inventory, verifies their exact union and verifies their intersection is empty.
No fixed count is encoded in the implementation or its regression assertion.

The module tests/test_ci_template.py collects 14 tests. The actual standalone
ci-template wrapper passed its 4 checks, including that module; its explicit CI
regression mode passed the 3 shell checks. These runs also passed actionlint.
Ruff, bash -n, shellcheck and the craftsmanship checker passed (0 warnings).

Only ci.json regression/e2e values changed. Unit coverage, environment and install
commands are unchanged. All three generated workflows, their canonical model
and the renderer match the base blobs exactly:

- pipeline.yml: fae952c8822bdc9b9d450f8ab8e259a7a15505b4
- pipeline-post-merge.yml: a047811da230b8bf5f2b8bae2856551a5430c164
- pipeline-after-merge.yml: b23071bec38110c30cc7d7d0dc9d80d326f6b0ab
- templates/ci/pipeline.yml: 25a0493fb6c1d58ac6307fb2dc38f3ff82c09785
- scripts/lib/render_ci.py: 14dbc7b28f3f67a9db304bed96921717414a4520

The complete repository suites were not rerun locally. Hosted CI must execute
the final categories after publication. Root reviewed the exact five-file index and approved publication. The strict
staged checker also passed with zero errors and zero warnings. Publication and
remote verification will be recorded in the durable project evidence.
