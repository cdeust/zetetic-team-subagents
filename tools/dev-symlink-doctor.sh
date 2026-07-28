#!/usr/bin/env bash
# dev-symlink-doctor.sh — Verify (and optionally repair) the "edition live"
# symlink montage between plugin cache installs and their dev repos, AND
# auto-bridge purged plugin-version directories so in-flight sessions whose
# CLAUDE_PLUGIN_ROOT still points at an old version keep working.
#
# Usage:
#   tools/dev-symlink-doctor.sh [--repair|prune-bridges]
#
# Map file (default ~/.claude/dev-symlink.map, override via DEV_SYMLINK_MAP):
#   <cache_install_dir>|<dev_repo_dir>|<mode>
#   mode = "tree" (every top-level cache entry whose name ALSO exists at the
#          top level of the dev repo — a "montable" entry, see
#          mountable_entries() — must be a symlink into the dev repo; a
#          montable entry that is a real file/dir, not a symlink, is BROKEN
#          regardless of whether an <entry>.orig-backup marker exists — this
#          is what makes a fresh, never-mounted install detectable instead of
#          reporting OK by vacuity) or a relative path (binary mode: that one
#          path must be a symlink into the dev repo, e.g.
#          target/release/automatised-pipeline).
#   Blank lines and lines starting with # are ignored. ~ expands to $HOME.
#   <cache_install_dir> is expected to end in the plugin's version segment
#   (e.g. .../cortex-plugins/cortex/4.14.0) — this is what the version-bridge
#   mechanism below keys off.
#
# Repair pattern (per broken mount entry, idempotent):
#   - if <entry>.orig-backup already exists: rm -rf <entry>
#   - else: mv <entry> <entry>.orig-backup
#   - ln -s <dev_repo_dir>/<entry> <entry>
#   Never touches .claude-plugin, .git*, or .in_use.
#
# Version-bridge mechanism (root cause: Claude Code's plugin auto-update
# replaces <plugin_dir>/<old_version> with <plugin_dir>/<new_version> and
# PURGES the old_version directory; any session already running captured
# CLAUDE_PLUGIN_ROOT=<...>/<old_version> at spawn, so every hook invocation
# under that root breaks with "No such file or directory" until the session
# restarts. The owner directive is: do not prevent the purge — instead,
# re-attach the old path via a symlink to the current version the moment the
# purge is detected, so in-flight sessions stay live):
#   - State file (default ~/.claude/dev-symlink.versions, override via
#     DEV_SYMLINK_VERSIONS): one line per plugin dir,
#     `<plugin_dir>|<v1>,<v2>,...` (oldest to newest, deduplicated) — the
#     full history of versions this doctor has ever observed for that
#     plugin, so a purge can be detected and bridged even if it happened
#     between two widely-spaced runs (e.g. an update while no session ran
#     the doctor in between).
#   - On every check/repair run (see ensure_version_bridge): for each
#     historical version no longer present on disk, if the CURRENT version
#     directory (named in the map file) exists as a real directory, create
#     `ln -s <plugin_dir>/<current_version> <plugin_dir>/<old_version>`.
#     An existing bridge whose target has drifted (a second update landed
#     before the bridge was pruned) is re-pointed at the new current
#     version. A real (non-symlink) directory at the old path is NEVER
#     touched — it might be genuine data, not yet purged.
#   - Bridges are retired ONLY by the explicit `prune-bridges` subcommand,
#     never by an arbitrary time-based rule (no evidence exists for any
#     "safe" TTL — see rules/coding-standards.md §8). `prune-bridges` removes
#     every version-bridge symlink found directly under each mapped plugin
#     dir and forgets the corresponding version(s) from the state file, so
#     they are not silently re-created on the next run.
#
# Exit codes:
#   check/repair: 0 all OK (or no map file), 1 at least one BROKEN entry, 2 usage.
#   prune-bridges: always 0 (pruning is advisory maintenance, not a gate).

set -euo pipefail

MODE="check"
case "${1:-}" in
  --repair) MODE="repair" ;;
  prune-bridges) MODE="prune-bridges" ;;
  "") ;;
  *) echo "usage: $0 [--repair|prune-bridges]" >&2; exit 2 ;;
esac

MAP_FILE="${DEV_SYMLINK_MAP:-$HOME/.claude/dev-symlink.map}"
VERSIONS_FILE="${DEV_SYMLINK_VERSIONS:-$HOME/.claude/dev-symlink.versions}"

expand_tilde() {
  local p="$1"
  case "$p" in
    "~"*) printf '%s' "$HOME${p#\~}" ;;
    *) printf '%s' "$p" ;;
  esac
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# Joins its arguments with a comma. Precondition: none (zero args -> empty
# string). Postcondition: output has no trailing/leading comma and no
# reliance on IFS beyond this function's own scope.
join_csv() {
  local out="" a first=1
  for a in "$@"; do
    if [[ "$first" -eq 1 ]]; then out="$a"; first=0; else out="$out,$a"; fi
  done
  printf '%s' "$out"
}

is_excluded_entry() {
  case "$1" in
    .claude-plugin|.in_use|.DS_Store) return 0 ;;
    .git*) return 0 ;;
    *.orig-backup) return 0 ;;
    *) return 1 ;;
  esac
}

# A cache entry is "montable" (subject to the tree-mode check) iff its name
# ALSO exists at the top level of the dev repo, after exclusions. This is the
# ONLY signal used: a prior <entry>.orig-backup marker is NOT required. The
# earlier version of this function required a backup marker to consider an
# entry mounted at all, which meant a fresh plugin install — no symlinks, no
# backups yet — had zero montable entries and the doctor reported OK by
# vacuity even though nothing was actually mounted (root-caused 2026-07-15:
# a `claude plugin update` left 4 real, unmounted plugin dirs and the doctor
# said OK on all 4). An <entry>.orig-backup sibling, when present, still
# resolves to its canonical name here so a partially-repaired montage (backup
# exists, live symlink missing or wrong) is still caught. A cache entry whose
# name has NO dev-repo counterpart (e.g. a per-install manifest or a real
# directory the dev repo simply doesn't carry) is never montable — it is
# reported separately, informationally, by info_only_entries() below, and is
# never touched by --repair.
mountable_entries() {
  local cache="$1" dev="$2" entry name dev_abs seen=""
  dev_abs="$(cd "$dev" 2>/dev/null && pwd)" || return 0
  while IFS= read -r -d '' entry; do
    name="$(basename "$entry")"
    case "$name" in
      *.orig-backup) name="${name%.orig-backup}" ;;
    esac
    is_excluded_entry "$name" && continue
    [[ -e "$dev_abs/$name" || -L "$dev_abs/$name" ]] || continue
    case "$seen" in
      *" $name "*) continue ;;
    esac
    seen="$seen $name "
    printf '%s\n' "$name"
  done < <(find "$cache" -maxdepth 1 -mindepth 1 -print0 2>/dev/null)
}

# Prints cache-root entry names that are NOT montable (no same-named entry in
# the dev repo, after exclusions) — real data the dev repo doesn't mirror
# (e.g. cortex/4.14.1's real .claude and .devcontainer dirs, absent from the
# Cortex-live worktree). Reported for visibility only: excluded from the
# BROKEN list, untouched by --repair, and does not affect the exit code.
info_only_entries() {
  local cache="$1" dev="$2" entry name dev_abs
  dev_abs="$(cd "$dev" 2>/dev/null && pwd)" || return 0
  while IFS= read -r -d '' entry; do
    name="$(basename "$entry")"
    case "$name" in
      *.orig-backup) name="${name%.orig-backup}" ;;
    esac
    is_excluded_entry "$name" && continue
    [[ -e "$dev_abs/$name" || -L "$dev_abs/$name" ]] && continue
    printf '%s\n' "$name"
  done < <(find "$cache" -maxdepth 1 -mindepth 1 -print0 2>/dev/null) | sort -u
}

# Prints "<name>\t<reason>" for each broken montable entry (tree mode).
check_tree() {
  local cache="$1" dev="$2" dev_abs name entry expected actual
  dev_abs="$(cd "$dev" 2>/dev/null && pwd)" || { printf '%s\t%s\n' "(dev repo)" "missing ($dev)"; return; }
  while IFS= read -r name; do
    is_excluded_entry "$name" && continue
    entry="$cache/$name"
    expected="$dev_abs/$name"
    if [[ -L "$entry" ]]; then
      actual="$(readlink "$entry")"
      [[ "$actual" == "$expected" ]] || printf '%s\t%s\n' "$name" "points elsewhere ($actual)"
    elif [[ -e "$entry" ]]; then
      printf '%s\t%s\n' "$name" "not mounted (real entry, not a symlink into the dev repo)"
    else
      printf '%s\t%s\n' "$name" "missing (expected a symlink into the dev repo)"
    fi
  done < <(mountable_entries "$cache" "$dev")
}

# Prints "<rel>\t<reason>" if the single binary-mode path is broken.
check_binary() {
  local cache="$1" dev="$2" rel="$3" dev_abs entry expected actual
  dev_abs="$(cd "$dev" 2>/dev/null && pwd)" || { printf '%s\t%s\n' "$rel" "dev repo missing"; return; }
  entry="$cache/$rel"
  expected="$dev_abs/$rel"
  if [[ ! -e "$entry" && ! -L "$entry" ]]; then
    printf '%s\t%s\n' "$rel" "missing"
  elif [[ -L "$entry" ]]; then
    actual="$(readlink "$entry")"
    [[ "$actual" == "$expected" ]] || printf '%s\t%s\n' "$rel" "points elsewhere ($actual)"
  else
    printf '%s\t%s\n' "$rel" "not a symlink"
  fi
}

# Repairs one broken entry (tree entry name, or binary-mode relative path).
repair_entry() {
  local cache="$1" dev="$2" rel="$3" entry target
  entry="$cache/$rel"
  target="$dev/$rel"
  if [[ -e "${entry}.orig-backup" || -L "${entry}.orig-backup" ]]; then
    rm -rf "$entry"
  elif [[ -e "$entry" || -L "$entry" ]]; then
    mkdir -p "$(dirname "$entry")"
    mv "$entry" "${entry}.orig-backup"
  fi
  mkdir -p "$(dirname "$entry")"
  ln -s "$target" "$entry"
  echo "    repaired: $rel"
}

# --- Version-bridge state file -------------------------------------------
#
# Format: `<plugin_dir>|<v1>,<v2>,...` — one line per plugin_dir, comma list
# is deduplicated, order = first-observed. Blank lines / lines starting with
# # are preserved verbatim (defensive; the file is doctor-owned so none are
# expected in practice, but a rewrite must not silently eat a hand-edited
# comment).

# Precondition: plugin_dir is an absolute, tilde-expanded path (matches how
# it is stored). Postcondition: prints the stored CSV history for plugin_dir
# (may be empty string) and returns 0; prints nothing and returns 0 if no
# record or no state file exists yet (not an error — first run for a plugin).
versions_history_get() {
  local plugin_dir="$1" p_dir hist
  [[ -f "$VERSIONS_FILE" ]] || return 0
  while IFS='|' read -r p_dir hist || [[ -n "$p_dir" ]]; do
    p_dir="$(trim "$p_dir")"
    [[ -z "$p_dir" || "$p_dir" == \#* ]] && continue
    if [[ "$p_dir" == "$plugin_dir" ]]; then
      printf '%s' "$(trim "${hist:-}")"
      return 0
    fi
  done < "$VERSIONS_FILE"
}

# Precondition: plugin_dir absolute; hist is a CSV string (may be empty).
# Postcondition: VERSIONS_FILE contains exactly one line for plugin_dir with
# body=hist (line omitted entirely if hist is empty — an empty history is
# not worth persisting), all other lines and comments preserved verbatim.
# Invariant: the rewrite is atomic (temp file + mv) so a crash mid-write
# never leaves a truncated state file.
versions_history_set() {
  local plugin_dir="$1" hist="$2" tmp p_dir rest trimmed_pdir found=0
  tmp="$(mktemp "${VERSIONS_FILE}.XXXXXX")"
  if [[ -f "$VERSIONS_FILE" ]]; then
    while IFS='|' read -r p_dir rest || [[ -n "$p_dir" ]]; do
      trimmed_pdir="$(trim "$p_dir")"
      if [[ -z "$trimmed_pdir" || "$trimmed_pdir" == \#* ]]; then
        printf '%s\n' "${p_dir}${rest:+|$rest}" >> "$tmp"
        continue
      fi
      if [[ "$trimmed_pdir" == "$plugin_dir" ]]; then
        found=1
        [[ -n "$hist" ]] && printf '%s|%s\n' "$plugin_dir" "$hist" >> "$tmp"
        continue
      fi
      printf '%s|%s\n' "$p_dir" "$rest" >> "$tmp"
    done < "$VERSIONS_FILE"
  fi
  if [[ "$found" -eq 0 && -n "$hist" ]]; then
    printf '%s|%s\n' "$plugin_dir" "$hist" >> "$tmp"
  fi
  mkdir -p "$(dirname "$VERSIONS_FILE")"
  mv "$tmp" "$VERSIONS_FILE"
}

# --- Version-bridge mechanism ---------------------------------------------

# Precondition: cache is the tilde-expanded <cache_install_dir> from a map
# line (parent dir is the plugin dir; basename is the current version).
# Postcondition: every version previously recorded for this plugin that no
# longer exists on disk now has a symlink bridge to the current version
# (created iff the current version dir is a real directory); every existing
# bridge whose target is stale is re-pointed at the current version; a real
# (non-symlink) directory at an old-version path is left untouched (may be
# genuine data, not a purge). The current version is recorded into the
# state-file history (deduplicated) so a FUTURE purge of it can be bridged
# too. Idempotent: re-running with no on-disk change is a no-op.
ensure_version_bridge() {
  local cache="$1" plugin_dir version hist hv old_dir cur_dir target h seen=0
  plugin_dir="$(dirname "$cache")"
  version="$(basename "$cache")"
  cur_dir="$plugin_dir/$version"
  hist="$(versions_history_get "$plugin_dir")"

  local -a hist_arr=()
  if [[ -n "$hist" ]]; then
    IFS=',' read -r -a hist_arr <<< "$hist"
  fi

  if [[ ${#hist_arr[@]} -gt 0 ]]; then
    for hv in "${hist_arr[@]}"; do
      [[ -z "$hv" || "$hv" == "$version" ]] && continue
      old_dir="$plugin_dir/$hv"
      if [[ -L "$old_dir" ]]; then
        target="$(readlink "$old_dir")"
        if [[ "$target" != "$cur_dir" ]]; then
          rm -f "$old_dir"
          ln -s "$cur_dir" "$old_dir"
          echo "  BRIDGE  repointed: $old_dir -> $version"
        fi
      elif [[ -e "$old_dir" ]]; then
        : # real directory still present — never touch (not purged, or genuine data)
      else
        if [[ -d "$cur_dir" && ! -L "$cur_dir" ]]; then
          ln -s "$cur_dir" "$old_dir"
          echo "  BRIDGE  created: $old_dir -> $version"
        fi
      fi
    done
  fi

  local -a new_hist=()
  if [[ ${#hist_arr[@]} -gt 0 ]]; then
    new_hist=("${hist_arr[@]}")
    for h in "${new_hist[@]}"; do [[ "$h" == "$version" ]] && seen=1; done
  fi
  [[ "$seen" -eq 0 ]] && new_hist+=("$version")
  versions_history_set "$plugin_dir" "$(join_csv "${new_hist[@]}")"
}

# Precondition: cache is the tilde-expanded <cache_install_dir> from a map
# line. Postcondition: every symlink found directly under the plugin dir
# whose target resolves under the SAME plugin dir (the only shape
# ensure_version_bridge ever creates at that level) is removed, and the
# corresponding version(s) are dropped from the state-file history so they
# are not silently re-created on the next check/repair run. A real
# (non-symlink) directory or a symlink pointing outside the plugin dir is
# never touched.
prune_bridges_for() {
  local cache="$1" plugin_dir entry name target hist found_any=0
  plugin_dir="$(dirname "$cache")"
  [[ -d "$plugin_dir" ]] || return 0

  hist="$(versions_history_get "$plugin_dir")"
  local -a hist_arr=()
  if [[ -n "$hist" ]]; then
    IFS=',' read -r -a hist_arr <<< "$hist"
  fi

  local -a removed=()
  while IFS= read -r -d '' entry; do
    [[ -L "$entry" ]] || continue
    name="$(basename "$entry")"
    target="$(readlink "$entry")"
    case "$target" in
      "$plugin_dir"/*) : ;;
      *) continue ;;
    esac
    rm -f "$entry"
    echo "  PRUNED  $entry (was -> $target)"
    removed+=("$name")
    found_any=1
  done < <(find "$plugin_dir" -maxdepth 1 -mindepth 1 -print0 2>/dev/null)

  if [[ "$found_any" -eq 1 && ${#hist_arr[@]} -gt 0 ]]; then
    local -a kept=()
    local h r skip
    for h in "${hist_arr[@]}"; do
      skip=0
      if [[ ${#removed[@]} -gt 0 ]]; then
        for r in "${removed[@]}"; do [[ "$h" == "$r" ]] && skip=1; done
      fi
      [[ "$skip" -eq 0 ]] && kept+=("$h")
    done
    if [[ ${#kept[@]} -gt 0 ]]; then
      versions_history_set "$plugin_dir" "$(join_csv "${kept[@]}")"
    else
      versions_history_set "$plugin_dir" ""
    fi
  fi
}

process_mapping() {
  local cache="$1" dev="$2" mode="$3" label broken_line name reason had_broken=0 info_name

  cache="$(expand_tilde "$cache")"; dev="$(expand_tilde "$dev")"
  label="$(basename "$(dirname "$cache")")/$(basename "$cache")"

  if [[ ! -d "$cache" ]]; then
    echo "  BROKEN $label: cache install dir missing ($cache)"
    return 1
  fi

  local broken=()
  if [[ "$mode" == "tree" ]]; then
    while IFS=$'\t' read -r name reason; do
      [[ -z "$name" ]] && continue
      broken+=("$name|$reason")
    done < <(check_tree "$cache" "$dev")
    while IFS= read -r info_name; do
      [[ -z "$info_name" ]] && continue
      echo "  INFO    $label: $info_name (real entry, no dev-repo counterpart — left as-is)"
    done < <(info_only_entries "$cache" "$dev")
  else
    while IFS=$'\t' read -r name reason; do
      [[ -z "$name" ]] && continue
      broken+=("$name|$reason")
    done < <(check_binary "$cache" "$dev" "$mode")
  fi

  if [[ ${#broken[@]} -eq 0 ]]; then
    echo "  OK      $label"
    return 0
  fi

  had_broken=1
  for broken_line in "${broken[@]}"; do
    name="${broken_line%%|*}"; reason="${broken_line#*|}"
    echo "  BROKEN  $label: $name ($reason)"
    if [[ "$MODE" == "repair" ]]; then
      repair_entry "$cache" "$dev" "$name"
    fi
  done
  return "$had_broken"
}

main() {
  if [[ ! -f "$MAP_FILE" ]]; then
    echo "dev-symlink-doctor: no map file at $MAP_FILE — nothing to check"
    exit 0
  fi

  if [[ "$MODE" == "prune-bridges" ]]; then
    local cache dev mode
    while IFS='|' read -r cache dev mode || [[ -n "$cache" ]]; do
      cache="$(trim "$cache")"
      [[ -z "$cache" || "$cache" == \#* ]] && continue
      prune_bridges_for "$(expand_tilde "$cache")"
    done < "$MAP_FILE"
    exit 0
  fi

  local rc=0 cache dev mode
  while IFS='|' read -r cache dev mode || [[ -n "$cache" ]]; do
    cache="$(trim "$cache")"
    [[ -z "$cache" || "$cache" == \#* ]] && continue
    dev="$(trim "${dev:-}")"
    mode="$(trim "${mode:-}")"
    [[ -z "$dev" || -z "$mode" ]] && { echo "  skip malformed line: $cache|$dev|$mode" >&2; continue; }
    ensure_version_bridge "$(expand_tilde "$cache")"
    process_mapping "$cache" "$dev" "$mode" || rc=1
  done < "$MAP_FILE"

  exit "$rc"
}

main
