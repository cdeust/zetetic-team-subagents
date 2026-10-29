# Native trusted-definition security fix

Scope: shared canonical native CI source, not a consumer-only patch.
Finding: https://github.com/cdeust/cortex-voice/pull/5#discussion_r4408352195.
Baseline source: `986aa55c27ffcba3cfa42d2b4a1728bb5ae0bebc`.

The final fixture with API-shaped successful run/job metadata was exercised
against baseline inline resolver source. Raw RED output (exit 1):

```
RED baseline fake-definition: run_tests=true unauthorized_merge_requests=1
```

Before implementation, the initial pytest regression also failed as expected:

```
FAILED tests/test_ci_native_definition.py::test_fake_pipeline_with_realistic_success_metadata_cannot_merge
E Failed: DID NOT RAISE PostMergeError
1 failed in 6.47s
```

Final focused command, in an isolated venv installed with
`pip install --require-hashes -r requirements-dev.lock`:

```
python -m pytest -q tests/test_gate_repo_config.py tests/test_ci_native_definition.py tests/test_ci_native_renderer.py tests/test_ci_native_gate.py tests/test_ci_renderer.py tests/test_ci_post_merge_template.py
144 passed in 3.75s
```

Actionlint, diff whitespace check, source craftsmanship and zetetic checks pass.
The inventory checker verifies 32 claim instances with 0 problems after the required
descriptive tool count correction 70 -> 71. No coverage or severity gate changed.

Diagnostic full locked run completed with 3959 passes, 33 subtests and one inventory
failure that had already been fixed after its test executed. This diagnostic is
not claimed as a final-state green run. A fresh final-state full locked unit and
coverage sequence runs before publication; its receipt is appended below.

The first global-Python attempt was stopped after reproducing its outdated
certifi environment failure; no code workaround or shared environment mutation
was used. The locked environment uses certifi 2026.10.19 and coverage 7.15.2.

Hosted acceptance remains separate: the source PR includes a read-only
`Workflow definition API capability` workflow to measure actual scoped
GITHUB_TOKEN access through identical resolver transport, without checkout or
candidate execution. Root monitors this workflow and source PR CI after push.

Final frozen typed implementation, exact locked unit sequence (exit 0):

```
3962 passed, 33 subtests passed in 528.44s (0:08:48)
Combined 371 files, skipped 1101
Wrote XML report to registered disposable storage
```

Coverage line rate: 0.9467 (9048/9557). The configured 90% gate passed unchanged.
Final focused native/renderer/inventory run: `144 passed in 3.40s`; this includes the real canonical generated workflow bytes.
Final smoke target is verified public `cdeust/Cortex` main pipeline (voice main has no pipeline yet).

Final production SHA256 receipts:

```
3b14834822c891c3f86ea8ce807f14ebb455a4805087beddbb472867e0582ea3  tools/ci_workflow_proof.py
0bd4a6f6bc508d63569e79810d594923ebc7daad0b96b5664abdaf21823d1b66  templates/ci/native/pipeline.yml
7d3e737e5820c473666ffa130782b65be50f7327f97e5a27bb22c2973b427583  templates/ci/native/generated/pipeline.yml
deee3a311e992d580bca966fe48fe55f316eae740f600bec94388ea1475537f1  .github/workflows/workflow-definition-api.yml
```
