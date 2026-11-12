#!/usr/bin/env bash
#
# mutation_check.sh — portable, EXTENSIBLE language->tool dispatcher for scoped
# mutation testing (rules/coding-standards.md §12). It detects the language of
# the changed source file(s) and runs the decided tool for it (§12.2 table),
# scoped to those files. The standard is 0 surviving NON-equivalent mutants on
# the changed code (§12.4) — there is no blunt percentage gate.
#
# Source: DeMillo, Lipton & Sayward (1978); Jia & Harman (2011) — see
# rules/coding-standards.md Primary Sources.
#
# EXTENSIBILITY (§1.2 Open/Closed): adding a language is adding ONE row to
# registry() plus its run_<lang> function — never editing the dispatch. The
# language<->tool knowledge lives as data, so an agent dropped on an unfamiliar
# repo (Kotlin/Gradle, Swift/SwiftUI, …) can `--discover` the setup instead of
# being limited to a hardcoded few. Each run_<lang> cites its tool's source.
#
# Unlike a repo's own wired runner (e.g. Cortex's Python scripts/mutation_check.sh
# which owns its [tool.mutmut] block), this gates ANY repo: it runs against the
# CURRENT working directory and requires that repo to carry the tool's per-repo
# config (§12.2 "wire concretely per repo"). It changes nothing permanent.
#
#   usage: mutation_check.sh [--tests <path>] <source-file> [<source-file> ...]
#          mutation_check.sh --discover        # detect this repo's language + tool + readiness
#          mutation_check.sh --list            # list supported languages and tools
#     --tests <path>   test selection (REQUIRED for Python/mutmut; ignored where
#                      the per-repo config owns the test command)
#   e.g. mutation_check.sh --tests tests_py/test_x.py pkg/x.py
#        mutation_check.sh src/parser.ts        # TypeScript/StrykerJS
#        mutation_check.sh src/Money.kt          # Kotlin/PIT (./gradlew pitest)
#        mutation_check.sh Sources/App/Auth.swift # Swift/Muter
#
# Exit codes (deterministic — this is a gate; the kernel decides, not the model):
#   0  every mutant on the changed code was killed, or the changed code holds no
#      mutant (or --discover/--list ran)
#   1  one or more mutants survived, or no test reaches them -> triage each
#      (missing test or documented equivalent, §12.1); a gate-failing result,
#      not an error
#   2  usage error (no sources, mixed/unknown language, missing --tests for Python)
#   3  the language's tool is not installed in this environment
#   4  the per-repo config the tool needs is missing (the message points at the fix)
#   5  no verdict (Python): mutmut left mutants unchecked, or its listing failed;
#      the message says which
set -euo pipefail

# ── Registry — the ONE place to add a language ───────────────────────────
# Columns: lang | space-separated extensions | install-probe binary | install hint
# Tool choices are the decided §12.2 set; each is sourced at its run_<lang>.
registry() {
  cat <<'EOF'
python|.py|mutmut|pip install mutmut (3.x)
typescript|.ts .tsx .cts .mts .js .jsx .cjs .mjs|stryker|npm i -D @stryker-mutator/core (+ runner)
rust|.rs|cargo-mutants|cargo install cargo-mutants
kotlin|.kt .kts|gradle|gradle-pitest-plugin id 'info.solidsoft.pitest' (./gradlew pitest)
swift|.swift|muter|brew install muter  (muter-mutation-testing/muter)
EOF
}

# Build-system markers -> language, for --discover on an unfamiliar repo.
# Extend alongside registry() when adding a language.
markers() {
  cat <<'EOF'
pyproject.toml|python
setup.cfg|python
Cargo.toml|rust
package.json|typescript
build.gradle|kotlin
build.gradle.kts|kotlin
settings.gradle|kotlin
settings.gradle.kts|kotlin
Package.swift|swift
EOF
}

supported_langs() { registry | cut -d'|' -f1 | paste -sd' ' -; }

# Look up a registry column (2=exts,3=probe,4=install) for a language.
reg_field() {
  registry | awk -F'|' -v l="$1" -v c="$2" '$1==l {print $c; exit}'
}

# Map a file path to its language token via the registry, or "" if unrecognised.
lang_of() {
  local ext=".${1##*.}" lang exts e
  while IFS='|' read -r lang exts _; do
    for e in $exts; do [ "$e" = "$ext" ] && { echo "$lang"; return 0; }; done
  done < <(registry)
  echo ""
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "mutation_check: '$1' not installed — $LANG mutation tool absent (§12.2). Install: $2" >&2
  exit 3
}

# ── Discovery — answer "what is this repo's mutation setup?" ──────────────
discover() {
  local hit=0 glob lang
  while IFS='|' read -r glob lang; do
    compgen -G "$glob" >/dev/null 2>&1 || continue
    hit=1
    local probe; probe="$(reg_field "$lang" 3)"
    local ready="installed"; command -v "$probe" >/dev/null 2>&1 || ready="MISSING ($(reg_field "$lang" 4))"
    printf '%-11s via %-14s [%s]  (marker: %s)\n' "$lang" "$probe" "$ready" "$glob"
  done < <(markers)
  [ "$hit" -eq 1 ] || { echo "mutation_check: no known build-system marker found in $(pwd)"; return 0; }
}

list_langs() {
  printf '%-11s %-15s %s\n' LANGUAGE TOOL INSTALL
  registry | awk -F'|' '{printf "%-11s %-15s %s\n", $1, $3, $4}'
}

# ── Python: mutmut, delegating to this repo's [tool.mutmut] ───────────────
# Source: mutmut 3.x (boxed.gg/mutmut). Repoint only_mutate + the test selection
# at the change under test, run, then restore pyproject.toml untouched.
run_python() {
  [ -n "$TESTS" ] || { echo "mutation_check: Python needs --tests <path> for mutmut" >&2; exit 2; }
  require_tool mutmut "pip install mutmut (3.x)"
  # NB: py/bak are script-scope, NOT local — the cleanup() trap fires on EXIT,
  # which is AFTER run_python returns, so a `local` here would be out of scope at
  # trap time and `set -u` would abort with "bak: unbound variable".
  py="pyproject.toml"
  [ -f "$py" ] && grep -q '^\[tool.mutmut\]' "$py" \
    || { echo "mutation_check: no [tool.mutmut] in $py — wire it per §12.2" >&2; exit 4; }

  bak="$(mktemp)"; cp "$py" "$bak"
  cleanup() { cp "$bak" "$py"; rm -f "$bak"; rm -rf mutants .mutmut-cache; }
  trap cleanup EXIT

  python3 - "$py" "$TESTS" "${SOURCES[@]}" <<'PYEOF'
import re, sys
path, tests, sources = sys.argv[1], sys.argv[2], sys.argv[3:]
fmt = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
src = open(path).read()
src, n1 = re.subn(r'^only_mutate = .*$', "only_mutate = " + fmt(sources), src, 1, re.M)
src, n2 = re.subn(r'^pytest_add_cli_args_test_selection = .*$',
                  "pytest_add_cli_args_test_selection = " + fmt([tests]), src, 1, re.M)
assert n1 and n2, "[tool.mutmut] must define only_mutate and pytest_add_cli_args_test_selection"
open(path, "w").write(src)
PYEOF

  echo ">>> mutmut | mutate: ${SOURCES[*]} | tests: $TESTS"
  local run_rc=0
  mutmut run || run_rc=$?
  mutmut_verdict "$run_rc"
}

# mutmut_verdict <exit status of mutmut run>: the gate's answer for Python.
mutmut_verdict() {
  # The listing of every mutant decides, not the exit status of the run: read it
  # whole, then look at each status. `mutmut results | grep -q` is false under
  # pipefail whenever grep leaves at its first match while mutmut is still
  # writing (BrokenPipeError, non-zero): the gate then printed "0 surviving
  # mutants" over a listing full of them.
  # source: measured 2026-11-12 with mutmut 3.8.1. `mutmut results --all true`
  # lists every mutant with its status and exits 0: "survived"; "no tests" for a
  # function no test calls; "not checked" for each mutant when the clean test
  # run fails (mutmut run exits 1); "killed"; nothing when the code holds no
  # mutant (mutmut run exits 1 there too). Cortex's scripts/mutation_check.sh
  # reads the listing whole and fails on survivors and on untested mutants
  # (Cortex ADR-1122).
  local listing blocking unchecked
  listing="$(mutmut results --all true)" || {
    echo "mutation_check: 'mutmut results --all true' failed (mutmut run exited $1) — no verdict" >&2
    return 5
  }
  blocking="$(grep -E ': (survived|no tests)[[:space:]]*$' <<<"$listing" || true)"
  if [ -n "$blocking" ]; then
    echo ">>> SURVIVORS (triage each — missing test or documented equivalent, §12.1):" >&2
    printf '%s\n' "$blocking" >&2
    return 1
  fi
  unchecked="$(grep -cE ': not checked[[:space:]]*$' <<<"$listing" || true)"
  if [ "$unchecked" -gt 0 ]; then
    echo "mutation_check: mutmut left $unchecked mutant(s) unchecked (mutmut run exited $1) — no verdict" >&2
    return 5
  fi
  if [ -z "$listing" ]; then
    echo ">>> no mutant in the changed code (mutmut run exited $1)."
    return 0
  fi
  echo ">>> 0 surviving mutants on changed code."
}

# ── TypeScript / JS: StrykerJS, scoped to the changed files ───────────────
# Source: StrykerJS (stryker-mutator.io). break:null in the config means the JSON
# report — not the process exit — is the authority on survivors.
run_typescript() {
  command -v stryker >/dev/null 2>&1 || command -v npx >/dev/null 2>&1 \
    || require_tool stryker "npm i -D @stryker-mutator/core (+ runner)"
  [ -f stryker.conf.json ] || [ -f stryker.conf.js ] \
    || { echo "mutation_check: no stryker.conf.json — copy templates/mutation/stryker.conf.json (§12.2)" >&2; exit 4; }

  local runner; runner=$(command -v stryker || echo "npx stryker")
  local report; report="$(mktemp -d)/mutation.json"
  local glob; glob="$(IFS=,; echo "${SOURCES[*]}")"
  echo ">>> stryker | mutate: ${SOURCES[*]}"
  $runner run --mutate "$glob" --reporters json --jsonReporter.fileName "$report" || true
  scan_stryker_json "$report"
}

# StrykerJS mutation-report schema: files{}.mutants[].status; a mutant is killed
# unless its status is Survived or NoCoverage (stryker-mutator.io report schema).
scan_stryker_json() {
  [ -f "$1" ] || { echo "mutation_check: stryker produced no JSON report at $1" >&2; return 1; }
  local n
  n="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(sum(1 for f in d.get("files",{}).values() for m in f.get("mutants",[])
         if m.get("status") in ("Survived","NoCoverage")))' "$1")"
  report_survivors "$n" "$1"
}

# ── Kotlin / JVM: PIT via the Gradle plugin ───────────────────────────────
# Source: gradle-pitest-plugin (gradle-pitest-plugin.solidsoft.info,
# github.com/szpak/gradle-pitest-plugin). Scope per-change via the plugin's
# targetClasses in build.gradle; survivors are status="SURVIVED" in mutations.xml.
run_kotlin() {
  local gw="./gradlew"; [ -x "$gw" ] || gw="gradle"
  command -v "$gw" >/dev/null 2>&1 || [ -x ./gradlew ] \
    || require_tool gradle "the gradle-pitest-plugin (id 'info.solidsoft.pitest')"
  echo ">>> $gw pitest  (scope via plugin targetClasses for: ${SOURCES[*]})"
  "$gw" pitest || true
  local xml="build/reports/pitest/mutations.xml"
  [ -f "$xml" ] || { echo "mutation_check: no $xml — is gradle-pitest-plugin applied? (§12.2)" >&2; exit 4; }
  if grep -q 'status="SURVIVED"\|status="NO_COVERAGE"' "$xml"; then
    echo ">>> surviving/uncovered mutant(s) in $xml — triage each (§12.1)." >&2
    return 1
  fi
  echo ">>> 0 surviving mutants on changed code."
}

# ── Swift: Muter, scoped to the changed files ─────────────────────────────
# Source: Muter (github.com/muter-mutation-testing/muter). `muter` runs by
# default; --files-to-mutate scopes it; the JSON report is the survivor authority.
run_swift() {
  require_tool muter "brew install muter (muter-mutation-testing/muter)"
  [ -f muter.conf.json ] || [ -f .muter.conf.json ] \
    || { echo "mutation_check: no muter.conf.json — run 'muter init' (§12.2)" >&2; exit 4; }
  local report; report="$(mktemp -d)/muter.json"
  echo ">>> muter --files-to-mutate ${SOURCES[*]}"
  muter --files-to-mutate "${SOURCES[*]}" --format json --output "$report" || true
  scan_muter_json "$report"
}

# Muter JSON report: fileReports[].appliedOperators[].testSuiteOutcome. A mutant
# is killed iff the suite then FAILED; "passed" means it survived (muter README,
# github.com/muter-mutation-testing/muter). Confirm the field when wiring a repo.
scan_muter_json() {
  [ -f "$1" ] || { echo "mutation_check: muter produced no JSON report at $1" >&2; return 1; }
  local n
  n="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
files=d.get("fileReports", d.get("file_reports", []))
print(sum(1 for f in files for op in f.get("appliedOperators",[])
         if op.get("testSuiteOutcome", op.get("outcome","")) == "passed"))' "$1")"
  report_survivors "$n" "$1"
}

# Shared verdict: a positive survivor count fails the gate (exit 1 via return 1).
report_survivors() {
  if [ "${1:-1}" -gt 0 ]; then
    echo ">>> $1 surviving mutant(s) — triage each (§12.1). Report: $2" >&2
    return 1
  fi
  echo ">>> 0 surviving mutants on changed code."
}

# ── Argument parse ────────────────────────────────────────────────────────
TESTS=""
SOURCES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --discover) discover; exit 0 ;;
    --list) list_langs; exit 0 ;;
    --tests) TESTS="${2:-}"; shift 2 ;;
    --tests=*) TESTS="${1#*=}"; shift ;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; while [ $# -gt 0 ]; do SOURCES+=("$1"); shift; done ;;
    -*) echo "mutation_check: unknown flag: $1 (try --help / --list / --discover)" >&2; exit 2 ;;
    *) SOURCES+=("$1"); shift ;;
  esac
done

[ "${#SOURCES[@]}" -gt 0 ] || { echo "mutation_check: no source files given (see --help)" >&2; exit 2; }

# All sources must share one language so a single tool run covers them.
LANG=""
for f in "${SOURCES[@]}"; do
  l="$(lang_of "$f")"
  [ -n "$l" ] || { echo "mutation_check: unrecognised language for: $f (supported: $(supported_langs))" >&2; exit 2; }
  if [ -z "$LANG" ]; then LANG="$l"
  elif [ "$l" != "$LANG" ]; then
    echo "mutation_check: mixed languages ($LANG vs $l); run one language per invocation" >&2; exit 2
  fi
done

declare -f "run_$LANG" >/dev/null \
  || { echo "mutation_check: no runner wired for $LANG (add run_$LANG)" >&2; exit 2; }
"run_$LANG"
