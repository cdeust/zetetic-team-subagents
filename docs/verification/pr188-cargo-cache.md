# PR188 Cargo cache and validator verification

Base: `461f7c0a033b27587865777b706b5587d1bf6a7a`.

The three cache-contract tests failed before adding the steps (no cache found),
then passed. The final focused suite runs these five modules:

```sh
python -m pytest -q -p no:cacheprovider tests/test_ci_cargo_cache.py tests/test_ci_template.py tests/test_ci_pr_safety.py tests/test_ci_contract.py tests/test_ci_coverage.py
```

Result: 107 passed. The real renderer regression passed 7/7. Actionlint accepted
both template and generated workflow. Ruff check/format and `git diff --check`
passed. No full suite or hosted warm-cache benchmark was run for this change.

PR188 run 39902092998 had failed its template fixture with
`neither uvx nor actionlint found` (3 passed, 1 failed). A fresh disposable venv,
installed with `pip --require-hashes -r requirements-dev.lock`, now runs that
fixture with `PATH=/usr/bin:/bin` and an absolute `PYTHON_BIN`: 4 passed, 0 failed.
This verifies discovery from the chosen Python environment without uvx or a
global actionlint. The installed executable reports actionlint 1.7.12.

Package provenance was checked against the versioned PyPI sdist and official
rhysd/actionlint release checksums: macOS ARM64 and Linux AMD64 hashes match the
wrapper's configuration. Only macOS ARM64 executed locally; hosted Linux remains
the acceptance check. The package builds a wheel from a small sdist and downloads
its checksum-verified upstream executable during installation.

Local uv found an unrelated unusable x86 Python 3.12 installation, so lock
resolution used `--python /opt/homebrew/bin/python3.13 --python-version 3.12`
with `UV_CUSTOM_COMPILE_COMMAND` retaining the portable original generation
command. All existing locked packages and hashes remained unchanged.

Scratch `/private/tmp/disk-hygiene-9z2qte_o` contained only this verification's
venv, package caches and pytest fixtures; it was registered for disposal.
