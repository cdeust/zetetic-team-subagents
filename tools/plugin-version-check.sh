#!/usr/bin/env bash
# plugin-version-check.sh — Is the plugin you are running the one that was published?
#
# Usage:
#   tools/plugin-version-check.sh                # three-value staleness check (session start)
#   tools/plugin-version-check.sh --version      # print the running plugin's version, nothing else
#   tools/plugin-version-check.sh --rules-version# print rules/coding-standards.md's version
#   tools/plugin-version-check.sh --json         # machine-readable result
#
# WHY THREE VALUES, NOT TWO (issue #52, and the incident that opened it).
# On 2026-07-24 the installed plugin ran v2.29.0 while the repo had released
# v2.34.0 — six releases, including §15, the redaction gates and the Fable
# loops, reached ZERO installs. No user action could have fixed it: the version
# is PINNED in a *different* repository's marketplace manifest (cdeust/Cortex's
# .claude-plugin/marketplace.json), and nothing bumped it. A check that compares
# only installed-vs-pin reports "up to date" against a stale pin — a false
# compliance statement, which for a rules-enforcement plugin is worse than no
# check at all: agents enforce a superseded standard AND certify the result.
#
# So this compares three values and names two distinct defects with different
# owners and different fixes:
#
#   installed < pin   INSTALL_LAG  the user has not updated          → user
#   pin < released    PIN_LAG      the release was never delivered   → the
#                                  marketplace-owning repo (named in the output)
#
# Counterpart gate: cdeust/Cortex#179 makes a stale pin a red CI run at the
# publishing end. This is the runtime end — the two together close the loop.
#
# Exit codes: 0 current OR degraded (see below), 1 lag detected, 2 usage error.
#
# FAIL-OPEN (issue #52 criterion 3). No network, no jq, no release metadata, an
# unreadable manifest, or a malformed version degrades to a single NOTICE line
# and exit 0 (ref: issue #52 criterion 3) — never a broken session, never a
# hang, never a false "you are
# stale". A boot-time check that can fail a session is a check that gets
# disabled, and then the six-release gap recurs with the check nominally in
# place. Every network call is time-boxed.
#
# Test injection points (all optional; used by tools/tests/plugin-version-check):
#   ZTS_PLUGIN_ROOT        override the plugin root being inspected
#   ZTS_CLAUDE_DIR         override ~/.claude (settings + marketplaces)
#   ZTS_LATEST_TAG_CMD     override the release probe; echo a tag or exit non-zero
#   ZTS_RULES_CHANGED_CMD  override the rules-diff probe; echo "yes" or "no"
set -uo pipefail

# source: GitHub REST p99 is far below this; a boot-time check must never hang
# a session (criterion 3), so the budget is a session-start budget, not an API one.
readonly API_TIMEOUT_S=5

# ── Resolution ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${ZTS_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}}"
CLAUDE_DIR="${ZTS_CLAUDE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}"

NOTICES=()
notice() { NOTICES+=("$1"); }

# Read a JSON value with jq; empty string when jq is absent, the file is
# unreadable, or the path is missing. Never fatal — callers treat "" as
# undeterminable and degrade (criterion 3).
json_read() {
  local file="$1" filter="$2"
  [[ -r "$file" ]] || return 0
  command -v jq >/dev/null 2>&1 || return 0
  jq -r "$filter // empty" "$file" 2>/dev/null || true
}

# Numeric semver compare, dot-separated. Echoes -1, 0 or 1 for a<b, a==b, a>b.
# Pure bash: `sort -V` is GNU-only and this must work on stock macOS.
# Non-numeric or malformed input echoes "x" — the caller degrades rather than
# guessing an ordering (criterion 6: malformed metadata is an arm, not a crash).
semver_cmp() {
  local a="${1#v}" b="${2#v}"
  [[ "$a" =~ ^[0-9]+(\.[0-9]+)*$ && "$b" =~ ^[0-9]+(\.[0-9]+)*$ ]] || { echo "x"; return 0; }
  local -a A B; IFS='.' read -ra A <<<"$a"; IFS='.' read -ra B <<<"$b"
  local i len=$(( ${#A[@]} > ${#B[@]} ? ${#A[@]} : ${#B[@]} ))
  for (( i = 0; i < len; i++ )); do
    local x="${A[i]:-0}" y="${B[i]:-0}"
    (( x > y )) && { echo 1; return 0; }
    (( x < y )) && { echo -1; return 0; }
  done
  echo 0
}

# ── The three values ───────────────────────────────────────────────────

# Installed: the version of the plugin this process is actually running under.
# Also satisfies criterion 1 — every agent/hook run can name its own version.
installed_version() { json_read "${PLUGIN_ROOT}/.claude-plugin/plugin.json" '.version'; }
plugin_name()       { json_read "${PLUGIN_ROOT}/.claude-plugin/plugin.json" '.name'; }

# Which marketplace actually serves this plugin. settings.json `enabledPlugins`
# is the authority — NOT the marketplace whose name resembles the plugin's. The
# incident hid here: zetetic-team-subagents is served by `cortex-plugins` (a
# clone of cdeust/Cortex), while an unused `zetetic-marketplace` clone sat
# alongside it, and updating that one changed nothing.
enabled_marketplace() {
  local name="$1" settings="${CLAUDE_DIR}/settings.json"
  json_read "$settings" \
    ".enabledPlugins | keys[] | select(startswith(\"${name}@\"))" | head -1 | sed "s/^${name}@//"
}

marketplace_manifest() { echo "${CLAUDE_DIR}/plugins/marketplaces/$1/.claude-plugin/marketplace.json"; }

pinned_version() {
  json_read "$(marketplace_manifest "$1")" \
    ".plugins[] | select(.name == \"$2\") | .version"
}

# The repo that OWNS the pin — where a PIN_LAG must be fixed. Read from the
# marketplace clone's git remote, so the message names a real target instead of
# telling the user to fix something they do not control.
#
# NOT the same repo as the plugin's own (see plugin_source_repo). That is the
# whole shape of this defect class: cortex-plugins is a clone of cdeust/Cortex,
# but it serves cdeust/zetetic-team-subagents. Querying the pin owner for the
# plugin's releases returns Cortex's version (4.16.0 vs 2.34.0) and every
# comparison downstream is nonsense.
pin_owner_repo() {
  local dir="${CLAUDE_DIR}/plugins/marketplaces/$1"
  git -C "$dir" remote get-url origin 2>/dev/null \
    | sed -E 's#(git@github.com[:/]|https://github.com/)##; s#\.git$##'
}

# The repo that PUBLISHES this plugin — where its releases live, and the only
# correct target for the latest-release probe. Prefers the marketplace entry's
# declared source (authoritative for how the install resolves), falling back to
# the plugin's own manifest.
plugin_source_repo() {
  local mkt="$1" name="$2" repo=""
  [[ -n "$mkt" ]] && repo="$(json_read "$(marketplace_manifest "$mkt")" \
    ".plugins[] | select(.name == \"${name}\") | .source.repo")"
  [[ -n "$repo" ]] && { echo "$repo"; return 0; }
  json_read "${PLUGIN_ROOT}/.claude-plugin/plugin.json" '.repository' \
    | sed -E 's#(git@github.com[:/]|https://github.com/)##; s#\.git$##'
}

# Latest published release. Fail-open: any failure returns empty and the caller
# emits a NOTICE rather than a verdict.
latest_release_tag() {
  local repo="$1"
  if [[ -n "${ZTS_LATEST_TAG_CMD:-}" ]]; then
    eval "${ZTS_LATEST_TAG_CMD}" 2>/dev/null || true
    return 0
  fi
  command -v curl >/dev/null 2>&1 || return 0
  curl -fsS --max-time "$API_TIMEOUT_S" \
    -H "Accept: application/vnd.github+json" \
    ${GITHUB_TOKEN:+-H "Authorization: Bearer ${GITHUB_TOKEN}"} \
    "https://api.github.com/repos/${repo}/releases/latest" 2>/dev/null \
    | { command -v jq >/dev/null 2>&1 && jq -r '.tag_name // empty' 2>/dev/null || true; }
}

# Did the withheld gap cross a change to the rules file? That is the case that
# matters (criterion 4): a docs-only bump is not worth interrupting a session
# for, a rules change means agents are certifying against a superseded standard.
# Prefers the local clone (works offline); silent when it cannot be determined.
rules_changed_between() {
  local from="$1" to="$2"
  if [[ -n "${ZTS_RULES_CHANGED_CMD:-}" ]]; then
    eval "${ZTS_RULES_CHANGED_CMD}" 2>/dev/null || true
    return 0
  fi
  git -C "$PLUGIN_ROOT" rev-parse --git-dir >/dev/null 2>&1 || return 0
  local range="v${from#v}..v${to#v}"
  git -C "$PLUGIN_ROOT" log --oneline "$range" -- rules/coding-standards.md 2>/dev/null \
    | grep -q . && echo yes || echo no
}

# ── Report ─────────────────────────────────────────────────────────────

emit_notices() {
  local n
  for n in "${NOTICES[@]:-}"; do [[ -n "$n" ]] && echo "NOTICE: $n"; done
}

# Count releases between two versions, when the local clone can tell us.
# Echoes empty when undeterminable — the message then omits the count rather
# than inventing one (§8).
releases_between() {
  local from="$1" to="$2"
  git -C "$PLUGIN_ROOT" rev-parse --git-dir >/dev/null 2>&1 || return 0
  git -C "$PLUGIN_ROOT" tag --sort=v:refname 2>/dev/null \
    | awk -v a="v${from#v}" -v b="v${to#v}" '$0==a{f=1;next} f&&$0==b{print c;exit} f{c++}'
}

report_pin_lag() {
  local pin="$1" latest="$2" mkt="$3" owner="$4" from_for_rules="$5"
  local count; count="$(releases_between "$pin" "$latest")"
  local phrase="releases were never delivered"
  [[ -n "$count" ]] && phrase="$((count + 1)) releases were never delivered"
  echo "PIN_LAG: marketplace '${mkt}' pins ${pin} but ${latest} is released — ${phrase}."
  if [[ -n "$owner" ]]; then
    echo "  Owner: ${owner} (.claude-plugin/marketplace.json). Updating your install cannot fix this."
  else
    echo "  Owner: the repo that publishes marketplace '${mkt}'. Updating your install cannot fix this."
  fi
  [[ "$(rules_changed_between "$from_for_rules" "$latest")" == "yes" ]] && \
    echo "  RULES CHANGED in that gap (rules/coding-standards.md) — agents are enforcing a superseded standard."
  return 0
}

usage() { echo "usage: plugin-version-check.sh [--version|--rules-version|--json]" >&2; exit 2; }

# criterion 5: the rules version a compliance report was evaluated against.
emit_rules_version() {
  sed -n 's/^version:[[:space:]]*//p' \
    "${PLUGIN_ROOT}/rules/coding-standards.md" 2>/dev/null | head -1
}

# installed vs pin — the arm the user can act on. Echoes the finding; returns 1
# when stale so the caller can accumulate status without parsing output.
check_install_lag() {
  local installed="$1" pin="$2" mkt="$3" name="$4"
  if [[ -z "$pin" ]]; then
    notice "marketplace pin undeterminable for '${name}' — install-vs-pin not checked"
    return 0
  fi
  case "$(semver_cmp "$installed" "$pin")" in
    -1) echo "INSTALL_LAG: installed ${installed} but marketplace '${mkt}' pins ${pin} — run /plugin to update."
        return 1 ;;
    x)  notice "version compare skipped: unparseable version (installed='${installed}' pin='${pin}')" ;;
  esac
  return 0
}

# pin vs released — the arm the user CANNOT act on (criterion 9). Distinct
# owner, distinct fix; conflating the two is the false-compliance defect.
check_pin_lag() {
  local pin="$1" latest="$2" mkt="$3" owner="$4"
  if [[ -z "$latest" ]]; then
    notice "latest release unavailable (offline, rate-limited, or no published release) — pin lag not checked"
    return 0
  fi
  [[ -n "$pin" ]] || return 0
  case "$(semver_cmp "$pin" "$latest")" in
    -1) report_pin_lag "$pin" "${latest#v}" "$mkt" "$owner" "$pin"; return 1 ;;
    x)  notice "release compare skipped: unparseable release tag '${latest}'" ;;
  esac
  return 0
}

# Resolve marketplace, pin, pin-owner and latest release into the caller's
# named variables. Split out so main() stays a readable orchestration (§4.2).
resolve_context() {
  local name="$1"
  MKT="$(enabled_marketplace "$name")"
  PIN=""; OWNER=""; LATEST=""
  if [[ -n "$MKT" ]]; then
    PIN="$(pinned_version "$MKT" "$name")"
    OWNER="$(pin_owner_repo "$MKT")"
  fi
  # Releases come from the PLUGIN's repo, never the marketplace owner's.
  local source_repo; source_repo="$(plugin_source_repo "$MKT" "$name")"
  if [[ -n "$source_repo" ]]; then
    LATEST="$(latest_release_tag "$source_repo")"
  else
    notice "plugin source repo undeterminable — pin lag not checked"
  fi
}

main() {
  local mode="check"
  case "${1:-}" in
    "") ;;
    --version)       mode="version" ;;
    --rules-version) mode="rules-version" ;;
    --json)          mode="json" ;;
    *) usage ;;
  esac

  [[ "$mode" == "rules-version" ]] && { emit_rules_version; return 0; }

  local name installed
  name="$(plugin_name)"; installed="$(installed_version)"
  [[ "$mode" == "version" ]] && { echo "$installed"; return 0; }

  if [[ -z "$installed" || -z "$name" ]]; then
    notice "plugin version undeterminable (${PLUGIN_ROOT}/.claude-plugin/plugin.json unreadable or jq missing)"
    emit_notices; return 0
  fi

  resolve_context "$name"
  local status=0
  check_install_lag "$installed" "$PIN" "$MKT" "$name" || status=1
  check_pin_lag "$PIN" "$LATEST" "$MKT" "$OWNER" || status=1

  if [[ "$mode" == "json" ]]; then
    printf '{"plugin":"%s","installed":"%s","marketplace":"%s","pinned":"%s","latest":"%s","status":%d}\n' \
      "$name" "$installed" "$MKT" "$PIN" "${LATEST#v}" "$status"
  fi
  emit_notices
  return "$status"
}

main "$@"
