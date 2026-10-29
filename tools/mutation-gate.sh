#!/usr/bin/env bash
#
# mutation-gate.sh — the LOOP-FACING test-strength gate. Wraps the scoped
# mutation runner (tools/mutation_check.sh) so the autonomous build loop can run
# mutation testing as one of its acceptance gates (memory/acceptance-gates*.yaml)
# without freezing on the cases a raw mutation_check.sh invocation rejects.
#
# Why a wrapper, not a raw mutation_check.sh gate: mutation_check.sh is a precise
# per-language tool (one language per call; Python needs --tests; exits 2/3/4 on
# usage / missing-runner / missing-config). A loop iteration's changed set is
# arbitrary (often .md/.sh only, or mixed languages, on a host without the
# runner). This wrapper makes the gate PROPORTIONAL and SOUND:
#
#   * no mutation-applicable changed source  -> PASS (exit 0): nothing to test.
#   * applicable source, runner+config ready -> run mutation_check.sh per language;
#       a SURVIVING mutant -> FAIL (exit 1): the real test-strength failure.
#   * applicable source, runner/config absent -> GRACEFUL DEGRADATION (exit 0 with
#       a LOUD stderr warning), per coding-standards.md §12: do not
#       report a mutation result you did not execute, and do not silently block a
#       tool-less environment. The authoritative external check remains the
#       human/CI re-gate (autonomous-build-loop INV-2). Survivors are the only
#       thing that blocks — absence of a runner is surfaced, not faked either way.
#
# Single source of truth: the language<->extension table is parsed from
# tools/mutation_check.sh registry() — adding a language there extends this gate
# automatically (coding-standards.md §1.2 Open/Closed). This file never restates
# the table.
#
# Python test selection: mutmut needs a test path. Resolved from $MUTATION_GATE_TESTS,
# else the first existing of: tests/ tests_py/ test/. If none resolves, the Python
# group degrades (warn), it does not block.
#
#   usage: mutation-gate.sh <changed-file> [<changed-file> ...]
#          mutation-gate.sh --staged          # files from the git staged diff
#
# Exit codes (deterministic — this is a gate): 0 pass or degraded; 1 surviving
# mutant on changed code. source: §12 (DeMillo–Lipton–Sayward 1978; Jia & Harman
# 2011); product-safety §12.5 (blocking half = scoped run).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# MUTATION_CHECK_BIN overrides the scoped runner — a test-injection seam only
# (tools/tests/mutation-gate/); production leaves it unset.
CHECK="${MUTATION_CHECK_BIN:-$ROOT/tools/mutation_check.sh}"

# --staged: derive the file list from the git index (parity with zetetic-checker
# / craftsmanship-checker, so memory/acceptance-gates.yaml can run it on staged
# files exactly as the loop config runs it on the {files} token).
if [ "${1:-}" = "--staged" ]; then
  set --
  while IFS= read -r _f; do [ -n "$_f" ] && set -- "$@" "$_f"; done \
    < <(git -C "$ROOT" diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
fi

[ "$#" -ge 1 ] || { echo "mutation-gate: no files given — PASS (nothing to test)"; exit 0; }
if [ ! -x "$CHECK" ]; then
  echo "⚠ mutation-gate: tools/mutation_check.sh not found — test-strength UNVERIFIED (degraded). Survivors uncheckable here; rely on the human/CI re-gate." >&2
  exit 0
fi

# ── ext -> lang, parsed ONCE from mutation_check.sh registry() (single source) ─
# Registry rows are 'lang|.ext .ext|probe|hint'; we read columns 1 and 2. Cached
# in REG so lang_of does no I/O per call. bash 3.2-safe (macOS default): no
# associative arrays, no mapfile.
REG="$(sed -n '/^registry()/,/^}/p' "$CHECK" | sed -n "/<<'EOF'/,/^EOF/p")"
lang_of() {
  local target=".${1##*.}" lang exts e
  while IFS='|' read -r lang exts _; do
    case "$lang" in [a-z]*) ;; *) continue ;; esac
    for e in $exts; do [ "$e" = "$target" ] && { printf '%s' "$lang"; return 0; }; done
  done <<EOF
$REG
EOF
  printf ''
}

resolve_python_tests() {
  if [ -n "${MUTATION_GATE_TESTS:-}" ]; then printf '%s' "$MUTATION_GATE_TESTS"; return 0; fi
  local d
  for d in tests tests_py test; do [ -d "$ROOT/$d" ] && { printf '%s' "$d"; return 0; }; done
  printf ''
}

# ── Collect the distinct languages present in the changed set (bash 3.2-safe:
# parallel string of unique langs, no associative arrays) ─────────────────────
langs_seen=""
for f in "$@"; do
  l="$(lang_of "$f")"
  [ -n "$l" ] || continue              # unsupported extension (.md/.sh/...) -> skip
  case " $langs_seen " in *" $l "*) ;; *) langs_seen="$langs_seen $l" ;; esac
done

if [ -z "$langs_seen" ]; then
  echo "mutation-gate: no mutation-applicable source in the changed set — PASS"
  exit 0
fi

# ── Run per language; translate exit codes ────────────────────────────────────
overall=0
for lang in $langs_seen; do
  # Re-filter the changed set to this language's files (word-split is intended).
  files=()
  for f in "$@"; do [ "$(lang_of "$f")" = "$lang" ] && files+=("$f"); done
  args=()
  if [ "$lang" = "python" ]; then
    tp="$(resolve_python_tests)"
    if [ -z "$tp" ]; then
      echo "⚠ mutation-gate[$lang]: no test path resolvable (set MUTATION_GATE_TESTS or add tests/) — test-strength UNVERIFIED for ${files[*]} (degraded, not blocking)." >&2
      continue
    fi
    args+=(--tests "$tp")
  fi
  rc=0
  # bash 3.2 + set -u: expand a possibly-empty array without tripping "unbound".
  out="$("$CHECK" ${args[@]+"${args[@]}"} "${files[@]}" 2>&1)" || rc=$?
  case "$rc" in
    0) echo "mutation-gate[$lang]: all mutants killed on changed code — PASS" ;;
    1) echo "$out"; echo "✗ mutation-gate[$lang]: surviving mutant(s) on changed code — test suite is not adequate (§12.4). Kill or document-as-equivalent each survivor."; overall=1 ;;
    2) echo "⚠ mutation-gate[$lang]: mutation_check usage/scope issue (rc=2) — UNVERIFIED (degraded): $out" >&2 ;;
    3) echo "⚠ mutation-gate[$lang]: mutation runner not installed (rc=3) — test-strength UNVERIFIED (degraded, per Move 8 step 2). Install the runner or rely on the human/CI re-gate." >&2 ;;
    4) echo "⚠ mutation-gate[$lang]: per-repo mutation config missing (rc=4) — UNVERIFIED (degraded): $out" >&2 ;;
    *) echo "⚠ mutation-gate[$lang]: mutation_check exited $rc — UNVERIFIED (degraded): $out" >&2 ;;
  esac
done

exit "$overall"
