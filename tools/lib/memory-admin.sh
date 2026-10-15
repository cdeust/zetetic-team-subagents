# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-admin.sh — ttl-sweep and audit of memory-tool.sh. Sourced, never
# executed. The reporting logic lives in lib/memory_admin.py.

# Sweeps one scope under its lock. Sets _TTL_SCOPE_DELETED to the number of
# files expired (or that would be, in dry-run mode).
# Usage: _ttl_sweep_scope <scope> <cutoff-epoch> <dry-run 0|1>
_ttl_sweep_scope() {
  local scope="$1" cutoff="$2" dry_run="$3"
  local scope_dir="$MEMORY_ROOT/$scope"
  _TTL_SCOPE_DELETED=0
  while IFS= read -r fpath; do
    [[ -z "$fpath" ]] && continue
    [[ -f "$fpath" ]] || continue
    local fmtime
    fmtime=$(python3 -c "import os; print(int(os.path.getmtime('$fpath')))" 2>/dev/null || echo 0)
    if (( fmtime < cutoff )); then
      local vp="/memories/$scope/${fpath#$scope_dir/}"
      if (( dry_run )); then
        echo "[dry-run] would expire: $vp (mtime $(date -r "$fmtime" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo $fmtime))"
      else
        rm -f -- "$fpath"
        audit "ttl_expire" "$vp" 0 ok
        enqueue_sync "delete" "$vp" "$scope"
      fi
      _TTL_SCOPE_DELETED=$(( _TTL_SCOPE_DELETED + 1 ))
    fi
  done < <(find "$scope_dir" -type f ! -name '.*' 2>/dev/null)
}

# ACL is bypassed on purpose: the TTL sweep is a system operation (governance
# enforcement, not a data operation). JUSTIFICATION: TTL enforcement is defined
# in the registry by the curator; enforcing it must not be blocked by ACL.
# source: memory/contract.md §6 (over-cap behavior must not fail silently)
cmd_ttl_sweep() {
  # Precondition:  registry exists and has scopes with non-null ttl_days.
  # Postcondition: every file whose mtime is older than its scope's ttl_days
  #                has been deleted (or printed in dry-run mode); one audit line
  #                written per deletion; one sync job enqueued per deletion.
  #                Running twice in a row is safe (re-entrant: already-deleted
  #                files are simply absent on the second pass).
  local dry_run=0
  while (( $# )); do
    case "$1" in
      --dry-run) dry_run=1; shift ;;
      *) shift ;;
    esac
  done

  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    echo "TTL sweep: 0 files expired across 0 scopes (no registry)"
    return 0
  fi

  # Build list of (scope ttl_days) pairs where ttl_days is not null.
  local scope_ttl_pairs
  scope_ttl_pairs=$(python3 "$_script_dir/lib/memory_admin.py" ttl-pairs "$MEMORY_REGISTRY")

  local total_files=0 total_scopes=0
  local now; now=$(date +%s)

  while IFS=' ' read -r scope ttl_days; do
    [[ -z "$scope" || -z "$ttl_days" ]] && continue
    [[ -d "$MEMORY_ROOT/$scope" ]] || continue

    local cutoff=$(( now - ttl_days * 86400 ))
    if (( dry_run )); then
      _ttl_sweep_scope "$scope" "$cutoff" "$dry_run"
    else
      with_lock "$scope" _ttl_sweep_scope "$scope" "$cutoff" "$dry_run"
    fi

    if (( _TTL_SCOPE_DELETED > 0 )); then
      total_scopes=$(( total_scopes + 1 ))
      total_files=$(( total_files + _TTL_SCOPE_DELETED ))
    fi
  done <<< "$scope_ttl_pairs"

  if (( dry_run )); then
    echo "[dry-run] TTL sweep: $total_files files would expire across $total_scopes scopes"
  else
    echo "TTL sweep: $total_files files expired across $total_scopes scopes"
  fi
}

cmd_audit() {
  # Precondition:  AUDIT_LOG exists (may be absent if no writes have occurred).
  # Postcondition: prints lines from the last 24 hours (or --since window),
  #                followed by a summary block and anomaly flags.
  local since_iso=""
  while (( $# )); do
    case "$1" in
      --since) since_iso="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [[ ! -f "$AUDIT_LOG" ]]; then
    echo "Audit log is empty — no writes recorded yet."
    return 0
  fi

  # Determine cutoff epoch second.
  local cutoff_epoch
  if [[ -n "$since_iso" ]]; then
    cutoff_epoch=$(python3 "$_script_dir/lib/memory_admin.py" since "$since_iso" 2>/dev/null) \
      || { echo "Error: invalid --since value: $since_iso"; exit 1; }
  else
    cutoff_epoch=$(( $(date +%s) - 86400 ))
  fi

  python3 "$_script_dir/lib/memory_admin.py" audit-report "$AUDIT_LOG" "$cutoff_epoch"
}
