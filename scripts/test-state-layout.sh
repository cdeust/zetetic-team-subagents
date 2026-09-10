#!/usr/bin/env bash
# test-state-layout.sh — Regression test for issue #136: every state file the
# plugin owns lives under ~/.claude/zetetic/, a flat install is moved there
# once, and the tools write their state in the new place by default.
#
# Measured 2026-09-10: setup.sh and the tools wrote .zetetic-manifest,
# .zetetic-manifest.json, .zetetic-version, zetetic-agent-models.json,
# worktree-sweep-audit.log, dev-symlink.map and dev-symlink.versions flat
# into ~/.claude, next to the GOA Phase 0 workspaces, and the root held 324
# entries. Owner ruling: what a plugin leaves on disk is managed by the
# plugin and readable at a glance.
#
# Tests:
#   S1  A flat-layout fixture is migrated: every legacy root entry is gone,
#       every one of them is under zetetic/ with its content intact, and the
#       user-tuned override config is moved, not overwritten.
#   S2  Re-running the install is idempotent: nothing at the root, the
#       override config untouched, exit 0.
#   S3  `configure` after the migration reports the existing config instead
#       of seeding a new one.
#   S4  A fresh install writes only ~/.claude/zetetic/ plus the staged trees.
#   S5  --dry-run on a flat fixture moves nothing and names what it would move.
#   S6  A sweep's audit log lands in ~/.claude/zetetic/ by default, and the
#       WORKTREE_AUDIT_LOG override still wins.
#   S7  The dev-symlink doctor's state file lands in ~/.claude/zetetic/ by
#       default, creating the directory when it is missing.
#   S8  The closing Layout report names the state directory and the trees.
#
# Every run uses a throwaway HOME and a throwaway copy of the plugin, so the
# real ~/.claude and the repo's own .claude-plugin/plugin.json are never touched.

set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; (( PASS_COUNT++ )) || true; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; (( FAIL_COUNT++ )) || true; }

# A private copy of the plugin: setup.sh re-syncs .claude-plugin/plugin.json
# from hooks/hooks.json on a real install, which must not dirty the repo.
PLUGIN="$TMP/plugin"
mkdir -p "$PLUGIN"
tar --exclude=.git --exclude=.claude -C "$REPO" -cf - . | tar -C "$PLUGIN" -xf -
SETUP="$PLUGIN/scripts/setup.sh"
MANAGER="$PLUGIN/tools/worktree-manager.sh"
DOCTOR="$PLUGIN/tools/dev-symlink-doctor.sh"
PLUGIN_VERSION="$(jq -r .version "$PLUGIN/.claude-plugin/plugin.json")"

LEGACY_NAMES=(.zetetic-manifest .zetetic-manifest.json .zetetic-version zetetic-agent-models.json
  worktree-sweep-audit.log dev-symlink.map dev-symlink.versions dev-symlink.map.bak-20260101 goa-phase0 goa-design)
NEW_NAMES=(manifest manifest.json version agent-models.json
  worktree-sweep-audit.log dev-symlink.map dev-symlink.versions dev-symlink.map.bak-20260101 goa-phase0 goa-design)

# Lays down the flat layout the owner's machine carried on 2026-09-10.
make_flat_home() {
  local home="$1" root="$1/.claude"
  mkdir -p "$root/goa-phase0/replays" "$root/goa-design"
  printf 'no-checksum  hooks/stale-from-old-install.sh\n' > "$root/.zetetic-manifest"
  mkdir -p "$root/hooks"; printf 'stale\n' > "$root/hooks/stale-from-old-install.sh"
  printf '{"version":"2.0.0","files":[]}\n' > "$root/.zetetic-manifest.json"
  printf '2.0.0\n' > "$root/.zetetic-version"
  printf '{"agents":{"engineer":{"model":"haiku","effort":"low"}},"marker":"user-tuned-S1"}\n' > "$root/zetetic-agent-models.json"
  printf '2026-09-10T00:00:00Z\trepo=x\tpath=y\tbranch=z\tremoved\n' > "$root/worktree-sweep-audit.log"
  printf '/cache/plug/1.0.0|/dev/plug|tree\n' > "$root/dev-symlink.map"
  printf '/cache/plug|1.0.0\n' > "$root/dev-symlink.versions"
  printf 'old map\n' > "$root/dev-symlink.map.bak-20260101"
  printf 'rubric\n' > "$root/goa-phase0/label-rubric.md"
  printf 'replay\n' > "$root/goa-phase0/replays/run.jsonl"
  printf 'design\n' > "$root/goa-design/GOA-DESIGN.md"
  echo "$home"
}

# Root entries of a HOME's ~/.claude that are neither the state dir nor a staged tree.
unexpected_root_entries() {
  local root="$1/.claude" e name out=""
  for e in "$root"/* "$root"/.[!.]*; do
    [[ -e "$e" ]] || continue
    name="$(basename "$e")"
    case "$name" in zetetic|agents|skills|commands|hooks|tools|reference) ;; *) out="$out $name" ;; esac
  done
  echo "$out"
}

# ── S1: flat fixture is migrated ────────────────────────────────────────────
echo "S1: flat-layout fixture is moved under ~/.claude/zetetic/ with content intact"
H1="$(make_flat_home "$TMP/home1")"
OUT1="$(HOME="$H1" bash "$SETUP" install 2>&1)" || { fail "install exited non-zero"; echo "$OUT1" | tail -20; }
left=""
for n in "${LEGACY_NAMES[@]}"; do [[ -e "$H1/.claude/$n" ]] && left="$left $n"; done
if [[ -z "$left" ]]; then pass "nothing of the flat layout left at the root"; else fail "still at the root:$left"; fi
missing=""
for n in "${NEW_NAMES[@]}"; do [[ -e "$H1/.claude/zetetic/$n" ]] || missing="$missing $n"; done
if [[ -z "$missing" ]]; then pass "every legacy entry is under zetetic/"; else fail "missing under zetetic/:$missing"; fi
if grep -q '"marker":"user-tuned-S1"' "$H1/.claude/zetetic/agent-models.json"; then
  pass "user-tuned agent-models.json moved, not overwritten"
else
  fail "agent-models.json content changed"
fi
if [[ "$(cat "$H1/.claude/zetetic/goa-phase0/replays/run.jsonl")" == "replay" && "$(cat "$H1/.claude/zetetic/goa-design/GOA-DESIGN.md")" == "design" ]]; then
  pass "GOA workspaces moved with their files"
else
  fail "GOA workspace content lost"
fi
if [[ "$(cat "$H1/.claude/zetetic/version")" == "$PLUGIN_VERSION" ]]; then pass "version recorded at zetetic/version"; else fail "zetetic/version is '$(cat "$H1/.claude/zetetic/version" 2>/dev/null)'"; fi
if grep -q '  hooks/session-start.sh$' "$H1/.claude/zetetic/manifest"; then pass "manifest written at zetetic/manifest"; else fail "zetetic/manifest lacks the installed files"; fi
if [[ ! -e "$H1/.claude/hooks/stale-from-old-install.sh" ]]; then pass "orphan from the legacy manifest removed (manifest was read from the new path)"; else fail "orphan survived: the legacy manifest was not read"; fi
if grep -q 'Upgrading: 2.0.0' <<<"$OUT1"; then pass "version check read the migrated version file"; else fail "version check did not see the migrated 2.0.0"; fi
if grep -q 'Moved zetetic-agent-models.json -> zetetic/agent-models.json' <<<"$OUT1"; then pass "migration is reported"; else fail "migration not reported"; fi

# ── S2: idempotent re-run ───────────────────────────────────────────────────
echo "S2: a second install run is a no-op for the state layout"
if HOME="$H1" bash "$SETUP" install >"$TMP/out2" 2>&1; then pass "re-run exits 0"; else fail "re-run failed"; tail -20 "$TMP/out2"; fi
if grep -q 'nothing flat at the root' "$TMP/out2"; then pass "re-run finds nothing to move"; else fail "re-run reported a move"; fi
if grep -q '"marker":"user-tuned-S1"' "$H1/.claude/zetetic/agent-models.json"; then pass "override config still untouched"; else fail "override config changed on re-run"; fi
if [[ -z "$(unexpected_root_entries "$H1")" ]]; then pass "root holds only zetetic/ and the staged trees"; else fail "unexpected at root:$(unexpected_root_entries "$H1")"; fi

# ── S3: configure keeps the migrated config ─────────────────────────────────
echo "S3: configure reports the existing (migrated) config instead of seeding"
OUT3="$(HOME="$H1" bash "$SETUP" configure 2>&1)" || fail "configure exited non-zero"
if grep -q 'Existing config: .*/.claude/zetetic/agent-models.json' <<<"$OUT3"; then pass "configure names zetetic/agent-models.json"; else fail "configure did not find the migrated config"; fi
if grep -q 'user-tuned-S1' <<<"$OUT3"; then pass "configure prints the user's content"; else fail "configure printed something else"; fi

# ── S4: fresh install writes only zetetic/ + staged trees ───────────────────
echo "S4: fresh install under an empty HOME writes only ~/.claude/zetetic/ and the staged trees"
H4="$TMP/home4"; mkdir -p "$H4/.claude"
if HOME="$H4" bash "$SETUP" install >"$TMP/out4" 2>&1; then pass "fresh install exits 0"; else fail "fresh install failed"; tail -20 "$TMP/out4"; fi
if [[ -z "$(unexpected_root_entries "$H4")" ]]; then pass "root holds only zetetic/ and the staged trees"; else fail "unexpected at root:$(unexpected_root_entries "$H4")"; fi
state_entries="$(ls -A "$H4/.claude/zetetic" | sort | tr '\n' ' ')"
if [[ "$state_entries" == "manifest version " ]]; then pass "zetetic/ holds exactly manifest and version"; else fail "zetetic/ holds: $state_entries"; fi
if [[ -f "$H4/.claude/hooks/session-start.sh" && -f "$H4/.claude/tools/worktree-manager.sh" ]]; then pass "staged trees populated"; else fail "staged trees missing"; fi

# ── S5: dry run moves nothing ───────────────────────────────────────────────
echo "S5: --dry-run on a flat fixture moves nothing and names what it would move"
H5="$(make_flat_home "$TMP/home5")"
OUT5="$(HOME="$H5" bash "$SETUP" install --dry-run 2>&1)" || fail "dry run exited non-zero"
if [[ -f "$H5/.claude/.zetetic-version" && ! -e "$H5/.claude/zetetic" ]]; then pass "nothing moved, zetetic/ not created"; else fail "dry run wrote to disk"; fi
if grep -q 'Would move .zetetic-version -> zetetic/version' <<<"$OUT5"; then pass "dry run names the pending move"; else fail "dry run did not name the move"; fi
if grep -q 'Upgrading: 2.0.0' <<<"$OUT5"; then pass "dry run still reads the recorded version"; else fail "dry run lost the recorded version"; fi

# ── S6: sweep audit log lands in zetetic/ ───────────────────────────────────
echo "S6: a sweep's audit log lands in ~/.claude/zetetic/ by default"
H6="$TMP/home6"; mkdir -p "$H6/.claude"
TARGET="$TMP/target"; mkdir -p "$TARGET"
git -C "$TARGET" init -q -b main
git -C "$TARGET" config user.email "test@example.invalid"
git -C "$TARGET" config user.name "State Layout Test"
git -C "$TARGET" commit -q --allow-empty -m init
git -C "$TARGET" update-ref refs/remotes/origin/main refs/heads/main
STALE="$TARGET/.claude/worktrees/s6"; mkdir -p "$TARGET/.claude/worktrees"
git -C "$TARGET" worktree add -q "$STALE" -b test/s6 origin/main
HOME="$H6" WORKTREE_GRACE_SECONDS=0 "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if grep -q 'branch=test/s6' "$H6/.claude/zetetic/worktree-sweep-audit.log" 2>/dev/null; then
  pass "audit line written to ~/.claude/zetetic/worktree-sweep-audit.log"
else
  fail "no audit line under zetetic/"
fi
if [[ ! -e "$H6/.claude/worktree-sweep-audit.log" ]]; then pass "nothing written at the root"; else fail "audit log still written at the root"; fi
git -C "$TARGET" worktree add -q "$TARGET/.claude/worktrees/s6b" -b test/s6b origin/main
HOME="$H6" WORKTREE_AUDIT_LOG="$TMP/override.log" WORKTREE_GRACE_SECONDS=0 "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if grep -q 'branch=test/s6b' "$TMP/override.log" 2>/dev/null; then pass "WORKTREE_AUDIT_LOG override still wins"; else fail "override ignored"; fi

# ── S7: doctor state file lands in zetetic/ ─────────────────────────────────
echo "S7: the dev-symlink doctor's versions file lands in ~/.claude/zetetic/ by default"
H7="$TMP/home7"; mkdir -p "$H7/.claude"
CACHE="$TMP/cache/mp/plug"; DEV="$TMP/dev-repo"
mkdir -p "$CACHE/1.0.0/scripts" "$DEV/scripts"
printf 'hook\n' > "$DEV/scripts/launcher.py"; printf 'hook\n' > "$CACHE/1.0.0/scripts/launcher.py"
printf '%s|%s|tree\n' "$CACHE/1.0.0" "$DEV" > "$TMP/map7"
HOME="$H7" DEV_SYMLINK_MAP="$TMP/map7" bash "$DOCTOR" >/dev/null 2>&1 || true
if grep -q "^$CACHE|1.0.0" "$H7/.claude/zetetic/dev-symlink.versions" 2>/dev/null; then
  pass "versions recorded at ~/.claude/zetetic/dev-symlink.versions (directory created)"
else
  fail "no versions file under zetetic/"
fi
if [[ ! -e "$H7/.claude/dev-symlink.versions" ]]; then pass "nothing written at the root"; else fail "versions file still written at the root"; fi
OUT7="$(HOME="$TMP/home7-nomap" bash "$DOCTOR" 2>&1 || true)"
if grep -q "no map file at $TMP/home7-nomap/.claude/zetetic/dev-symlink.map" <<<"$OUT7"; then pass "doctor looks for the map under zetetic/ by default"; else fail "doctor default map path is not under zetetic/: $OUT7"; fi
cp "$TMP/map7" "$H7/.claude/zetetic/dev-symlink.map"
# Exit 1 is the doctor's verdict on this unmounted fixture; what matters is that it read the map.
OUT7B="$(HOME="$H7" bash "$DOCTOR" 2>&1 || true)"
if grep -q 'plug/1.0.0' <<<"$OUT7B"; then pass "doctor reads zetetic/dev-symlink.map by default"; else fail "doctor did not read zetetic/dev-symlink.map: $OUT7B"; fi

# ── S8: closing layout report ───────────────────────────────────────────────
echo "S8: setup.sh ends with the layout report"
if grep -q 'Plugin state, ~/.claude/zetetic/:' "$TMP/out4" && grep -qE '^\s+manifest\s+[0-9]+ lines' "$TMP/out4"; then
  pass "state files listed with sizes"
else
  fail "layout report missing the state files"
fi
if grep -qE '[~]/.claude/hooks/ +[1-9][0-9]* files' "$TMP/out4"; then pass "staged trees listed with counts"; else fail "layout report missing the trees"; fi
if [[ "$(grep -n 'Layout' "$TMP/out4" | tail -1 | cut -d: -f1)" -gt "$(grep -n 'Next steps' "$TMP/out4" | cut -d: -f1)" ]]; then
  pass "layout is the last section printed"
else
  fail "layout printed before the next steps"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
[[ "$FAIL_COUNT" -eq 0 ]] || exit 1
