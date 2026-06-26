#!/usr/bin/env bash
# run-python.sh — resolve a working Python 3 interpreter, then exec a hook script.
#
# Why this exists: on Windows, `python3` in PATH is usually the Microsoft Store
# stub (prints an install message and exits 49 — it does not run Python). A naive
# `python3 X.py || py -3 X.py` fallback is wrong here: the zetetic Python hooks
# use a non-zero exit as a meaningful signal (secret-shield returns 2 to block a
# tool call; the Stop gates return non-zero to hold the turn), and they read the
# hook event from stdin exactly once. A `||` fallback would (a) re-run the script
# on every legitimate block and (b) feed it an already-drained stdin. Instead we
# pick the interpreter ONCE, up front, and exec the script a single time.
#
# Usage:  run-python.sh <script.py> [args...]
# stdin is forwarded to the script unchanged (exec preserves it).
set -euo pipefail

script="${1:?run-python.sh: missing script path}"
shift

# Probe candidates by actually running them — `command -v` is not enough on
# Windows, where the stub resolves but fails to execute. `-c ''` is a no-op that
# the stub cannot satisfy (it exits non-zero), so it falls through to `py -3`.
if command -v python3 >/dev/null 2>&1 && python3 -c '' >/dev/null 2>&1; then
  exec python3 "$script" "$@"
elif command -v py >/dev/null 2>&1 && py -3 -c '' >/dev/null 2>&1; then
  exec py -3 "$script" "$@"
elif command -v python >/dev/null 2>&1 \
     && python -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
  exec python "$script" "$@"
fi

# No working Python 3 found. Fail open: warn on stderr but do not block the
# session (exit 0) — this preserves the pre-existing behavior where a broken
# python3 silently no-op'd the hook, but now the cause is visible.
echo "[zetetic] run-python.sh: no working Python 3 interpreter found (tried python3, py -3, python)." >&2
echo "[zetetic] On Windows, install Python from python.org and ensure 'py -3' works, or disable the" >&2
echo "[zetetic] Microsoft Store python/python3 execution aliases. Hook skipped: $script" >&2
exit 0
