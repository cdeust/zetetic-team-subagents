#!/usr/bin/env bash
# Regression suite — dev-symlink-doctor.sh version-bridge mechanism.
#
# Root-cause incident (2026-07-14): a plugin auto-update replaces
# <plugin_dir>/<old_version> with <plugin_dir>/<new_version> and PURGES
# old_version. Any session already running captured
# CLAUDE_PLUGIN_ROOT=<...>/<old_version> at spawn; every hook under that
# root breaks with "No such file or directory" until the session restarts.
# The owner directive: do not block the purge, auto-bridge the old path to
# the current version instead. This suite proves:
#   1. a purged, previously-recorded version gets bridged to current.
#   2. a REAL directory at an old-version path is never overwritten.
#   3. a stale bridge (two updates happened) gets re-pointed, and the
#      intermediate version also gets bridged.
#   4. prune-bridges removes the symlink AND forgets the version so it is
#      not silently recreated on the next run.
#   5. pre-existing check/repair montage behavior is unchanged (OK/BROKEN/
#      repaired reporting, exit codes) — non-regression.
#
# Self-contained: builds throwaway fixtures in a tmpdir, overrides
# DEV_SYMLINK_MAP / DEV_SYMLINK_VERSIONS, never touches ~/.claude or any
# real plugin cache. Exit non-zero if any assertion fails.
set -uo pipefail   # NOT -e: some doctor invocations are expected to exit 1.
cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
DOCTOR="$REPO/tools/dev-symlink-doctor.sh"

PASS=0
FAIL=0
pass() { printf "  ok   %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL %s\n" "$1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run_doctor() {
  # Args: subcmd(""|--repair|prune-bridges) map_file versions_file
  local sub="$1" map="$2" versions="$3"
  DEV_SYMLINK_MAP="$map" DEV_SYMLINK_VERSIONS="$versions" bash "$DOCTOR" $sub
}

echo "dev-symlink-doctor version-bridge regression suite"

# =====================================================================
# Fixture setup: one plugin (plug) under a synthetic cache root, mounted
# tree-mode against a synthetic dev repo containing one hook file.
# =====================================================================
CACHE_ROOT="$TMP/plugins/cache/mp/plug"
DEV_REPO="$TMP/dev-repo"
MAP="$TMP/map"
VERSIONS="$TMP/versions"

mkdir -p "$CACHE_ROOT/4.14.0/scripts" "$DEV_REPO/scripts"
printf 'hook\n' > "$DEV_REPO/scripts/launcher.py"
printf 'hook\n' > "$CACHE_ROOT/4.14.0/scripts/launcher.py"
printf '%s|%s|tree\n' "$CACHE_ROOT/4.14.0" "$DEV_REPO" > "$MAP"

# =====================================================================
# 1. First run: no bridge yet (nothing purged), version recorded.
# =====================================================================
echo " 1. first run records the current version, creates no bridge:"
out="$(run_doctor "" "$MAP" "$VERSIONS")"
if grep -q 'BRIDGE' <<<"$out"; then
  fail "unexpected BRIDGE action on first run: $out"
else
  pass "no bridge action on first run"
fi
if [[ -f "$VERSIONS" ]] && grep -qF "$CACHE_ROOT|4.14.0" "$VERSIONS"; then
  pass "state file records 4.14.0 for plug"
else
  fail "state file missing 4.14.0 record: $(cat "$VERSIONS" 2>/dev/null)"
fi

# =====================================================================
# 2. Simulate the incident: purge 4.14.0, install 4.15.0, update map.
#    The doctor must create a symlink bridge 4.14.0 -> 4.15.0.
# =====================================================================
echo " 2. purge + new version -> bridge created, old hook path resolves:"
mkdir -p "$CACHE_ROOT/4.15.0/scripts"
printf 'hook\n' > "$CACHE_ROOT/4.15.0/scripts/launcher.py"
rm -rf "$CACHE_ROOT/4.14.0"
printf '%s|%s|tree\n' "$CACHE_ROOT/4.15.0" "$DEV_REPO" > "$MAP"

out="$(run_doctor "" "$MAP" "$VERSIONS")"
if grep -q "BRIDGE  created: $CACHE_ROOT/4.14.0 -> 4.15.0" <<<"$out"; then
  pass "bridge created for purged 4.14.0 -> 4.15.0"
else
  fail "expected bridge-created line, got: $out"
fi
if [[ -L "$CACHE_ROOT/4.14.0" ]] && [[ "$(readlink "$CACHE_ROOT/4.14.0")" == "$CACHE_ROOT/4.15.0" ]]; then
  pass "4.14.0 is now a symlink to 4.15.0"
else
  fail "4.14.0 is not the expected bridge symlink"
fi
if [[ -f "$CACHE_ROOT/4.14.0/scripts/launcher.py" ]]; then
  pass "old-path hook file resolves through the bridge (session stays live)"
else
  fail "old-path hook file does NOT resolve — bridge is broken"
fi

# =====================================================================
# 3. Never overwrite a real directory: manually recreate a REAL 4.14.0
#    dir with a marker file; even though the state file lists 4.14.0 as
#    historical, the doctor must leave it untouched.
# =====================================================================
echo " 3. a real directory at an old-version path is never overwritten:"
rm -f "$CACHE_ROOT/4.14.0"   # remove the bridge symlink from step 2
mkdir -p "$CACHE_ROOT/4.14.0"
printf 'real data\n' > "$CACHE_ROOT/4.14.0/marker.txt"
# Force the state file to still list 4.14.0 as historical (as it would be
# if a purge-then-recreate happened between two doctor runs).
printf '%s|4.14.0,4.15.0\n' "$CACHE_ROOT" > "$VERSIONS"

out="$(run_doctor "" "$MAP" "$VERSIONS")"
if [[ -L "$CACHE_ROOT/4.14.0" ]]; then
  fail "real 4.14.0 directory was replaced with a symlink"
else
  pass "real 4.14.0 directory left untouched (not a symlink)"
fi
if [[ -f "$CACHE_ROOT/4.14.0/marker.txt" ]] && grep -q 'real data' "$CACHE_ROOT/4.14.0/marker.txt"; then
  pass "real 4.14.0 directory contents intact"
else
  fail "real 4.14.0 directory contents lost or modified"
fi
if grep -q 'BRIDGE' <<<"$out"; then
  fail "unexpected BRIDGE action against a real directory: $out"
else
  pass "no bridge action taken against the real directory"
fi
# Restore the pre-scenario-3 state (bridge present) for the next scenarios.
rm -rf "$CACHE_ROOT/4.14.0"
ln -s "$CACHE_ROOT/4.15.0" "$CACHE_ROOT/4.14.0"

# =====================================================================
# 4. Repoint on a second update: 4.15.0 gets purged and replaced by
#    4.16.0. The existing 4.14.0 bridge (currently -> 4.15.0) must be
#    re-pointed at 4.16.0, AND a new bridge for 4.15.0 -> 4.16.0 must
#    appear.
# =====================================================================
echo " 4. second update repoints the stale bridge and bridges the intermediate version:"
mkdir -p "$CACHE_ROOT/4.16.0/scripts"
printf 'hook\n' > "$CACHE_ROOT/4.16.0/scripts/launcher.py"
rm -f "$CACHE_ROOT/4.14.0"          # drop stale bridge symlink itself
rm -rf "$CACHE_ROOT/4.15.0"         # purge the real 4.15.0 dir
ln -s "$CACHE_ROOT/4.15.0" "$CACHE_ROOT/4.14.0"   # stale bridge -> now-purged 4.15.0
printf '%s|%s|tree\n' "$CACHE_ROOT/4.16.0" "$DEV_REPO" > "$MAP"

out="$(run_doctor "" "$MAP" "$VERSIONS")"
if grep -q "BRIDGE  repointed: $CACHE_ROOT/4.14.0 -> 4.16.0" <<<"$out"; then
  pass "stale bridge 4.14.0 repointed to 4.16.0"
else
  fail "expected repoint line for 4.14.0, got: $out"
fi
if grep -q "BRIDGE  created: $CACHE_ROOT/4.15.0 -> 4.16.0" <<<"$out"; then
  pass "intermediate version 4.15.0 bridged to 4.16.0"
else
  fail "expected bridge-created line for 4.15.0, got: $out"
fi
if [[ "$(readlink "$CACHE_ROOT/4.14.0")" == "$CACHE_ROOT/4.16.0" ]] \
   && [[ "$(readlink "$CACHE_ROOT/4.15.0")" == "$CACHE_ROOT/4.16.0" ]]; then
  pass "both old-version paths now resolve through symlinks to 4.16.0"
else
  fail "old-version paths do not resolve to 4.16.0 as expected"
fi

# =====================================================================
# 5. prune-bridges removes the symlinks AND forgets the versions, so the
#    very next run does not resurrect them.
# =====================================================================
echo " 5. prune-bridges retires bridges and prevents automatic recreation:"
out="$(run_doctor "prune-bridges" "$MAP" "$VERSIONS")"
if grep -q "PRUNED  $CACHE_ROOT/4.14.0" <<<"$out" && grep -q "PRUNED  $CACHE_ROOT/4.15.0" <<<"$out"; then
  pass "prune-bridges reports both retired bridges"
else
  fail "expected PRUNED lines for both 4.14.0 and 4.15.0, got: $out"
fi
if [[ ! -e "$CACHE_ROOT/4.14.0" && ! -e "$CACHE_ROOT/4.15.0" ]]; then
  pass "both bridge symlinks removed from disk"
else
  fail "bridge symlink(s) still present after prune-bridges"
fi
if ! grep -qF '4.14.0' "$VERSIONS" && ! grep -qF '4.15.0' "$VERSIONS"; then
  pass "state file forgot the pruned versions"
else
  fail "state file still references a pruned version: $(cat "$VERSIONS")"
fi

# Re-run check (no --repair, no prune-bridges): must NOT recreate what was
# just pruned — this is the whole point of an explicit, non-time-based
# retirement mechanism (rules/coding-standards.md §8: no invented TTL).
out="$(run_doctor "" "$MAP" "$VERSIONS")"
if [[ -e "$CACHE_ROOT/4.14.0" || -e "$CACHE_ROOT/4.15.0" ]]; then
  fail "pruned bridge was silently recreated on the next run"
else
  pass "pruned bridges stay retired across subsequent runs"
fi

# =====================================================================
# 6. Non-regression: pre-existing check/repair montage behavior.
# =====================================================================
echo " 6. non-regression on pre-existing check/repair montage behavior:"

# 6a. OK case: a properly mounted entry (backup sibling + correct symlink).
OK_CACHE="$TMP/ok-cache"
OK_DEV="$TMP/ok-dev"
mkdir -p "$OK_CACHE" "$OK_DEV"
printf 'x\n' > "$OK_DEV/file.txt"
printf 'orig\n' > "$OK_CACHE/file.txt.orig-backup"
ln -s "$OK_DEV/file.txt" "$OK_CACHE/file.txt"
OK_MAP="$TMP/ok-map"
printf '%s|%s|tree\n' "$OK_CACHE" "$OK_DEV" > "$OK_MAP"
out="$(run_doctor "" "$OK_MAP" "$TMP/ok-versions")"
rc=$?
if grep -qE '  OK      .*/ok-cache' <<<"$out" && [[ "$rc" -eq 0 ]]; then
  pass "OK entry reports OK and exits 0"
else
  fail "expected OK report + exit 0, got rc=$rc out=$out"
fi

# 6b. BROKEN case: mounted entry present (backup sibling) but the live
# symlink is missing entirely -> BROKEN, exit 1; then --repair fixes it.
BROKEN_CACHE="$TMP/broken-cache"
BROKEN_DEV="$TMP/broken-dev"
mkdir -p "$BROKEN_CACHE" "$BROKEN_DEV"
printf 'x\n' > "$BROKEN_DEV/file.txt"
printf 'orig\n' > "$BROKEN_CACHE/file.txt.orig-backup"
# no file.txt in cache at all: "missing (backup present, no live mount)"
BROKEN_MAP="$TMP/broken-map"
printf '%s|%s|tree\n' "$BROKEN_CACHE" "$BROKEN_DEV" > "$BROKEN_MAP"
out="$(run_doctor "" "$BROKEN_MAP" "$TMP/broken-versions")"
rc=$?
if grep -qE 'BROKEN  .*/broken-cache: file.txt' <<<"$out" && [[ "$rc" -eq 1 ]]; then
  pass "BROKEN entry reports BROKEN and exits 1"
else
  fail "expected BROKEN report + exit 1, got rc=$rc out=$out"
fi

out="$(run_doctor "--repair" "$BROKEN_MAP" "$TMP/broken-versions")"
if grep -q 'repaired: file.txt' <<<"$out" && [[ -L "$BROKEN_CACHE/file.txt" ]] \
   && [[ "$(readlink "$BROKEN_CACHE/file.txt")" == "$BROKEN_DEV/file.txt" ]]; then
  pass "--repair fixes the BROKEN entry (symlink now points at dev repo)"
else
  fail "--repair did not fix the broken entry as expected: $out"
fi

# =====================================================================
# 7. Fresh-install detection (root cause fixed 2026-07-15): mountable_entries
#    no longer requires an <entry>.orig-backup marker. A brand-new install
#    with real copies mirroring the dev repo and ZERO symlinks/backups must
#    be reported BROKEN, not OK by vacuity.
# =====================================================================
echo " 7. fresh install (no symlinks, no backups) is no longer OK by vacuity:"
FRESH_CACHE="$TMP/fresh-cache"
FRESH_DEV="$TMP/fresh-dev"
mkdir -p "$FRESH_CACHE/scripts" "$FRESH_DEV/scripts"
printf 'hook\n' > "$FRESH_DEV/scripts/launcher.py"
printf 'hook\n' > "$FRESH_CACHE/scripts/launcher.py"   # real copy, no symlink, no backup
FRESH_MAP="$TMP/fresh-map"
printf '%s|%s|tree\n' "$FRESH_CACHE" "$FRESH_DEV" > "$FRESH_MAP"
out="$(run_doctor "" "$FRESH_MAP" "$TMP/fresh-versions")"
rc=$?
if grep -qE 'BROKEN  .*/fresh-cache: scripts \(not mounted' <<<"$out" && [[ "$rc" -eq 1 ]]; then
  pass "fresh unmounted install reports BROKEN and exits 1"
else
  fail "expected BROKEN + exit 1 for fresh install, got rc=$rc out=$out"
fi

out="$(run_doctor "--repair" "$FRESH_MAP" "$TMP/fresh-versions")"
if [[ -L "$FRESH_CACHE/scripts" ]] && [[ "$(readlink "$FRESH_CACHE/scripts")" == "$FRESH_DEV/scripts" ]]; then
  pass "--repair mounts the fresh install (symlink now points at dev repo)"
else
  fail "--repair did not mount the fresh install: $out"
fi
if [[ -d "$FRESH_CACHE/scripts.orig-backup" ]]; then
  pass "--repair preserved the original real directory as .orig-backup"
else
  fail "--repair did not create the expected .orig-backup"
fi

# =====================================================================
# 8. Informational-only entries: a real cache entry with no dev-repo
#    counterpart is reported as INFO, excluded from BROKEN, and does not
#    block the OK verdict.
# =====================================================================
echo " 8. real entry with no dev-repo counterpart is informational, not BROKEN:"
INFO_CACHE="$TMP/info-cache"
INFO_DEV="$TMP/info-dev"
mkdir -p "$INFO_CACHE" "$INFO_DEV"
printf 'x\n' > "$INFO_DEV/file.txt"
printf 'orig\n' > "$INFO_CACHE/file.txt.orig-backup"
ln -s "$INFO_DEV/file.txt" "$INFO_CACHE/file.txt"
mkdir -p "$INFO_CACHE/.devcontainer"   # real dir, absent from dev repo
printf 'cache-only\n' > "$INFO_CACHE/.devcontainer/marker.txt"
INFO_MAP="$TMP/info-map"
printf '%s|%s|tree\n' "$INFO_CACHE" "$INFO_DEV" > "$INFO_MAP"
out="$(run_doctor "" "$INFO_MAP" "$TMP/info-versions")"
rc=$?
if grep -qE '  OK      .*/info-cache' <<<"$out" && [[ "$rc" -eq 0 ]]; then
  pass "cache-only entry does not block the OK verdict"
else
  fail "expected OK + exit 0 despite cache-only entry, got rc=$rc out=$out"
fi
if grep -qE 'INFO    .*/info-cache: \.devcontainer \(real entry, no dev-repo counterpart' <<<"$out"; then
  pass "cache-only entry reported as INFO"
else
  fail "expected INFO line for .devcontainer, got: $out"
fi
if [[ -d "$INFO_CACHE/.devcontainer" ]] && [[ ! -L "$INFO_CACHE/.devcontainer" ]] \
   && [[ -f "$INFO_CACHE/.devcontainer/marker.txt" ]]; then
  pass "cache-only entry left untouched"
else
  fail "cache-only entry was modified or removed"
fi

# =====================================================================
# 9. Binary mode has no equivalent blind spot: a real (unmounted) file at
#    the mapped relative path is BROKEN even on a fresh install.
# =====================================================================
echo " 9. binary mode: a real unmounted file is BROKEN, not OK by vacuity:"
BIN_CACHE="$TMP/bin-cache"
BIN_DEV="$TMP/bin-dev"
mkdir -p "$BIN_CACHE/target/release" "$BIN_DEV/target/release"
printf 'binary\n' > "$BIN_DEV/target/release/tool"
printf 'binary\n' > "$BIN_CACHE/target/release/tool"   # real copy, never mounted
BIN_MAP="$TMP/bin-map"
printf '%s|%s|target/release/tool\n' "$BIN_CACHE" "$BIN_DEV" > "$BIN_MAP"
out="$(run_doctor "" "$BIN_MAP" "$TMP/bin-versions")"
rc=$?
if grep -qE 'BROKEN  .*/bin-cache: target/release/tool \(not a symlink\)' <<<"$out" && [[ "$rc" -eq 1 ]]; then
  pass "binary mode reports BROKEN for a real unmounted file"
else
  fail "expected BROKEN + exit 1 for unmounted binary, got rc=$rc out=$out"
fi

echo
echo "dev-symlink-doctor result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1
echo "dev-symlink-doctor PASSED"
