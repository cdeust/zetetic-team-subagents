# PR 176: remove adversarial-verify and CR-4 (2026-10-21)

Branch chore/remove-adversarial-verify, commit cea86f5.

- `bash tests/run-all.sh`: `RESULT: 41 passed, 0 failed`, exit 0
- `.venv/bin/python -m pytest -q`: `1858 passed in 187.86s`
- `bash tools/doc-count-check.sh`: `37 claim instance(s) verified, 0 problem(s)`
- `bash tools/doc-command-check.sh`: `14 runnable command(s) checked across 20 document(s), 0 missing`
- `ZETETIC_PROFILE=strict bash tools/zetetic-checker.sh --staged`: `Errors: 0`, `Warnings: 0`, PASSED
- `scripts/gate.sh commit` and `push`: proofs written for tree 917d8dd6e45af050fc7f3bdbbc6d01e5e1db425b
- deletion-gate first blocked the commit for a missing `Retired-Because:` trailer; the trailer was added.
