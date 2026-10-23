# PR #188 coverage verification

Base: `1afe7df` (`ci/pr-bots-finalize`). Local verification: macOS ARM64,
CPython 3.13; hosted Ubuntu/CPython 3.12 verification remains pending.

## Result

The complete final suite passes: **2938 passed in 576.15s**. Coverage 7.15.2
reports **8239/8726 statements covered (94.42%)**, with 487 missed. `coverage
report`, `coverage xml`, and the repository Cobertura gate all pass at the
unchanged **90%** threshold. No source paths or exclusion patterns changed.

The local original suite measured 7159/8566 (83.57%), matching the hosted
rounded 84% failure. It had 2907 passing tests and one teardown error:
`test_follow_tags_judges_the_annotated_tags_behind_the_pushed_commits`, where
`Gate._end_if_in_flight` received PermissionError from `os.killpg`. The two
worker records reached terminal states, and both PIDs were confirmed absent;
no signal was sent manually. This initial run used an existing environment
with coverage 7.16.0. The final run used an isolated hash-pinned environment
and did not reproduce the error, so it is not a one-variable runtime comparison.

## Changes and controlled evidence

Coverage's documented `patch = ["subprocess"]` starts measurement in Python
children and enables parallel data files, which require `coverage combine`
before XML generation. The installed coverage 7.15.2 `.pth` calls
`coverage.process_startup` when `COVERAGE_PROCESS_CONFIG` is set. The unit
command now prepends the venv's bin directory to PATH, so bare `python3`
children use that same instrumented interpreter. Other CI categories are
byte-for-byte unchanged. Source: [coverage 7.15.2 configuration reference](https://coverage.readthedocs.io/en/7.15.2/config.html#run-patch).

A controlled probe ran the same 54 existing portable-package and staged-check
tests with coverage 7.15.2. Both runs passed. Without subprocess measurement,
portable-reference generation was 0/85 and staged checks were absent. With
it, they were 70/85 and 81/88 respectively. The final full run merged 1276
shards (308 unique, 968 duplicates), increasing the denominator by 160.

31 new behavioral cases cover previously untested corpus mining and label
adjudication, plus portable-reference drift and incomplete-source rejection.
All use disposable fixture data. No real user transcript or model evaluation
corpus is read. These fixtures verify program behavior; they are not evidence
of router accuracy or model quality.

| Component | Original covered/total | Final covered/total |
| --- | ---: | ---: |
| `tools/mine_shape_cases.py` | 0/130 | 130/130 |
| `tools/score_shape_labels.py` | 0/134 | 134/134 |
| `tools/sync-portable-references.py` | 0/85 | 85/85 |
| `hooks/pre-agent-genius-gate.py` | 0/118 | 113/118 |
| `hooks/gate-proof.py` | 0/103 | 96/103 |
| `hooks/zetetic-gates.py` | 0/72 | 68/72 |
| `hooks/lib/staged_checks.py` | not measured | 82/88 |

## Reproduction

Install `requirements-dev.lock` with `pip --require-hashes` into a fresh venv,
prepend its `bin` directory to PATH, then from the worktree:

```bash
python -m coverage run -m pytest -q
python -m coverage combine
python -m coverage report --precision=2
python -m coverage xml
python tools/ci_coverage.py coverage.xml --min 90
```

The local run additionally used an owned disposable `COVERAGE_FILE` and
pytest `--basetemp`, disabled bytecode and pytest cache writes, and ran all
tests without selection/exclusions. Final Ruff check/format and git diff
whitespace validation pass. No product code, workflow template, generated
pipeline, threshold or release logic was changed.
