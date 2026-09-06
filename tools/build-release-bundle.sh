#!/usr/bin/env bash
# build-release-bundle.sh — assemble the attestable release bundle (issue #53).
#
# This plugin ships NO compiled binary. The full host integration includes
# source that executes in the user's session: hooks/ run on lifecycle events,
# tools/*.sh run in pre-commit gates, and agents/ define assistant permissions.
# The isolated portable package is static skill content. There is no sandbox
# between a tampered executable and the machine, so the honest unit of
# provenance is "the exact set of source files a release delivers", captured as a
# deterministic tarball plus two side artifacts:
#
#   zetetic-team-subagents.tar.gz         the bundle (attested + checksummed)
#   zetetic-team-subagents.tar.gz.sha256  its checksum
#   EXECUTABLE-MANIFEST.sha256            every hooks/* and tools/*.sh|*.py that
#                                         will RUN on a user's machine, hashed —
#                                         so a user granting session-execution
#                                         rights can enumerate exactly what they
#                                         granted and diff it against last release
#   zetetic-team-subagents.cdx.json       CycloneDX SBOM of the bundle contents,
#                                         including vendored third-party skill
#                                         material (external prior art cited by
#                                         the redaction skill, per §8)
#
# Usage: tools/build-release-bundle.sh [output-dir]   (default: dist/)
# Exit: 0 on success, non-zero on any failure (set -e).
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"
OUT_DIR="${1:-dist}"
BUNDLE_NAME="zetetic-team-subagents"

# The shipped surface: definition + session-executing content + the configs and
# static skills marketplace installs consume. Deliberately excludes tests/,
# docs/, enterprise/ and dev scaffolding. Keeping those out makes the executable
# manifest below the whole answer to "what runs" while the SBOM inventories the
# complete delivered payload.
BUNDLE_PATHS=(
  agents hooks tools rules skills commands
  .claude-plugin/plugin.json .mcp.json
  .agents/plugins/marketplace.json plugins/zetetic-reasoning plugins/zetetic-design
  README.md LICENSE PRIVACY.md SECURITY.md CHANGELOG.md
)

mkdir -p "$OUT_DIR"

# --- deterministic tarball -------------------------------------------------
# Reproducibility first: an attestation over a non-deterministic archive proves
# little. GNU tar (the ubuntu release runner) supports the flags that strip
# mtime/owner/order nondeterminism; on a runner without them the archive is
# still correct, just not byte-reproducible.
tar_args=(--create --gzip)
if tar --version 2>/dev/null | grep -qi "gnu tar"; then
  tar_args+=(--sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner)
fi
tar "${tar_args[@]}" -f "$OUT_DIR/$BUNDLE_NAME.tar.gz" "${BUNDLE_PATHS[@]}"

# --- executable-content manifest (criterion 4) -----------------------------
# Every hook and every shell/python tool a session will execute, hashed. Sorted
# for a stable, diffable manifest.
{
  find hooks -type f \( -name "*.sh" -o -name "*.py" \) 2>/dev/null
  find tools -type f \( -name "*.sh" -o -name "*.py" \) 2>/dev/null
} | LC_ALL=C sort | while IFS= read -r f; do
  sha256sum "$f"
done > "$OUT_DIR/EXECUTABLE-MANIFEST.sha256"
echo "Executable files manifested: $(wc -l < "$OUT_DIR/EXECUTABLE-MANIFEST.sha256")"

# --- SBOM (criterion 3) ----------------------------------------------------
python3 tools/gen-bundle-sbom.py \
  --version "$(jq -r '.version' .claude-plugin/plugin.json)" \
  --output "$OUT_DIR/$BUNDLE_NAME.cdx.json" \
  "${BUNDLE_PATHS[@]}"

# --- checksums for every asset ---------------------------------------------
( cd "$OUT_DIR" && for f in "$BUNDLE_NAME.tar.gz" "$BUNDLE_NAME.cdx.json" EXECUTABLE-MANIFEST.sha256; do
    sha256sum "$f" > "$f.sha256"
  done )

echo "Release bundle assembled in $OUT_DIR/:"
ls -la "$OUT_DIR"
