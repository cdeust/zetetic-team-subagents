#!/usr/bin/env bash
# Run the Codex plugin + skill validators from immutable OpenAI source commits.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: run-codex-validators.sh <plugin-root> <skill> [skill...]" >&2
  exit 2
fi

plugin_root="$1"
shift
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

# plugin validator: openai/codex, Apache-2.0.
# skill validator: openai/skills system skill snapshot.
# Each URL is content-addressed by the most recent commit that changed the
# validator when this gate was introduced (verified 2026-08-03).
plugin_commit="2c351cb8646054427e0ea81a484233114b1234f7"
skill_commit="e8acbcb5f86cef1e04b96eed7557148b719c5f6b"
plugin_api="repos/openai/codex/contents/codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py?ref=${plugin_commit}"
skill_api="repos/openai/skills/contents/skills/.system/skill-creator/scripts/quick_validate.py?ref=${skill_commit}"

fetch() {
  local api="$1" output="$2"
  if env -u GH_TOKEN -u GITHUB_TOKEN gh auth status >/dev/null 2>&1; then
    env -u GH_TOKEN -u GITHUB_TOKEN gh api \
      -H 'Accept: application/vnd.github.raw+json' "$api" >"$output"
  elif gh auth status >/dev/null 2>&1; then
    gh api -H 'Accept: application/vnd.github.raw+json' "$api" >"$output"
  else
    echo "GitHub CLI authentication is required to fetch pinned validators" >&2
    exit 1
  fi
}

fetch "$plugin_api" "$scratch/validate_plugin.py"
fetch "$skill_api" "$scratch/quick_validate.py"

python3 "$scratch/validate_plugin.py" "$plugin_root"
for skill in "$@"; do
  python3 "$scratch/quick_validate.py" "$skill"
done
