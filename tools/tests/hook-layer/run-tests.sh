#!/usr/bin/env bash
# Regression suite C2 — hook-layer fixes (fix/hook-layer-enforcement).
#
# Asserts the EXPECTED POST-FIX behaviour of the four stdin hooks plus the
# craftsmanship checker. Maps 1:1 to the audit findings:
#
#   R1 macOS-no-timeout: timeout/gtimeout absence must NOT zero out the stdin
#       payload (that silently disabled the pre-commit guard). With both absent,
#       a fed payload must still be parsed (the guard still fires).
#   R3 secret-shield non-dict JSON: '[]' / '42' / 'null' parse fine but have no
#       .get(); they must fail OPEN (exit 0), not crash (exit 1).
#   R4 stop-acceptance-gate non-dict payload -> allow (exit 0, no block).
#   R5 stop-context-guard   non-dict payload -> allow (exit 0, no block).
#   R6 PostToolUse repo context: post-commit advisory hooks must resolve a repo
#       from tool_input.workdir or `git -C` even when the hook cwd is not a
#       repository, and must always exit 0 when no repo can be resolved.
#   A7 git-verb guard across ALL FIVE gate hooks (pre-commit-zetetic,
#       pre-push-review, pre-push-provenance, post-commit-difficulty,
#       post-commit-lab-notebook): wrapper/separator forms behind sudo/env/a
#       leading assignment/grouping (`git push;`, `git commit&`, `sudo git
#       commit`, `env X=1 git commit`, `GIT_EDITOR=vim git commit`,
#       `(git commit)`) MUST fire the verb-appropriate gate; lines that only
#       mention the verb (echo/--grep/commit-tree) MUST stay quiet.
#
#   secret-shield corpus: a false-positive corpus must stay ALLOWED (exit 0);
#       a true-positive corpus must BLOCK (exit 2) — the intentional-block
#       contract is preserved.
#   SS-FN-1 env reads: `printenv`/`env` of a credential var (AWS_SECRET_ACCESS_KEY,
#       GITHUB_TOKEN) BLOCKS (exit 2); of a public var (API_HOST, PUBLIC_PATH)
#       ALLOWS (exit 0).
#   F1 `.env` templates: `.env.example`/`.env.sample`/`.env.template` (Read or
#       Bash) ALLOW (exit 0); a bare `.env` still BLOCKS (exit 2).
#   F2 keyring/keychain source files: `keyring_backend.py` / `how-keychain-works.md`
#       ALLOW (exit 0); `login.keychain-db` still BLOCKS (exit 2).
#   craftsmanship detector corpus: each size/grab-bag detector fires with the
#       right label & severity, a clean file passes, and SEV_*=off disables a
#       block (config is fully tunable including off). Detector false positives
#       (round-2): a JSON object literal + long `while(){` block (.js) must NOT
#       block as FUNCTION_TOO_LONG; a 5-arg CALL must NOT block as PARAM_COUNT;
#       a real 5-param def in a 600+-line file MUST still block.
#
# Self-contained: builds throwaway fixtures in a tmpdir, shims PATH where needed,
# never touches the working tree, runs no git mutation.
#
# Exit non-zero if any assertion fails. Run AFTER all hook-layer fixes land.
set -uo pipefail   # NOT -e: we deliberately run hooks expecting non-zero codes.
cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
HOOKS="$REPO/hooks"
TOOLS="$REPO/tools"
SECRET_SHIELD="$HOOKS/pre-tool-secret-shield.py"
ACCEPT_GATE="$HOOKS/stop-acceptance-gate.py"
CTX_GUARD="$HOOKS/stop-context-guard.py"
PRE_COMMIT="$HOOKS/pre-commit-zetetic.sh"
CHECKER="$TOOLS/craftsmanship-checker.sh"

PASS=0
FAIL=0
pass() { printf "  ok   %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL %s\n" "$1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# JSON-encode an arbitrary string safely (handles quotes/backslashes/$).
json_str() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# Build a Bash-tool event JSON for the given command string.
bash_event() { printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(json_str "$1")"; }
bash_event_context() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys

command, cwd, workdir = sys.argv[1:4]
event = {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": command}}
if workdir:
    event["tool_input"]["workdir"] = workdir
print(json.dumps(event))
PY
}
read_event() { printf '{"tool_name":"Read","tool_input":{"file_path":%s}}' "$(json_str "$1")"; }

echo "C2 hook-layer regression suite"

# =====================================================================
# R3 — secret-shield: non-dict valid JSON must fail open (exit 0).
# =====================================================================
echo " R3 secret-shield non-dict payloads -> exit 0 (fail open):"
for payload in '[]' '42' 'null'; do
  printf '%s' "$payload" | python3 "$SECRET_SHIELD" >/dev/null 2>&1
  rc=$?
  [[ "$rc" -eq 0 ]] && pass "secret-shield '$payload' -> exit 0" \
                    || fail "secret-shield '$payload' -> expected 0, got $rc"
done

# =====================================================================
# secret-shield FALSE-POSITIVE corpus -> NOT blocked (exit 0).
# These look secret-adjacent but are benign: a host var, a template copy, a
# vault-named public URL path, an author var.
# =====================================================================
echo " secret-shield false-positive corpus -> exit 0 (allowed):"
SS_FALSE=(
  'echo $API_HOST'
  'cp prod.env.template /app/.env'
  'curl https://example.com/vault/data.json'
  'echo $AUTHOR_NAME'
)
for cmd in "${SS_FALSE[@]}"; do
  bash_event "$cmd" | python3 "$SECRET_SHIELD" >/dev/null 2>&1
  rc=$?
  [[ "$rc" -eq 0 ]] && pass "allow: $cmd" || fail "blocked (rc=$rc) but should allow: $cmd"
done

# =====================================================================
# secret-shield TRUE-POSITIVE corpus -> blocked (exit 2). Intentional-block
# contract preserved.
# =====================================================================
echo " secret-shield true-positive corpus -> exit 2 (blocked):"
SS_TRUE=(
  'echo $AWS_SECRET_ACCESS_KEY'
  'cat ~/.aws/credentials'
)
for cmd in "${SS_TRUE[@]}"; do
  bash_event "$cmd" | python3 "$SECRET_SHIELD" >/dev/null 2>&1
  rc=$?
  [[ "$rc" -eq 2 ]] && pass "block (exit 2): $cmd" || fail "expected block exit 2, got $rc: $cmd"
done

# Run a hook event through secret-shield and echo its exit code. Capture-then-
# nothing: we only need the rc, so /dev/null both streams and read $?.
ss_rc() { printf '%s' "$1" | python3 "$SECRET_SHIELD" >/dev/null 2>&1; echo $?; }

# =====================================================================
# SS-FN-1 — env-var DUMP/READ commands that name a sensitive var must block
# (exit 2), while reads of a public/benign var must allow (exit 0). The fix
# distinguishes a credential variable (AWS_SECRET_ACCESS_KEY, GITHUB_TOKEN)
# from a public one (API_HOST, PUBLIC_PATH) by underscore-component + suffix
# matching, not a blind substring — so neither over- nor under-blocks.
# =====================================================================
echo " SS-FN-1 printenv/env secret reads -> block (2); public env -> allow (0):"
SS_ENV_BLOCK=(
  'printenv AWS_SECRET_ACCESS_KEY'
  'env GITHUB_TOKEN somecmd'
)
for cmd in "${SS_ENV_BLOCK[@]}"; do
  rc="$(ss_rc "$(bash_event "$cmd")")"
  [[ "$rc" -eq 2 ]] && pass "block (exit 2): $cmd" || fail "expected block exit 2, got $rc: $cmd"
done
SS_ENV_ALLOW=(
  'printenv API_HOST'
  'printenv PUBLIC_PATH'
)
for cmd in "${SS_ENV_ALLOW[@]}"; do
  rc="$(ss_rc "$(bash_event "$cmd")")"
  [[ "$rc" -eq 0 ]] && pass "allow (exit 0): $cmd" || fail "blocked (rc=$rc) but should allow: $cmd"
done

# =====================================================================
# F1 — `.env` template/sample files are NOT secret stores; reading them must
# allow (exit 0) whether as a Read of the path or a Bash command naming it.
# A bare `.env` (no .example/.sample/.template suffix) still blocks (exit 2):
# the intentional-block contract on the real credential file is preserved.
# =====================================================================
echo " F1 .env templates allowed; bare .env still blocks:"
F1_ALLOW_READ=( '.env.example' '.env.sample' '.env.template' )
for path in "${F1_ALLOW_READ[@]}"; do
  rc="$(ss_rc "$(read_event "$path")")"
  [[ "$rc" -eq 0 ]] && pass "allow Read: $path" || fail "blocked (rc=$rc) but should allow Read: $path"
done
F1_ALLOW_BASH=( 'cat .env.example' 'echo see .env.example' )
for cmd in "${F1_ALLOW_BASH[@]}"; do
  rc="$(ss_rc "$(bash_event "$cmd")")"
  [[ "$rc" -eq 0 ]] && pass "allow Bash: $cmd" || fail "blocked (rc=$rc) but should allow Bash: $cmd"
done
rc="$(ss_rc "$(read_event '.env')")"
[[ "$rc" -eq 2 ]] && pass "block (exit 2) Read: .env (bare)" \
                  || fail "expected block exit 2 on bare .env, got $rc"

# =====================================================================
# F2 — `keychain`/`keyring` as a substring of a SOURCE FILE NAME (a backend
# module, a doc about how keychains work) is not a credential store; reading
# such a file must allow (exit 0). The real macOS keychain DB
# (login.keychain-db) still blocks (exit 2) — intentional-block preserved.
# =====================================================================
echo " F2 keyring/keychain source files allowed; login.keychain-db blocks:"
F2_ALLOW=( 'cat src/keyring_backend.py' 'cat docs/how-keychain-works.md' )
for cmd in "${F2_ALLOW[@]}"; do
  rc="$(ss_rc "$(bash_event "$cmd")")"
  [[ "$rc" -eq 0 ]] && pass "allow: $cmd" || fail "blocked (rc=$rc) but should allow: $cmd"
done
rc="$(ss_rc "$(bash_event 'cat login.keychain-db')")"
[[ "$rc" -eq 2 ]] && pass "block (exit 2): cat login.keychain-db" \
                  || fail "expected block exit 2 on login.keychain-db, got $rc"

# =====================================================================
# R4 — stop-acceptance-gate: non-dict payload -> allow (exit 0, no block).
# =====================================================================
echo " R4 stop-acceptance-gate non-dict payloads -> allow (exit 0, no block):"
for payload in '[]' '42' 'null'; do
  out="$(printf '%s' "$payload" | python3 "$ACCEPT_GATE" 2>/dev/null)"
  rc=$?
  if [[ "$rc" -eq 0 ]] && ! grep -q '"block"' <<<"$out"; then
    pass "acceptance-gate '$payload' -> allow"
  else
    fail "acceptance-gate '$payload' -> expected allow (exit 0, no block); rc=$rc out='$out'"
  fi
done

# =====================================================================
# R5 — stop-context-guard: non-dict payload -> allow (exit 0, no block).
# =====================================================================
echo " R5 stop-context-guard non-dict payloads -> allow (exit 0, no block):"
for payload in '[]' '42' 'null'; do
  out="$(printf '%s' "$payload" | python3 "$CTX_GUARD" 2>/dev/null)"
  rc=$?
  if [[ "$rc" -eq 0 ]] && ! grep -q '"block"' <<<"$out"; then
    pass "context-guard '$payload' -> allow"
  else
    fail "context-guard '$payload' -> expected allow (exit 0, no block); rc=$rc out='$out'"
  fi
done

# =====================================================================
# A7 — git-verb guard across ALL FIVE gate hooks (not just pre-commit).
#
# Every gate hook early-EXITS 0 (silently, no output) when its git-verb guard
# does NOT fire, and falls through to do real work when it DOES. We isolate the
# GUARD decision (independent of any finding) by giving each hook a fixture in
# which the guard-fired path prints a known SENTINEL and the guard-quiet path
# stays silent. So: sentinel present <=> guard fired; absent <=> short-circuit.
#
# Per-hook fixtures + sentinels (all proven by execution against the fixed
# hooks before this suite was written):
#   pre-commit-zetetic    -> CLAUDE_PLUGIN_ROOT=empty git root; checker "not
#                            found" sentinel.
#   pre-push-review       -> same empty-root checker "not found" sentinel.
#   pre-push-provenance   -> repo with a remote + an unsidecar'd research file;
#                            PROVENANCE_STRICT=block => "MISSING PROVENANCE".
#   post-commit-difficulty-> tasks/ + a difficulty book naming a committed
#                            file (>=2 commits so HEAD has a parent) => the
#                            "Consider updating" NOTE.
#   post-commit-lab-notebook-> research/NOTEBOOK.md + research/.session.json
#                            => "=== Research Session Active ===".
#
# The probe is generalized to (hook-path, repo-dir, extra-env, sentinel, cmd).
# Capture-then-grep (out="$(...)"; grep <<<"$out") — never `cmd | grep -q`,
# whose pipefail+SIGPIPE interaction can yield a false negative.
# =====================================================================
echo " A7 git-verb guard across all five gate hooks:"
PRE_PUSH_REVIEW="$HOOKS/pre-push-review.sh"
PRE_PUSH_PROV="$HOOKS/pre-push-provenance.sh"
POST_DIFF="$HOOKS/post-commit-difficulty.sh"
POST_LAB="$HOOKS/post-commit-lab-notebook.sh"

EMPTY_ROOT="$TMP/empty-plugin-root"
mkdir -p "$EMPTY_ROOT"
git -C "$EMPTY_ROOT" init -q     # a git root with NO tools/ dir
# Shared "checker not found" sentinel for the two zetetic-checker hooks; the R1
# macOS-no-timeout case below reuses it on pre-commit-zetetic.
SENTINEL='zetetic-checker.sh not found'

# pre-push-provenance fixture: base commit pushed to a bare remote, then an
# unsidecar'd research file committed on top. origin/<branch>...HEAD then names
# that file => MISSING PROVENANCE under PROVENANCE_STRICT=block.
PROV_ROOT="$TMP/a7-prov"
mkdir -p "$PROV_ROOT"
git -C "$PROV_ROOT" init -q -b main
git -C "$PROV_ROOT" config user.email t@t; git -C "$PROV_ROOT" config user.name t
printf 'base\n' > "$PROV_ROOT/base.txt"
git -C "$PROV_ROOT" add -A; git -C "$PROV_ROOT" commit -qm base
PROV_BARE="$TMP/a7-prov-bare.git"
git init -q --bare "$PROV_BARE"
git -C "$PROV_ROOT" remote add origin "$PROV_BARE"
git -C "$PROV_ROOT" push -q origin main
# Research-worthy (.py, names an 'algorithm' + a 'threshold'); no sidecar.
printf 'def f():\n    # implementation of algorithm\n    threshold = 1\n' > "$PROV_ROOT/algo.py"
git -C "$PROV_ROOT" add -A; git -C "$PROV_ROOT" commit -qm add-algo

# post-commit-difficulty fixture: a difficulty book naming a committed file,
# committed first; the tracked file committed second so HEAD has a parent and
# `git diff-tree -r HEAD` lists it.
DIFF_ROOT="$TMP/a7-diff"
mkdir -p "$DIFF_ROOT/tasks"
git -C "$DIFF_ROOT" init -q
git -C "$DIFF_ROOT" config user.email t@t; git -C "$DIFF_ROOT" config user.name t
printf '# difficulty book\n- hardest case in widget\n' > "$DIFF_ROOT/tasks/difficulty-book-core.md"
git -C "$DIFF_ROOT" add -A; git -C "$DIFF_ROOT" commit -qm seed-book
printf 'content\n' > "$DIFF_ROOT/widget.py"
git -C "$DIFF_ROOT" add -A; git -C "$DIFF_ROOT" commit -qm add-widget

# post-commit-lab-notebook fixture: an active research session.
LAB_ROOT="$TMP/a7-lab"
mkdir -p "$LAB_ROOT/research"
git -C "$LAB_ROOT" init -q
git -C "$LAB_ROOT" config user.email t@t; git -C "$LAB_ROOT" config user.name t
printf 'seed\n' > "$LAB_ROOT/f.txt"
git -C "$LAB_ROOT" add -A; git -C "$LAB_ROOT" commit -qm c
printf '# notebook\n' > "$LAB_ROOT/research/NOTEBOOK.md"
printf '{"question":"does it work"}\n' > "$LAB_ROOT/research/.session.json"

# Generalized probe: 0 if the hook's guard fired (its sentinel appeared), else 1.
# Args: HOOK_PATH  REPO_DIR  EXTRA_ENV  SENTINEL  COMMAND.
guard_fired() {
  local hook="$1" repo="$2" extra_env="$3" sentinel="$4" cmd="$5" out
  out="$( ( cd "$repo" && env $extra_env CLAUDE_PLUGIN_ROOT="$EMPTY_ROOT" \
           bash "$hook" <<<"$(bash_event "$cmd")" ) 2>&1 )"
  grep -q "$sentinel" <<<"$out"
}

# Drive one hook through its FIRE set (verb-appropriate) and its QUIET set.
# Args: LABEL HOOK_PATH REPO_DIR EXTRA_ENV SENTINEL VERB(commit|push).
a7_check_hook() {
  local label="$1" hook="$2" repo="$3" extra_env="$4" sentinel="$5" verb="$6"
  local fire=() quiet=()
  # Wrapper/separator forms that MUST fire (root cause: a command-position git
  # verb behind sudo/env/leading-assignment/grouping is still a real git op).
  fire=(
    "git ${verb};"
    "git ${verb}&"
    "sudo git ${verb}"
    "env X=1 git ${verb}"
    "(git ${verb})"
  )
  # commit-only forms (GIT_EDITOR is meaningful for commit, not push).
  [[ "$verb" == "commit" ]] && fire+=( "GIT_EDITOR=vim git ${verb}" )
  # Lines that merely MENTION the verb and MUST stay quiet (no command-position
  # git verb): a quoted echo, a --grep search value, and (commit) commit-tree.
  quiet=(
    "echo 'git ${verb}'"
    "git log --grep='git ${verb}'"
  )
  [[ "$verb" == "commit" ]] && quiet+=( 'git commit-tree' )
  local cmd
  for cmd in "${fire[@]}"; do
    if guard_fired "$hook" "$repo" "$extra_env" "$sentinel" "$cmd"; then
      pass "[$label] guard fired (true positive): $cmd"
    else
      fail "[$label] guard did NOT fire but should: $cmd"
    fi
  done
  for cmd in "${quiet[@]}"; do
    if guard_fired "$hook" "$repo" "$extra_env" "$sentinel" "$cmd"; then
      fail "[$label] guard fired but should NOT (false positive): $cmd"
    else
      pass "[$label] guard quiet (false positive): $cmd"
    fi
  done
}

a7_check_hook "pre-commit-zetetic"     "$PRE_COMMIT"        "$EMPTY_ROOT" "" \
  "$SENTINEL" "commit"
a7_check_hook "pre-push-review"        "$PRE_PUSH_REVIEW"   "$EMPTY_ROOT" "" \
  "$SENTINEL" "push"
a7_check_hook "pre-push-provenance"    "$PRE_PUSH_PROV"     "$PROV_ROOT" "PROVENANCE_STRICT=block" \
  'MISSING PROVENANCE' "push"
a7_check_hook "post-commit-difficulty" "$POST_DIFF"         "$DIFF_ROOT" "" \
  'Consider updating' "commit"
a7_check_hook "post-commit-lab-notebook" "$POST_LAB"        "$LAB_ROOT"  "" \
  'Research Session Active' "commit"

# =====================================================================
# R6 — PostToolUse hooks run in the host cwd, which can differ from the tool's
# workdir.  The old difficulty hook fell back to a non-git directory containing
# tasks/, then leaked git diff-tree's exit 128 into the session.
# =====================================================================
echo " R6 PostToolUse repository context and fail-open contract:"
NON_GIT_ROOT="$TMP/r6-non-git"
mkdir -p "$NON_GIT_ROOT/tasks"

out="$( ( cd "$NON_GIT_ROOT" && bash "$POST_DIFF" \
  <<<"$(bash_event_context "git -C '$DIFF_ROOT' commit -m x" "$NON_GIT_ROOT" "")" ) 2>&1 )"
rc=$?
if [[ "$rc" -eq 0 ]] && grep -q 'Consider updating' <<<"$out"; then
  pass "post-commit-difficulty resolves git -C repo from non-git cwd"
else
  fail "post-commit-difficulty git -C context: expected advisory exit 0, got rc=$rc out='$out'"
fi

out="$( ( cd "$NON_GIT_ROOT" && bash "$POST_DIFF" \
  <<<"$(bash_event_context 'git commit -m x' "$NON_GIT_ROOT" "$DIFF_ROOT")" ) 2>&1 )"
rc=$?
if [[ "$rc" -eq 0 ]] && grep -q 'Consider updating' <<<"$out"; then
  pass "post-commit-difficulty resolves tool_input.workdir"
else
  fail "post-commit-difficulty workdir context: expected advisory exit 0, got rc=$rc out='$out'"
fi

out="$( ( cd "$NON_GIT_ROOT" && bash "$POST_LAB" \
  <<<"$(bash_event_context "git -C '$LAB_ROOT' commit -m x" "$NON_GIT_ROOT" "")" ) 2>&1 )"
rc=$?
if [[ "$rc" -eq 0 ]] && grep -q 'Research Session Active' <<<"$out"; then
  pass "post-commit-lab-notebook resolves git -C repo from non-git cwd"
else
  fail "post-commit-lab-notebook git -C context: expected advisory exit 0, got rc=$rc out='$out'"
fi

for hook in "$POST_DIFF" "$POST_LAB"; do
  printf '%s' "$(bash_event_context 'git commit -m x' "$NON_GIT_ROOT" "")" \
    | ( cd "$NON_GIT_ROOT" && bash "$hook" ) >/dev/null 2>&1
  rc=$?
  [[ "$rc" -eq 0 ]] && pass "$(basename "$hook") fails open without a repository" \
                    || fail "$(basename "$hook") leaked exit $rc without a repository"
done

# =====================================================================
# R1 — macOS-no-timeout: with timeout AND gtimeout absent from PATH, a fed
# stdin payload must still be parsed (NOT zeroed out). We assert it by feeding a
# real `git commit` event and checking the guard still fires (sentinel present).
# If the payload were zeroed, BASH_CMD would be empty, the guard would not fire,
# and the sentinel would be absent.
#
# We build a curated PATH containing the bins the hook needs but NEITHER timeout
# NOR gtimeout, regardless of what the host provides.
# =====================================================================
echo " R1 macOS-no-timeout: payload still parsed when timeout/gtimeout absent:"
STUBBIN="$TMP/stubbin"
mkdir -p "$STUBBIN"
for b in bash sh cat jq grep sed awk dirname git python3 head tr env; do
  p="$(command -v "$b" 2>/dev/null || true)"
  [[ -n "$p" ]] && ln -sf "$p" "$STUBBIN/$b"
done
# Sanity: the curated PATH must lack the bounded-read binaries.
if PATH="$STUBBIN" command -v timeout >/dev/null 2>&1 || PATH="$STUBBIN" command -v gtimeout >/dev/null 2>&1; then
  fail "test setup: timeout/gtimeout leaked into the curated PATH"
else
  out="$( ( cd "$EMPTY_ROOT" && PATH="$STUBBIN" CLAUDE_PLUGIN_ROOT="$EMPTY_ROOT" \
           bash "$PRE_COMMIT" <<<"$(bash_event 'git commit -m x')" ) 2>&1 )"
  rc=$?
  if grep -q "$SENTINEL" <<<"$out"; then
    pass "payload parsed without timeout/gtimeout (guard fired)"
  else
    fail "payload appears zeroed without timeout/gtimeout (guard did NOT fire); rc=$rc out='$out'"
  fi
fi

# =====================================================================
# craftsmanship-checker detector corpus.
#
# Fixtures are chosen to (a) cross the §10 1.2x flex band so they BLOCK (not
# merely advise), and (b) avoid the slow per-line brace-nesting detector:
#   - FILE_TOO_LONG uses a .c file (unrecognized lang => detectors 2-5 fail-open,
#     only the cheap wc-based file-size detector runs).
#   - FUNCTION_TOO_LONG / PARAM_COUNT use small .py files (recognized lang).
# Severity: size detectors BLOCK (exit 1); GRABBAG_NAME is ADVISE (exit 0).
# =====================================================================
echo " craftsmanship-checker detector corpus:"
if [[ ! -x "$CHECKER" ]]; then
  fail "craftsmanship-checker.sh not executable at $CHECKER"
else
  FX="$TMP/craft"
  mkdir -p "$FX"

  # >500 lines, beyond 1.2x band (>600) -> FILE_TOO_LONG block. .c = fast path.
  : > "$FX/big.c"
  for i in $(seq 1 601); do printf 'int v%d = %d;\n' "$i" "$i"; done >> "$FX/big.c"

  # function body 65 lines (>50*1.2=60) -> FUNCTION_TOO_LONG block.
  { printf 'def f():\n'; for i in $(seq 1 65); do printf '    a%d = %d\n' "$i" "$i"; done; printf 'x = 0\n'; } > "$FX/longfn.py"

  # 5 params (>4) -> PARAM_COUNT block.
  printf 'def g(a, b, c, d, e):\n    return a\n' > "$FX/params.py"

  # utils.py basename -> GRABBAG_NAME (advise, exit 0).
  printf 'def thing():\n    return 1\n' > "$FX/utils.py"

  # clean -> no findings, exit 0.
  printf 'def ok():\n    return 1\n' > "$FX/clean.py"

  # ── Detector FALSE-POSITIVE fixtures (round-2 fixes) ──────────────────
  # (a) A brace-language file (.js) with a big JSON object LITERAL and a long
  #     `while (...) { ... }` block. Neither is a function/method, so neither
  #     may be mis-scored as a >flex-band FUNCTION_TOO_LONG block. Post-fix
  #     expectation: NO blocking FUNCTION_TOO_LONG false positive.
  {
    printf 'const config = {\n'
    for i in $(seq 1 70); do printf '  key%d: %d,\n' "$i" "$i"; done
    printf '};\n'
    printf 'let n = 0;\n'
    printf 'while (n < 100) {\n'
    for i in $(seq 1 70); do printf '  n += %d;\n' "$i"; done
    printf '}\n'
  } > "$FX/objlit.js"

  # (b) A 5-arg CALL (not a declaration). PARAM_COUNT counts DECLARATION
  #     params; a call site must not be mistaken for a 5-param def. Post-fix
  #     expectation: NO PARAM_COUNT block.
  printf 'result = f(a, b, c, d, e)\n' > "$FX/call5.py"

  # (c) TRUE POSITIVE we must keep blocking: a real 5-param def in a 600+-line
  #     file. PARAM_COUNT AND FILE_TOO_LONG both fire; the file blocks (exit 1).
  { printf 'def realdef(a, b, c, d, e):\n'; for i in $(seq 1 600); do printf '    x%d = %d\n' "$i" "$i"; done; } > "$FX/realdef.py"

  ck() { bash "$CHECKER" --files "$1" 2>&1; }      # combined out, ignore rc here
  ck_rc() { bash "$CHECKER" --files "$1" >/dev/null 2>&1; echo $?; }

  # FILE_TOO_LONG: label present AND blocks (exit 1).
  if grep -q 'FILE_TOO_LONG' <<<"$(ck "$FX/big.c")"; then pass "FILE_TOO_LONG label fires (big.c)"
  else fail "FILE_TOO_LONG label missing (big.c)"; fi
  rc="$(ck_rc "$FX/big.c")"
  [[ "$rc" -eq 1 ]] && pass "big.c blocks (exit 1)" || fail "big.c expected exit 1, got $rc"

  # SEV_FILE_TOO_LONG=off -> the >500 file no longer blocks (exit 0).
  SEV_FILE_TOO_LONG=off bash "$CHECKER" --files "$FX/big.c" >/dev/null 2>&1
  rc=$?
  [[ "$rc" -eq 0 ]] && pass "SEV_FILE_TOO_LONG=off disables the block (exit 0)" \
                    || fail "SEV_FILE_TOO_LONG=off expected exit 0, got $rc"

  # FUNCTION_TOO_LONG: label present AND blocks.
  if grep -q 'FUNCTION_TOO_LONG' <<<"$(ck "$FX/longfn.py")"; then pass "FUNCTION_TOO_LONG label fires (longfn.py)"
  else fail "FUNCTION_TOO_LONG label missing (longfn.py)"; fi
  rc="$(ck_rc "$FX/longfn.py")"
  [[ "$rc" -eq 1 ]] && pass "longfn.py blocks (exit 1)" || fail "longfn.py expected exit 1, got $rc"

  # PARAM_COUNT: label present AND blocks.
  if grep -q 'PARAM_COUNT' <<<"$(ck "$FX/params.py")"; then pass "PARAM_COUNT label fires (params.py)"
  else fail "PARAM_COUNT label missing (params.py)"; fi
  rc="$(ck_rc "$FX/params.py")"
  [[ "$rc" -eq 1 ]] && pass "params.py blocks (exit 1)" || fail "params.py expected exit 1, got $rc"

  # GRABBAG_NAME: advisory -> label present but exit 0.
  if grep -q 'GRABBAG_NAME' <<<"$(ck "$FX/utils.py")"; then pass "GRABBAG_NAME advises (utils.py)"
  else fail "GRABBAG_NAME label missing (utils.py)"; fi
  rc="$(ck_rc "$FX/utils.py")"
  [[ "$rc" -eq 0 ]] && pass "utils.py advise => exit 0" || fail "utils.py expected exit 0 (advise), got $rc"

  # Detector FALSE-POSITIVE (a): JSON object literal + long while-block (.js)
  # must NOT trigger a blocking FUNCTION_TOO_LONG. No blocking FP => exit 0,
  # and no FUNCTION_TOO_LONG error line.
  out="$(ck "$FX/objlit.js")"
  if grep -qE 'FUNCTION_TOO_LONG +\(error\)' <<<"$out"; then
    fail "objlit.js: FUNCTION_TOO_LONG blocking false positive on a JSON literal / while-block"
  else
    pass "objlit.js: no FUNCTION_TOO_LONG blocking false positive"
  fi
  rc="$(ck_rc "$FX/objlit.js")"
  [[ "$rc" -eq 0 ]] && pass "objlit.js -> exit 0 (no block)" \
                    || fail "objlit.js expected exit 0 (no blocking FP), got $rc"

  # Detector FALSE-POSITIVE (b): a 5-arg CALL (not a def) must NOT trigger a
  # blocking PARAM_COUNT. No PARAM_COUNT label, exit 0.
  out="$(ck "$FX/call5.py")"
  if grep -q 'PARAM_COUNT' <<<"$out"; then
    fail "call5.py: PARAM_COUNT false positive on a 5-arg CALL (not a def)"
  else
    pass "call5.py: no PARAM_COUNT false positive on a call site"
  fi
  rc="$(ck_rc "$FX/call5.py")"
  [[ "$rc" -eq 0 ]] && pass "call5.py -> exit 0 (no block)" \
                    || fail "call5.py expected exit 0 (no PARAM_COUNT FP), got $rc"

  # TRUE POSITIVE preserved: a real 5-param def in a 600+-line file still
  # blocks (PARAM_COUNT + FILE_TOO_LONG both fire; exit 1).
  out="$(ck "$FX/realdef.py")"
  if grep -q 'PARAM_COUNT' <<<"$out"; then pass "realdef.py: PARAM_COUNT label fires (real 5-param def)"
  else fail "realdef.py: PARAM_COUNT label missing on a real 5-param def"; fi
  if grep -q 'FILE_TOO_LONG' <<<"$out"; then pass "realdef.py: FILE_TOO_LONG label fires (600+ lines)"
  else fail "realdef.py: FILE_TOO_LONG label missing on a 600+-line file"; fi
  rc="$(ck_rc "$FX/realdef.py")"
  [[ "$rc" -eq 1 ]] && pass "realdef.py blocks (exit 1)" || fail "realdef.py expected exit 1 (true positive), got $rc"

  # clean file -> exit 0.
  rc="$(ck_rc "$FX/clean.py")"
  [[ "$rc" -eq 0 ]] && pass "clean.py -> exit 0" || fail "clean.py expected exit 0, got $rc"

  # ── Detector FALSE-POSITIVE (c): CRAFT-FN-IIFE-RECURSION-FP ────────────
  # A no-bundler browser module wrapped in an IIFE `(function () { ... })();`
  # must NOT be scored as one giant function; internal functions must be
  # measured individually instead. See tools/lib/craftsmanship-detectors.sh
  # craft_fn_brace for the root-cause writeup (§4.2, Martin 2008 Ch.3).

  # (c1) IIFE module, all internal functions small (<=50 lines) -> 0 findings.
  {
    printf '(function () {\n'
    printf '  function small1() {\n'
    for i in $(seq 1 5); do printf '    var a%d = %d;\n' "$i" "$i"; done
    printf '  }\n'
    printf '  function small2() {\n'
    for i in $(seq 1 5); do printf '    var b%d = %d;\n' "$i" "$i"; done
    printf '  }\n'
    printf '})();\n'
  } > "$FX/iife_small.js"
  out="$(ck "$FX/iife_small.js")"
  if grep -q 'FUNCTION_TOO_LONG' <<<"$out"; then
    fail "iife_small.js: FUNCTION_TOO_LONG false positive on IIFE wrapper (internal fns small)"
  else
    pass "iife_small.js: no FUNCTION_TOO_LONG false positive (IIFE wrapper, small internals)"
  fi
  rc="$(ck_rc "$FX/iife_small.js")"
  [[ "$rc" -eq 0 ]] && pass "iife_small.js -> exit 0 (no block)" \
                    || fail "iife_small.js expected exit 0, got $rc"

  # (c2) IIFE module with ONE internal function >60 lines (>50*1.2 flex band)
  # -> exactly 1 FUNCTION_TOO_LONG finding, attributed to the INNER function's
  # header line, not to the wrapper (line 1).
  {
    printf '(function () {\n'
    printf '  function bigOne() {\n'
    for i in $(seq 1 65); do printf '    var x%d = %d;\n' "$i" "$i"; done
    printf '  }\n'
    printf '  function small1() {\n'
    for i in $(seq 1 5); do printf '    var a%d = %d;\n' "$i" "$i"; done
    printf '  }\n'
    printf '})();\n'
  } > "$FX/iife_big_inner.js"
  out="$(ck "$FX/iife_big_inner.js")"
  n_findings="$(grep -c 'FUNCTION_TOO_LONG' <<<"$out")"
  [[ "$n_findings" -eq 1 ]] && pass "iife_big_inner.js: exactly 1 FUNCTION_TOO_LONG finding" \
                            || fail "iife_big_inner.js: expected 1 FUNCTION_TOO_LONG finding, got $n_findings"
  if grep -q 'FUNCTION_TOO_LONG.*iife_big_inner\.js:2:' <<<"$out"; then
    pass "iife_big_inner.js: finding attributed to inner function header (line 2), not wrapper"
  else
    fail "iife_big_inner.js: finding not attributed to inner function header (line 2)"
  fi
  rc="$(ck_rc "$FX/iife_big_inner.js")"
  [[ "$rc" -eq 1 ]] && pass "iife_big_inner.js blocks (exit 1)" || fail "iife_big_inner.js expected exit 1, got $rc"

  # (c3) TRUE POSITIVE preserved: a plain (non-IIFE) named function >60 lines
  # in a NON-wrapped .js file still blocks -> non-regression on the base case.
  { printf 'function plainBig() {\n'; for i in $(seq 1 65); do printf '  var y%d = %d;\n' "$i" "$i"; done; printf '}\n'; } > "$FX/plain_big.js"
  if grep -q 'FUNCTION_TOO_LONG' <<<"$(ck "$FX/plain_big.js")"; then pass "plain_big.js: FUNCTION_TOO_LONG label fires (non-IIFE, non-regression)"
  else fail "plain_big.js: FUNCTION_TOO_LONG label missing (non-IIFE, non-regression)"; fi
  rc="$(ck_rc "$FX/plain_big.js")"
  [[ "$rc" -eq 1 ]] && pass "plain_big.js blocks (exit 1)" || fail "plain_big.js expected exit 1, got $rc"

  # (c4) TRUE POSITIVE preserved: a named-variable arrow function assignment
  # (`var f = () => {...}`) is NOT an IIFE (identifier precedes the arrow
  # header, not a grouping/unary-operator token) and must still block when
  # oversized.
  { printf 'var plainArrow = () => {\n'; for i in $(seq 1 65); do printf '  var z%d = %d;\n' "$i" "$i"; done; printf '};\n'; } > "$FX/plain_arrow.js"
  if grep -q 'FUNCTION_TOO_LONG' <<<"$(ck "$FX/plain_arrow.js")"; then pass "plain_arrow.js: FUNCTION_TOO_LONG label fires (assigned arrow, non-regression)"
  else fail "plain_arrow.js: FUNCTION_TOO_LONG label missing (assigned arrow, non-regression)"; fi
  rc="$(ck_rc "$FX/plain_arrow.js")"
  [[ "$rc" -eq 1 ]] && pass "plain_arrow.js blocks (exit 1)" || fail "plain_arrow.js expected exit 1, got $rc"
fi

echo
echo "C2 result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1
echo "C2 PASSED"
