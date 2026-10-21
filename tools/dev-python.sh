#!/usr/bin/env bash
# dev-python.sh — print a Python 3 that can import pytest and yaml, creating
# <main checkout>/.venv from requirements-dev.lock when none exists.
# source: ADR-9849
# Usage:  PY="$(tools/dev-python.sh)" || exit 1
# DEV_PYTHON_CREATE=1 (default) creates the venv; 0 prints the command and exits 1.
set -euo pipefail

has_dev_deps() { [ -x "$1" ] && "$1" -c 'import pytest, yaml' >/dev/null 2>&1; }

if [ -n "${PYTHON_BIN:-}" ]; then
  py="$(command -v "$PYTHON_BIN" || true)"
  if [ -n "$py" ] && has_dev_deps "$py"; then printf '%s\n' "$py"; exit 0; fi
  echo "dev-python: PYTHON_BIN=$PYTHON_BIN cannot import pytest and yaml" >&2
  exit 1
fi

top="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="$(git -C "$top" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
main="${common%/.git}"
if [ -z "$common" ] || [ "$main" = "$common" ]; then main="$top"; fi

for cand in "$top/.venv/bin/python" "$main/.venv/bin/python"; do
  if has_dev_deps "$cand"; then printf '%s\n' "$cand"; exit 0; fi
done

lock="$top/requirements-dev.lock"
base="$(command -v python3 || true)"
if [ -z "$base" ] || [ ! -f "$lock" ]; then
  echo "dev-python: need python3 on PATH and $lock to create a dev venv" >&2
  exit 1
fi
venv="$main/.venv"
create="${DEV_PYTHON_CREATE:-1}"
if [ "$create" != 1 ]; then
  [ "$create" = 0 ] || echo "dev-python: DEV_PYTHON_CREATE must be 0 or 1, got '$create'" >&2
  echo "dev-python: no dev venv and DEV_PYTHON_CREATE=0; create it with:" >&2
  echo "  python3 -m venv $venv && $venv/bin/python -m pip install --require-hashes -r $lock" >&2
  exit 1
fi
echo "dev-python: creating $venv from requirements-dev.lock" >&2
[ -x "$venv/bin/python" ] || "$base" -m venv "$venv" >&2
"$venv/bin/python" -m pip install -q --disable-pip-version-check \
  --require-hashes -r "$lock" >&2
if has_dev_deps "$venv/bin/python"; then
  printf '%s\n' "$venv/bin/python"; exit 0
fi
echo "dev-python: $venv was created but still cannot import pytest and yaml" >&2
exit 1
