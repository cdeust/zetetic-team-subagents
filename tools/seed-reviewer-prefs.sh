#!/usr/bin/env bash
#
# seed-reviewer-prefs.sh — bootstrap a team lead's reviewer-prefs (CAP-2) from the
# EVIDENCE of how they already work: their review comments and their merged PRs.
#
# Why this exists: a lead need not hand-author their review preferences from a blank
# file. The richest, most honest signal of "how this lead reviews" is what they have
# actually flagged in past reviews and how their own merged code is shaped. This tool
# gathers that evidence via `gh` and emits a draft for the scope
# /memories/reviewer-prefs/<lead>/.
#
# Zetetic discipline (rules/coding-standards.md §8 source discipline, §9 no faked
# judgment):
#   - This tool does NOT invent abstract "preferences". Inventing a preference the
#     lead did not express would be a guess, not a pref. It emits the raw evidence
#     (verbatim review comments + merged-PR titles), each with provenance (PR number,
#     file path, URL). Abstracting that evidence into stated preferences is a JUDGMENT
#     step left to the orchestrator/curator reading the draft — it is not faked here.
#   - Every emitted item is marked `status: inferred`. A reviewed agent applies an
#     inferred pref as advisory (COMMENT-level) only; it becomes binding solely after
#     the lead confirms it (status: confirmed). See memory/scope-coverage.md.
#   - Write access honours the scope ACL: the draft is written under MEMORY_AGENT_ID
#     of an OWNER (orchestrator/_user) — not a reviewed agent. Default is dry-run to
#     stdout so the evidence is inspectable before anything is persisted.
#
#   usage: seed-reviewer-prefs.sh <lead-login> [--repo OWNER/REPO] [--limit N]
#                                 [--write] [--owner-id ID]
#     <lead-login>  the lead's GitHub login (author of the reviews/PRs to mine).
#     --repo        OWNER/REPO to mine. Default: the current repo (gh infers it).
#     --limit       max PRs/comments to scan per source. Default 50.
#     --write       persist the draft to /memories/reviewer-prefs/<lead>/inferred.md
#                   via tools/memory-tool.sh (default: print to stdout, persist nothing).
#     --owner-id    MEMORY_AGENT_ID used for the write — must be a scope owner.
#                   Default: orchestrator. (_user is the other valid owner.)
#
# Exit codes (deterministic):
#   0  draft emitted (and written, if --write)
#   2  usage error
#   3  gh CLI missing or not authenticated
#   4  no evidence found for this lead in this repo (nothing to seed)
#   5  --write reached memory-tool.sh but the write was rejected (ACL or tool error)
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "seed-reviewer-prefs: $1" >&2; exit "${2:-2}"; }

require_gh() {
  command -v gh >/dev/null 2>&1 || die "the GitHub CLI 'gh' is not installed (https://cli.github.com)" 3
  gh auth status >/dev/null 2>&1 || die "'gh' is not authenticated — run 'gh auth login'" 3
}

# parse_args sets globals: LEAD, REPO, LIMIT, WRITE, OWNER_ID.
parse_args() {
  [ "$#" -ge 1 ] || die "missing <lead-login>. See header for usage." 2
  LEAD="$1"; shift
  # GitHub logins are [A-Za-z0-9-] (<=39 chars). Validating here both rejects bad
  # input and makes it safe to interpolate LEAD into the jq filter below.
  case "$LEAD" in (''|*[!A-Za-z0-9-]*) die "invalid GitHub login '$LEAD'" 2 ;; esac
  REPO=""; LIMIT=50; WRITE=0; OWNER_ID="orchestrator"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo)     REPO="${2:?--repo needs OWNER/REPO}"; shift 2 ;;
      --limit)    LIMIT="${2:?--limit needs a number}"; shift 2 ;;
      --write)    WRITE=1; shift ;;
      --owner-id) OWNER_ID="${2:?--owner-id needs an id}"; shift 2 ;;
      *)          die "unknown argument: $1" 2 ;;
    esac
  done
  case "$LIMIT" in (''|*[!0-9]*) die "--limit must be a positive integer, got '$LIMIT'" 2 ;; esac
  [ "$LIMIT" -gt 0 ] || die "--limit must be a positive integer (>0), got '$LIMIT'" 2
  # REPO is interpolated into a gh api URL path; validate symmetrically with LEAD.
  [ -z "$REPO" ] || case "$REPO" in (*/*) : ;; (*) die "--repo must be OWNER/REPO, got '$REPO'" 2 ;; esac
  [ -z "$REPO" ] || case "$REPO" in (*[!A-Za-z0-9_./-]*) die "--repo has invalid characters: '$REPO'" 2 ;; esac
  [ "$OWNER_ID" = "orchestrator" ] || [ "$OWNER_ID" = "_user" ] \
    || die "--owner-id must be a reviewer-prefs owner (orchestrator|_user), got '$OWNER_ID'" 2
}

# set_repo_args populates the REPO_ARGS array with the gh --repo flag, or empties it
# (gh then infers the current repo). An array passes OWNER/REPO as one argument without
# depending on IFS word-splitting at the call site.
set_repo_args() { REPO_ARGS=(); if [ -n "$REPO" ]; then REPO_ARGS=(--repo "$REPO"); fi; }

# fetch_merged_prs — merged PRs authored by the lead (how their own code is shaped).
# Emits one markdown bullet per PR, or nothing. Does not abort the run on gh error.
# `gh pr list --jq` applies gh's bundled jq to the --json output (no external jq).
fetch_merged_prs() {
  gh pr list ${REPO_ARGS[@]+"${REPO_ARGS[@]}"} --author "$LEAD" --state merged --limit "$LIMIT" \
    --json number,title,url \
    --jq '.[] | "- PR #\(.number): \(.title)\n  \(.url)"' 2>/dev/null || return 0
}

# fetch_review_comments — code-review comments authored BY the lead across the repo's
# PRs (what they actually flag). The REST endpoint lists most-recent first; `gh api
# --jq` filters the response to the lead and quotes each verbatim with file + PR
# provenance. LEAD is validated to [A-Za-z0-9-] so interpolation into jq is safe.
fetch_review_comments() {
  local path="repos/{owner}/{repo}/pulls/comments"
  [ -n "$REPO" ] && path="repos/$REPO/pulls/comments"
  gh api --paginate -X GET "$path" -f per_page=100 \
    --jq ".[] | select(.user.login == \"$LEAD\")
          | \"- on \`\(.path)\` (\(.html_url)):\n  > \" + (.body | gsub(\"\n\"; \"\n  > \"))" \
    2>/dev/null | head -n $((LIMIT * 6)) || return 0
}

# emit_draft writes the full inferred-prefs markdown to stdout.
emit_draft() {
  local prs="$1" comments="$2" today="$3"
  cat <<EOF
---
description: "Inferred review preferences for lead '$LEAD' — seeded from PR history, awaiting confirmation"
status: inferred
lead: "$LEAD"
seeded_on: "$today"
source: "seed-reviewer-prefs.sh (gh review comments + merged PRs)"
---

# Inferred review preferences — $LEAD

**status: inferred.** This file was bootstrapped from evidence of how $LEAD has
reviewed and shipped code. It is NOT yet a set of confirmed preferences: a reviewed
agent treats every item below as a COMMENT-level suggestion, never a blocking rule,
until the lead (or the orchestrator/curator on the lead's behalf) abstracts it into
confirmed preferences and sets \`status: confirmed\`. A preference never overrides a
\`~/.claude/reference/coding-standards.md\` blocking rule.

## How to confirm
Read the evidence below, abstract the recurring patterns into stated preferences
(e.g. "prefers Result types over exceptions", "wants one assertion per test"), keep
the provenance link on each, then set the frontmatter \`status: confirmed\`. Discard
anything that contradicts a hard rule.

## Evidence — review comments authored by $LEAD
${comments:-_(none found in scanned range)_}

## Evidence — merged PRs authored by $LEAD
${prs:-_(none found in scanned range)_}
EOF
}

main() {
  parse_args "$@"
  require_gh
  set_repo_args
  local today; today=$(date -u +%Y-%m-%d)
  local prs comments draft
  prs=$(fetch_merged_prs)
  comments=$(fetch_review_comments)
  if [ -z "$prs" ] && [ -z "$comments" ]; then
    die "no review comments or merged PRs found for '$LEAD'${REPO:+ in $REPO} — nothing to seed" 4
  fi
  draft=$(emit_draft "$prs" "$comments" "$today")

  if [ "$WRITE" -eq 1 ]; then
    MEMORY_AGENT_ID="$OWNER_ID" bash "$SELF_DIR/memory-tool.sh" create \
      "/memories/reviewer-prefs/$LEAD/inferred.md" "$draft" \
      || die "write failed — confirm '$OWNER_ID' owns the reviewer-prefs scope and the PR adding it is merged" 5
    echo "seed-reviewer-prefs: wrote /memories/reviewer-prefs/$LEAD/inferred.md (status: inferred) as '$OWNER_ID'" >&2
  else
    printf '%s\n' "$draft"
    echo "seed-reviewer-prefs: dry-run (no write). Re-run with --write to persist as an owner." >&2
  fi
}

main "$@"
