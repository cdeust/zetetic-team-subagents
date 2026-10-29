# Portable native authorization test export

Scope: Spec163 P1 https://github.com/cdeust/ai-architect-mcp-spec/pull/163#discussion_r4408715493.
The source generator now commits a stdlib unittest asset into native consumers
and runs it in their contract job before ci.json configures the unit jobs.
It compiles the actual generated post-merge controller and its embedded proof;
it does not test a separate unused implementation.

Before implementation, the native export/CI contract failed for both schedule
profiles because the portable test asset was absent:

```
2 failed, 1 passed in 0.18s
```

Final focused source command:

```
python3 -m pytest -q tests/test_ci_native_authorization_export.py tests/test_ci_native_definition.py tests/test_ci_native_renderer.py tests/test_ci_native_gate.py tests/test_ci_renderer.py tests/test_ci_post_merge_template.py
82 passed in 3.10s
```

Actual renderer CLI output, exact consumer CI command:

```
python3 -m unittest discover -s scripts/tests -p test_ci_workflow_authorization.py -v
Ran 12 tests in 0.060s
OK
```

The source export contracts also run that consumer test with `python -S`, proving
it needs no third-party site packages, for native scheduled and no-schedule modes.
Acceptance asserts confirmed merged SHA/run_tests/PR outputs plus the exact-head
PUT precondition. Rejection asserts no PUT. CLI failure asserts nonzero return,
no emitted output and an observable workflow-proof error.

Mutation evidence (disposable generated workflow only): remove the actual
`_proof.authorize_workflow` call, then run the same exported tests:

```
MUTATION RED exit=1
Ran 12 tests in 0.046s
FAILED (failures=11)
```

This includes the fake-successful-job rejection and CLI failure tests. The
mutation was restored. The production resolve job is byte-identical to source
main before this change, and tools/ci_workflow_proof.py is unchanged.
Actionlint passed all generated workflows; source craftsmanship and zetetic
checks passed without threshold changes. No full unit rerun is claimed here:
root authorized focused verification because the production gate is unchanged.

Coordination: no event-reader or P2 test changes. The existing native renderer
common-job assertion accounts only for the new named contract test step; the
new export test requires that exact step once in both workflows. Preserve P2
source.json adaptation/asset hashes and distant native-renderer inverse helper
when combining source PRs.
