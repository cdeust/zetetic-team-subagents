#!/usr/bin/env bash
# doc-count-check.sh — every number a document states about this project is
# recomputed from the tree and compared. Fails the build on drift.
#
# Why (issue #72): four files gave four different agent/skill/hook totals and
# none matched the tree. memory/scope-coverage.md had already recorded one of
# those discrepancies, which shows the drift was noticed once and then
# re-accumulated, because nothing measured it.
#
# The convention these commands implement is written down in docs/COUNTING.md.
# That file is the explanation; this one is the enforcement. Change one and the
# other is wrong.
#
# Usage:
#   bash tools/doc-count-check.sh            check every registered claim
#   bash tools/doc-count-check.sh --report   print the measured quantities only
#
# Exit: 0 when every claim matches; 1 on any mismatch or unmatched pattern;
# 2 on a usage or environment error.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to repo root $REPO_ROOT" >&2; exit 1; }

# ── Claim registry ─────────────────────────────────────────────────────
# file | quantity key | extended regex with EXACTLY ONE capture group around
# the digits. A pattern that matches zero lines is a FAILURE, not a skip: copy
# reworded out from under a claim must break the build, not quietly stop being
# checked.
#
# A pattern that STARTS with the capture group needs a [^0-9] guard in front of
# it. Extraction is a greedy sed substitution, so `([0-9]+) genius agents` reads
# "97 genius agents" as 7: the leading .* swallows the 9. The guard forces the
# match to begin at a non-digit and captures the whole number.
CLAIMS=$(cat <<'REGISTRY'
README.md|agents_total|badge/agents-([0-9]+)-
README.md|skills_total|badge/skills-([0-9]+)-
README.md|hook_registrations|badge/hooks-([0-9]+)_lifecycle
README.md|suites|badge/suites-([0-9]+)-
README.md|genius_agents|[^0-9]([0-9]+) genius agents \(plus
README.md|team_agents|genius agents \(plus ([0-9]+) team-role
README.md|agents_total|team-role agents = ([0-9]+) total
README.md|skills_total|\*\*([0-9]+) multi-step workflows\*\*
README.md|problem_skills|\| ([0-9]+) problem-shaped skills route you
README.md|category_skills|[^0-9]([0-9]+) category skills run full pipelines
README.md|memory_suites|\*\*([0-9]+) memory suites\*\*
README.md|agents_total|All ([0-9]+) agent files pass
CONTRIBUTING.md|genius_agents|ships \*\*([0-9]+) reasoning
CONTRIBUTING.md|team_agents|patterns \+ ([0-9]+) team agents
CONTRIBUTING.md|skills_total|team agents \+ ([0-9]+) skills
CONTRIBUTING.md|hook_registrations|skills \+ ([0-9]+) lifecycle hooks
.claude-plugin/marketplace.json|genius_agents|[^0-9]([0-9]+) reasoning patterns from history
.claude-plugin/marketplace.json|team_agents|\+ ([0-9]+) team specialists
.claude-plugin/marketplace.json|problem_skills|Complete system: ([0-9]+) problem-shaped skills
.claude-plugin/marketplace.json|genius_agents|problem-shaped skills backed by ([0-9]+) genius agents
.claude-plugin/marketplace.json|team_agents|genius agents, ([0-9]+) team agents
.claude-plugin/marketplace.json|skills_total|[^0-9]([0-9]+) skills total
.claude-plugin/marketplace.json|commands|skills total, ([0-9]+) commands
.claude-plugin/marketplace.json|tools|commands, ([0-9]+) tools
.claude-plugin/marketplace.json|hook_scripts|tools, ([0-9]+) hooks
README.md|problem_skills|distribution of ([0-9]+) problem-shaped skills
README.md|problem_skills|entry point: ([0-9]+) problem-shaped skills
README.md|problem_skills|. ([0-9]+) problem-shaped skills route you
README.md|category_skills|. ([0-9]+) category skills run full pipelines
README.md|skills_total|\*\*([0-9]+) multi-step workflows
skills/_index.md|skills_total|covers ([0-9]+) skills:
skills/_index.md|problem_skills|[^0-9]([0-9]+) problem-shaped entry points
skills/_index.md|category_skills|plus ([0-9]+) category skills
docs/COUNTING.md|problem_skills|problem-shaped skills .*[^0-9]([0-9]+) .$
docs/COUNTING.md|category_skills|category skills .*[^0-9]([0-9]+) .$
docs/COUNTING.md|skills_total|skill documents .*[^0-9]([0-9]+) .$
REGISTRY
)

# ── Measurement ────────────────────────────────────────────────────────
# One function per quantity, each the exact command from docs/COUNTING.md.
count_genius_agents()    { grep -l '^name:' agents/genius/*.md 2>/dev/null | wc -l | tr -d ' '; }
count_team_agents()      { grep -l '^name:' agents/*.md 2>/dev/null | wc -l | tr -d ' '; }
count_problem_skills()   { find skills -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' '; }
count_skills_total()     { find skills -name '*.md' ! -name '_index.md' ! -name '_template.md' 2>/dev/null | wc -l | tr -d ' '; }
count_hook_scripts()     { ls hooks/*.sh hooks/*.py 2>/dev/null | wc -l | tr -d ' '; }
count_commands()         { find commands -name '*.md' 2>/dev/null | wc -l | tr -d ' '; }
count_tools()            { ls tools/*.sh tools/*.py 2>/dev/null | wc -l | tr -d ' '; }
count_suites()           { bash tests/run-all.sh --list 2>/dev/null | wc -l | tr -d ' '; }
count_memory_suites()    { ls scripts/test-memory-*.sh 2>/dev/null | wc -l | tr -d ' '; }

count_hook_registrations() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "FATAL: jq is required to count hook registrations in hooks/hooks.json" >&2
    exit 2
  fi
  jq '[.hooks[][].hooks[]] | length' hooks/hooks.json
}

GENIUS_AGENTS="$(count_genius_agents)"
TEAM_AGENTS="$(count_team_agents)"
AGENTS_TOTAL=$(( GENIUS_AGENTS + TEAM_AGENTS ))
PROBLEM_SKILLS="$(count_problem_skills)"
SKILLS_TOTAL="$(count_skills_total)"
CATEGORY_SKILLS=$(( SKILLS_TOTAL - PROBLEM_SKILLS ))
HOOK_REGISTRATIONS="$(count_hook_registrations)"
HOOK_SCRIPTS="$(count_hook_scripts)"
COMMANDS="$(count_commands)"
TOOLS="$(count_tools)"
SUITES="$(count_suites)"
MEMORY_SUITES="$(count_memory_suites)"

quantity_of() {
  case "$1" in
    genius_agents)      printf '%s' "$GENIUS_AGENTS" ;;
    team_agents)        printf '%s' "$TEAM_AGENTS" ;;
    agents_total)       printf '%s' "$AGENTS_TOTAL" ;;
    problem_skills)     printf '%s' "$PROBLEM_SKILLS" ;;
    category_skills)    printf '%s' "$CATEGORY_SKILLS" ;;
    skills_total)       printf '%s' "$SKILLS_TOTAL" ;;
    hook_registrations) printf '%s' "$HOOK_REGISTRATIONS" ;;
    hook_scripts)       printf '%s' "$HOOK_SCRIPTS" ;;
    commands)           printf '%s' "$COMMANDS" ;;
    tools)              printf '%s' "$TOOLS" ;;
    suites)             printf '%s' "$SUITES" ;;
    memory_suites)      printf '%s' "$MEMORY_SUITES" ;;
    *)                  return 1 ;;
  esac
}

report() {
  printf '%-20s %s\n' "genius_agents" "$GENIUS_AGENTS"
  printf '%-20s %s\n' "team_agents" "$TEAM_AGENTS"
  printf '%-20s %s\n' "agents_total" "$AGENTS_TOTAL"
  printf '%-20s %s\n' "problem_skills" "$PROBLEM_SKILLS"
  printf '%-20s %s\n' "category_skills" "$CATEGORY_SKILLS"
  printf '%-20s %s\n' "skills_total" "$SKILLS_TOTAL"
  printf '%-20s %s\n' "hook_registrations" "$HOOK_REGISTRATIONS"
  printf '%-20s %s\n' "hook_scripts" "$HOOK_SCRIPTS"
  printf '%-20s %s\n' "commands" "$COMMANDS"
  printf '%-20s %s\n' "tools" "$TOOLS"
  printf '%-20s %s\n' "suites" "$SUITES"
  printf '%-20s %s\n' "memory_suites" "$MEMORY_SUITES"
}

if [[ "${1:-}" == "--report" ]]; then
  report
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  echo "usage: bash tools/doc-count-check.sh [--report]" >&2
  exit 2
fi

# ── Verification ───────────────────────────────────────────────────────
SED_D=$'\001'
checked=0
bad=0

while IFS='|' read -r file key regex; do
  [[ -z "$file" ]] && continue

  if [[ ! -f "$file" ]]; then
    printf 'ERROR    %s: registered document does not exist\n' "$file"
    bad=$(( bad + 1 ))
    continue
  fi

  expected="$(quantity_of "$key")" || {
    printf 'ERROR    %s: unknown quantity key "%s" in the registry\n' "$file" "$key"
    bad=$(( bad + 1 ))
    continue
  }

  found=0
  while IFS= read -r actual; do
    [[ -z "$actual" ]] && continue
    found=$(( found + 1 ))
    checked=$(( checked + 1 ))
    if [[ "$actual" != "$expected" ]]; then
      bad=$(( bad + 1 ))
      printf 'DRIFT    %s: %s claims %s, tree has %s   [/%s/]\n' \
        "$file" "$key" "$actual" "$expected" "$regex"
    fi
    # SED_D, not '|': a registered pattern may contain a literal pipe (markdown
    # tables are full of them). With '|' as the delimiter sed strips the
    # backslash from '\|' and hands ERE a bare alternation, silently turning the
    # pattern into ".*  OR  <rest>" and matching nothing. A control character
    # cannot appear in a regex here, so it can never collide.
  done < <(sed -nE "s${SED_D}.*${regex}.*${SED_D}\1${SED_D}p" "$file")

  if [[ "$found" -eq 0 ]]; then
    bad=$(( bad + 1 ))
    printf 'UNMATCHED %s: no line matches the registered claim for %s   [/%s/]\n' \
      "$file" "$key" "$regex"
    printf '          The copy was reworded, or the claim was removed. Update the\n'
    printf '          registry in tools/doc-count-check.sh, or restore the claim.\n'
  fi
done <<< "$CLAIMS"

echo ""
printf 'doc-count-check: %d claim instance(s) verified, %d problem(s)\n' "$checked" "$bad"

if [[ "$checked" -eq 0 ]]; then
  echo "FATAL: the registry matched nothing at all — the gate is broken." >&2
  exit 2
fi

if [[ "$bad" -gt 0 ]]; then
  echo "FAILED: a document states a number the tree does not support."
  echo "        Convention and commands: docs/COUNTING.md"
  exit 1
fi

echo "PASSED: every documented count matches the tree."
exit 0
