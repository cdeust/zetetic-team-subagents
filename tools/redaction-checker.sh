#!/usr/bin/env bash
# redaction-checker.sh — Scan reader-facing Markdown copy for mechanically
# detectable AI-writing patterns.
#
# Usage:
#   tools/redaction-checker.sh --staged              # check staged .md changes (commit hook, warn-only)
#   tools/redaction-checker.sh --files <f1> <f2> ... # check specific files (review / CI)
#   tools/redaction-checker.sh --full                # audit sweep: all tracked
#                                                    #   AND untracked-not-ignored copy paths
#
# Checks (the greppable subset of skills/writing/redaction.md; judgment-level
# patterns — puffery, -ing analysis, colon reveals in context — stay with the
# skill, which is the authoritative inventory):
#   - EM_DASH  (warning): em dash in prose copy. House rule: zero in published copy.
#   - BANNED_WORD (warning): the skill's banned-outright vocabulary (§7).
#   - WEASEL (warning): unsourced-attribution and filler phrases (§5, §23).
#
# Severity model:
#   - All findings are WARNINGS by default: exit 0, findings on stdout. Prose
#     judgment belongs to a human or the /redaction skill; the mechanical layer
#     only surfaces candidates. ZETETIC_PROFILE=strict (via .zetetic.conf,
#     same contract as zetetic-checker.sh) makes findings exit 1.
#
# Scope: reader-facing copy only — README*, CHANGELOG*, docs/, top-level *.md.
# The pattern inventory itself, agent definitions, skills, templates, and test
# fixtures quote these patterns as examples and are always excluded.
#
# Exit codes: 0 clean (or warnings in default profile), 1 findings in strict, 2 usage error.
#
# Rule provenance: skills/writing/redaction.md (vendored from blader/humanizer
# v2.9.1 + petergyang/no-ai-slop, MIT; house deltas). Issue: #43.

set -euo pipefail
shopt -s extglob   # inline-code-span stripping in scan_file uses *(...)

# ── Scope ──────────────────────────────────────────────────────────────
COPY_INCLUDE='(^|/)(README[^/]*|CHANGELOG[^/]*|CONTRIBUTING[^/]*|SECURITY[^/]*|PRIVACY[^/]*|CODE_OF_CONDUCT[^/]*)\.md$|^docs/.*\.md$'
COPY_EXCLUDE='^skills/|^agents/|^templates/|^tools/tests/|^tests/|^memory/|^rules/|node_modules/|^plugins/.*/(skills|agents)/'

# ── Patterns ───────────────────────────────────────────────────────────
# source: skills/writing/redaction.md §7 (banned vocabulary), §5 (weasel), §23 (filler), §14 (em dash)
EM_DASH_RE=$'—'
# Word boundaries are spelled out rather than `\b`: matching moved to bash's
# builtin `=~` (POSIX ERE via regcomp), which does NOT support the GNU `\b`
# extension — verified on bash 5.3.9, where `\b` silently matches nothing and
# every BANNED_WORD finding disappears. The vocabulary is group 2.
BANNED_RE='(^|[^[:alnum:]_])([Dd]elve|[Ff]oster(s|ing)?|[Ll]everag(e|es|ing)|[Uu]tiliz(e|es|ing)|[Ff]acilitat(e|es|ing)|[Ee]mpower(s|ing)?|[Ss]treamlin(e|es|ing)|[Rr]obust|[Cc]utting-edge|[Pp]aradigm shift|[Gg]ame.changer|[Tt]apestry|[Mm]ultifaceted|[Mm]eticulous|[Pp]aramount|[Tt]ransformative|[Ee]mbark(s|ing)?|[Ss]upercharg(e|es|ing)|[Hh]arness(es|ing)?|[Ee]ver-evolving)([^[:alnum:]_]|$)'
WEASEL_RE="([Ss]tudies show|[Ee]xperts (agree|argue|believe)|[Ii]ndustry reports|[Ww]idely regarded|[Ii]t.s worth noting|[Ii]t.s important to note|[Ii]n today.s world|[Aa]t the end of the day|[Ll]et.s dive in|[Ii]n the ever-|[Gg]ame.changing)"
# source: skills/writing/redaction.md §9/§35 (binary contrasts, negative listing, dramatic fragmentation)
CONTRAST_RE="((It|This|That)('s| is) not [^.]{2,60}\.[[:space:]]*(It|This|That)('s| is)|[Nn]ot (a|an|the) [^.]{1,40}\.[[:space:]]*Not (a|an|the)|That.s it\.[[:space:]]*That.s|not just [^,.;]{2,40}, but)"
# source: redaction.md §30/§31/§28/§27 (throat-clearing, faux insight, signposting, rhetorical setups)
SETUP_RE="([Hh]ere.s the thing|[Ll]et me be clear|[Ww]hat nobody tells you|[Tt]he part everyone misses|[Ii]n this (article|section|page)|[Ww]e will explore|[Ii]n conclusion|[Ww]hat if I told you|[Pp]lot twist:|[Tt]hink about it:)"
# source: redaction.md §1/§4/§8/§20-22 (puffery, promotional, copula avoidance, AI conversation artifacts)
PUFF_RE="([Tt]estament to|[Pp]ivotal moment|(vital|crucial) role|[Ii]ndelible mark|[Ee]volving landscape|[Nn]estled|[Bb]reathtaking|[Ss]tunning|[Rr]enowned|serves as (a|an|the)|stands as|I hope this helps|knowledge cutoff|[Gg]reat question|[Ll]et me know if you)"

# ── Profile (same contract as zetetic-checker.sh: declared, not env-silent) ──
ZETETIC_PROFILE="${ZETETIC_PROFILE:-standard}"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [[ -f "$repo_root/.zetetic.conf" ]]; then
  profile_line=$(grep -E '^[[:space:]]*ZETETIC_PROFILE=' "$repo_root/.zetetic.conf" | tail -1 || true)
  [[ -n "$profile_line" ]] && ZETETIC_PROFILE="${profile_line#*=}"
fi

# ── File selection ─────────────────────────────────────────────────────
mode="${1:-}"
files=()
case "$mode" in
  --staged)
    while IFS= read -r f; do files+=("$f"); done \
      < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | grep -E "$COPY_INCLUDE" | grep -Ev "$COPY_EXCLUDE" || true)
    ;;
  --files)
    shift
    [[ $# -eq 0 ]] && { echo "usage: $0 --files <f1> [f2 ...]" >&2; exit 2; }
    for f in "$@"; do
      if echo "$f" | grep -qE "$COPY_INCLUDE" && ! echo "$f" | grep -qE "$COPY_EXCLUDE"; then
        files+=("$f")
      fi
    done
    ;;
  --full)
    # Tracked copy paths (--cached) PLUS untracked-but-not-ignored files
    # (--others --exclude-standard). A NEW file not yet committed was invisible
    # to a plain `git ls-files`, so a local --full passed while CI's Redaction
    # Sweep — which sees the committed tree once the file lands — failed: a false
    # local pass (issue #64). --exclude-standard honours .gitignore, so ignored
    # artifacts stay out. The two sets are disjoint (untracked ≠ in-index), so no
    # file is scanned twice; tracked-file behaviour is byte-for-byte unchanged.
    while IFS= read -r f; do files+=("$f"); done \
      < <(git ls-files --cached --others --exclude-standard 2>/dev/null | grep -E "$COPY_INCLUDE" | grep -Ev "$COPY_EXCLUDE" || true)
    ;;
  *)
    echo "usage: $0 --staged | --files <f...> | --full" >&2
    echo "  --full scans tracked AND untracked-not-ignored copy paths" >&2
    exit 2
    ;;
esac

[[ ${#files[@]} -eq 0 ]] && exit 0

# ── Scan ───────────────────────────────────────────────────────────────
findings=0

# Remove the parts of a line that are NOT reader-facing copy, leaving the prose
# the rule set is entitled to judge. Result in $STRIPPED (an out-variable, not
# stdout: a command substitution here forks a subshell per line, which is the
# cost this checker was just rewritten to avoid).
#
#   `inline spans`  identifiers — a skill name, flag or path. `systems-leverage`
#                   is a shipped artifact; renaming one to satisfy a prose rule
#                   is the tail wagging the dog. Fenced blocks are skipped
#                   wholesale for the same reason; this closes it at span scope.
#   ](target)       an address, not copy. Link TEXT is kept — that is what the
#                   reader actually reads, so it stays subject to every rule.
STRIPPED=""
strip_noncopy() {
  local s="$1"
  s="${s//\`*([^\`])\`/}"
  s="${s//\]\(*([^)])\)/]}"
  STRIPPED="$s"
}

scan_file() {
  local f="$1" in_fence=0 lineno=0 line
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    # skip fenced code blocks — code and quoted commands aren't copy
    if [[ "$line" =~ ^\`\`\` ]]; then in_fence=$((1 - in_fence)); continue; fi
    [[ $in_fence -eq 1 ]] && continue
    strip_noncopy "$line"; line="$STRIPPED"
    # Matching uses bash's builtin `=~` (ERE, same dialect as `grep -E`) and
    # BASH_REMATCH for the excerpt. The previous form spawned up to twelve
    # `printf | grep` subprocesses PER LINE, which cost 111s on this repo's
    # own README alone — a checker that slow gets skipped, and a skipped gate
    # enforces nothing. Builtin matching is subprocess-free.
    # `if/then/fi`, never `[[ ]] && { }`: under `set -e` a trailing `&&` list
    # whose test is false makes the loop, and therefore scan_file, return
    # non-zero, which aborted the script before it could print its summary or
    # exit 0. A clean file reported failure.
    if [[ "$line" == *"$EM_DASH_RE"* ]]; then
      echo "$f:$lineno: EM_DASH: house rule is zero em dashes in copy (redaction §14)"
      findings=$((findings + 1))
    fi
    if [[ "$line" =~ $BANNED_RE ]]; then
      echo "$f:$lineno: BANNED_WORD: ${BASH_REMATCH[2]} (redaction §7)"
      findings=$((findings + 1))
    fi
    if [[ "$line" =~ $WEASEL_RE ]]; then
      echo "$f:$lineno: WEASEL: ${BASH_REMATCH[0]} — name the source or cut (redaction §5/§23)"
      findings=$((findings + 1))
    fi
    if [[ "$line" =~ $CONTRAST_RE ]]; then
      echo "$f:$lineno: CONTRAST: ${BASH_REMATCH[0]:0:60} (redaction §9/§35)"
      findings=$((findings + 1))
    fi
    if [[ "$line" =~ $SETUP_RE ]]; then
      echo "$f:$lineno: SETUP: ${BASH_REMATCH[0]} (redaction §27-31)"
      findings=$((findings + 1))
    fi
    if [[ "$line" =~ $PUFF_RE ]]; then
      echo "$f:$lineno: PUFFERY: ${BASH_REMATCH[0]} (redaction §1/§4/§8/§20-22)"
      findings=$((findings + 1))
    fi
  done < "$f"
}

for f in "${files[@]}"; do scan_file "$f"; done

if [[ $findings -gt 0 ]]; then
  echo "redaction: $findings candidate pattern(s) in reader-facing copy. Authoritative inventory: skills/writing/redaction.md"
  if [[ "$ZETETIC_PROFILE" == "strict" ]]; then
    exit 1
  fi
fi
exit 0
