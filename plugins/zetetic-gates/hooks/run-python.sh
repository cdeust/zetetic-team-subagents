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

# No working Python 3 found. Fail open for every hook but the commit gate: warn on stderr but do
# not block the session (exit 0) — this preserves the pre-existing behavior where a broken
# python3 silently no-op'd the hook, but now the cause is visible.
echo "[zetetic] run-python.sh: no working Python 3 interpreter found (tried python3, py -3, python)." >&2
echo "[zetetic] On Windows, install Python from python.org and ensure 'py -3' works, or disable the" >&2
echo "[zetetic] Microsoft Store python/python3 execution aliases. Hook skipped: $script" >&2
#
# gate-proof.py is the exception and FAILS CLOSED: a gate that opens when it cannot run is not a gate.
# Without Python it cannot parse the command, so it refuses what can publish a commit by name: a payload
# in which `git` or `gh` stands as a COMMAND WORD. The payload is first DEQUOTED (dequote below): the JSON
# escapes \n, \r and \t become spaces, then every backslash, double quote and single quote is removed, so
# `"git" push`, `'git' commit`, `\git push`, `git"" push` and `/usr/bin/"git" push` all read `git push`, as the
# Python hook reads them. A command word is then `git` or `gh` preceded by the start of the command (the JSON
# key's colon), a space, a command separator or a path slash (the basename of `/usr/bin/git`), and followed by
# a space. "highlights", "ghost", "github", a working directory under "github" or ending in "/git" do not match.
# Any other tool call passes, so a host without Python can still install one. The payload is read once here
# because nothing else will, and only shell builtins are used (read, case, parameter expansion): the refusal
# does not depend on any tool on the PATH. A JSON \uXXXX escape is not decoded.
dequote() {
  local text=$1 bs='\' dq='"' sq="'"
  text=${text//"$bs"n/ }
  text=${text//"$bs"r/ }
  text=${text//"$bs"t/ }
  text=${text//"$bs"/}
  text=${text//"$dq"/}
  text=${text//"$sq"/}
  dequoted=$text
}
mentions_git_or_gh() {
  local before word
  for before in ':' ' ' ';' '&' '|' '(' '`' '{' '/'; do
    for word in git gh; do
      case "$1" in *"$before$word "*) return 0 ;; esac
    done
  done
  return 1
}
case "$script" in
  gate-proof.py | */gate-proof.py)
    IFS= read -r -d '' payload || true
    dequote "$payload"
    if [[ -z "$payload" ]] || mentions_git_or_gh "$dequoted"; then
      echo "GATE-PROOF: no working Python 3, so this call cannot be checked against the commit gate: refused (closed)." >&2
      echo "GATE-PROOF: install Python 3 (python3, py -3 or python) and retry; calls that do not run git or gh are not affected." >&2
      exit 2
    fi
    ;;
esac
#
# A caller whose output is the point of the hook (session-start.sh) cannot
# afford a stderr-only warning: stderr is not shown to the user. It sets
# ZETETIC_PYTHON_MISSING_NOTICE to its own wording and gets that line, plus
# what was tried, on stdout. Hooks that leave it unset keep their stdout
# untouched (stdout is a protocol channel for several of them).
if [[ -n "${ZETETIC_PYTHON_MISSING_NOTICE:-}" ]]; then
  echo "${ZETETIC_PYTHON_MISSING_NOTICE} (Python 3 not found; tried python3, py -3, python)"
fi
exit 0
