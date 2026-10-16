#!/usr/bin/env bash
# Regression suite for tools/dev-python.sh (#171). Offline: python3 and the venv
# python are stubs on PATH that log their arguments; nothing reaches pip or the network.
set -uo pipefail   # NOT -e: a failing case must be counted, not abort the run.

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SUITE_DIR/../../.." && pwd)"
SCRIPT="$REPO_ROOT/tools/dev-python.sh"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }

TMP="$(cd -P "$(mktemp -d)" && pwd)"
trap 'rm -rf "$TMP"' EXIT
LOG="$TMP/calls.log"

# A python stub: logs its args; `-c` imports succeed only when STUB_HAS_DEPS=1;
# `-m venv DIR` creates DIR/bin/python as another stub (no real venv, no pip).
STUB_BIN="$TMP/stub-bin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/python3" <<'STUB'
#!/usr/bin/env bash
echo "$0 $*" >> "$STUB_LOG"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  mkdir -p "$3/bin" && cp "$0" "$3/bin/python"; exit 0
fi
if [ "${1:-}" = "-c" ]; then [ "${STUB_HAS_DEPS:-0}" = 1 ]; exit; fi
exit 0
STUB
chmod +x "$STUB_BIN/python3"
STUB_PATH="$STUB_BIN:$(dirname "$(command -v git)"):/usr/bin:/bin"

# make_checkout <dir>: a git repo holding dev-python.sh and a lock file.
make_checkout() {
  local dir="$1"
  mkdir -p "$dir/tools"
  git init -q "$dir"
  cp "$SCRIPT" "$dir/tools/dev-python.sh"
  echo "pytest==0 --hash=sha256:00" > "$dir/requirements-dev.lock"
  git -C "$dir" add -A
  git -C "$dir" -c user.email=t@example.com -c user.name=t commit -qm init
}

# run_dev <checkout> [VAR=value ...]: runs dev-python.sh offline; sets RC/OUT/ERR.
run_dev() {
  local dir="$1"; shift
  : > "$LOG"
  OUT="$(env -u PYTHON_BIN -u DEV_PYTHON_CREATE PATH="$STUB_PATH" STUB_LOG="$LOG" "$@" \
    bash "$dir/tools/dev-python.sh" 2>"$TMP/err")"
  RC=$?
  ERR="$(cat "$TMP/err")"
}

echo "== DEV_PYTHON_CREATE=0 with no venv"
make_checkout "$TMP/c0"
run_dev "$TMP/c0" DEV_PYTHON_CREATE=0
[[ "$RC" -eq 1 ]] && ok "exit 1" || bad "expected exit 1, got $RC"
[[ ! -e "$TMP/c0/.venv" ]] && ok "no .venv created" || bad ".venv was created"
if grep -qE -- '-m venv|pip' "$LOG"; then bad "ran venv/pip: $(cat "$LOG")"; else ok "no venv or pip call"; fi
want="python3 -m venv $TMP/c0/.venv && $TMP/c0/.venv/bin/python -m pip install --require-hashes -r $TMP/c0/requirements-dev.lock"
[[ "$ERR" == *"$want"* ]] && ok "prints the exact command" || bad "command not printed; stderr: $ERR"

echo "== DEV_PYTHON_CREATE unset defaults to 1 (creates the venv)"
make_checkout "$TMP/c1"
run_dev "$TMP/c1"
grep -q -- "-m venv $TMP/c1/.venv" "$LOG" && ok "creates the venv" || bad "no venv creation: $(cat "$LOG")"
grep -q -- "pip install .*--require-hashes -r $TMP/c1/requirements-dev.lock" "$LOG" \
  && ok "installs the hash-locked deps" || bad "no hash-locked install: $(cat "$LOG")"

echo "== DEV_PYTHON_CREATE with an unknown value"
make_checkout "$TMP/cx"
run_dev "$TMP/cx" DEV_PYTHON_CREATE=yes
[[ "$RC" -eq 1 && ! -e "$TMP/cx/.venv" ]] && ok "exit 1, nothing created" || bad "rc=$RC, venv: $(ls "$TMP/cx")"

echo "== PYTHON_BIN without pytest"
make_checkout "$TMP/cp"
run_dev "$TMP/cp" PYTHON_BIN="$STUB_BIN/python3"
[[ "$RC" -eq 1 ]] && ok "exit 1" || bad "expected exit 1, got $RC"
[[ ! -e "$TMP/cp/.venv" ]] && ok "no fallback venv" || bad ".venv was created"

echo "== a worktree finds the main checkout's .venv"
make_checkout "$TMP/main"
mkdir -p "$TMP/main/.venv/bin" && cp "$STUB_BIN/python3" "$TMP/main/.venv/bin/python"
git -C "$TMP/main" worktree add -q "$TMP/main/.claude/worktrees/wt" -b wt
run_dev "$TMP/main/.claude/worktrees/wt" STUB_HAS_DEPS=1
[[ "$RC" -eq 0 && "$OUT" == "$TMP/main/.venv/bin/python" ]] && ok "prints $OUT" \
  || bad "rc=$RC out='$OUT' err='$ERR'"
[[ ! -e "$TMP/main/.claude/worktrees/wt/.venv" ]] && ok "no venv in the worktree" || bad "worktree .venv created"

echo
echo "dev-python: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
echo "PASSED"
