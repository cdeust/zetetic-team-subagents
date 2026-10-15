# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-sync.sh — Cortex replica queue of memory-tool.sh. Sourced, never
# executed. Expects PENDING_SYNC_DIR, MEMORY_AGENT_ID and resolve_path.

# Local FS is authoritative; Cortex is an async replica. After any successful
# mutation, enqueue a job describing the post-state. A Claude-side agent
# drains the queue via MCP (cortex:remember) and marks jobs committed.
# Enqueue failure MUST NOT fail the parent op (contract §5.3).

MEMORY_NO_SYNC="${MEMORY_NO_SYNC:-}"

enqueue_sync() {
  [[ -n "$MEMORY_NO_SYNC" ]] && return 0
  local op="$1" vpath="$2" scope="$3" new_vpath="${4:-}"
  mkdir -p -- "$PENDING_SYNC_DIR" 2>/dev/null || return 0
  local ts; ts="$(date -u +%Y%m%dT%H%M%SZ)"
  # Short random suffix for uniqueness under concurrent writes.
  local rand; rand="$(od -An -N4 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' || printf '%04x' "$RANDOM")"
  local id="${ts}-${rand}"
  local job_file="$PENDING_SYNC_DIR/$id.json"
  local tmp="$job_file.tmp.$$"

  # Read post-state (for ops that leave a file). Skip for delete.
  local target_real=""
  if [[ "$op" != "delete" ]]; then
    local effective_vpath="${new_vpath:-$vpath}"
    if ! resolve_path "$effective_vpath" target_real 2>/dev/null; then
      # Resolution failure shouldn't block enqueue — record without body.
      target_real=""
    fi
  fi

  python3 - "$tmp" "$id" "$op" "$vpath" "$new_vpath" "$scope" "$MEMORY_AGENT_ID" "$target_real" <<'PY' 2>/dev/null || return 0
import sys, os, json, hashlib, base64, pathlib
tmp, job_id, op, vpath, new_vpath, scope, agent, target = sys.argv[1:9]
payload = {
    "id": job_id,
    "ts": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "op": op,
    "agent_id": agent,
    "scope": scope,
    "vpath": vpath,
}
if new_vpath:
    payload["new_vpath"] = new_vpath
if target and op != "delete" and pathlib.Path(target).is_file():
    data = pathlib.Path(target).read_bytes()
    payload["bytes"] = len(data)
    payload["content_sha256"] = hashlib.sha256(data).hexdigest()
    payload["content_b64"] = base64.b64encode(data).decode()
pathlib.Path(tmp).write_text(json.dumps(payload, ensure_ascii=False))
PY
  mv -f -- "$tmp" "$job_file" 2>/dev/null || { rm -f "$tmp"; return 0; }
  return 0
}

cmd_sync_status() {
  if [[ ! -d "$PENDING_SYNC_DIR" ]]; then
    echo "queue: empty (no .pending-sync directory yet)"
    return 0
  fi
  local pending claimed oldest
  pending=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  claimed=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json.claimed' 2>/dev/null | wc -l | tr -d ' ')
  oldest=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
           | sort | head -1 | xargs -I{} basename {} .json 2>/dev/null || true)
  printf 'queue: %d pending, %d claimed (in-flight)\n' "$pending" "$claimed"
  [[ -n "$oldest" ]] && printf 'oldest: %s\n' "$oldest"
}

cmd_drain_sync() {
  # Emit pending jobs as JSONL, one per line, AND atomically claim each so
  # a concurrent drainer cannot replicate the same job twice. Caller must
  # invoke commit-sync or release-sync for each id it emits.
  local limit=50
  while (( $# )); do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  [[ -d "$PENDING_SYNC_DIR" ]] || { echo ""; return 0; }
  local count=0
  # Sort by filename (timestamp-prefixed → chronological).
  while IFS= read -r job_file; do
    [[ -z "$job_file" ]] && continue
    (( count >= limit )) && break
    local claimed="$job_file.claimed"
    # Atomic claim via rename — loser sees ENOENT on original and skips.
    # INVARIANT: a job is claimed iff the source no longer exists after mv -n.
    # BSD mv -n returns exit 0 even when dst pre-exists (no-clobber skip), so
    # [[ -f $claimed ]] is insufficient — it is true whether or not WE moved it.
    # The correct witness is [[ ! -e $job_file ]]: the rename atomically removed
    # the source; if it still exists, another drainer claimed it first.
    # source: POSIX rename(2) atomicity; BSD mv(1) man page no-clobber semantics.
    if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ ! -e "$job_file" ]]; then
      cat "$claimed"
      printf '\n'
      count=$((count + 1))
    fi
  done < <(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort)
}

cmd_commit_sync() {
  local job_id="$1"
  [[ -z "$job_id" ]] && { echo "Error: commit-sync requires a job id"; exit 1; }
  local claimed="$PENDING_SYNC_DIR/$job_id.json.claimed"
  if [[ ! -f "$claimed" ]]; then
    echo "Error: job $job_id is not claimed (already committed or never drained)"
    exit 1
  fi
  rm -f -- "$claimed"
  echo "Committed sync job $job_id"
}

cmd_release_sync() {
  local job_id="$1"
  [[ -z "$job_id" ]] && { echo "Error: release-sync requires a job id"; exit 1; }
  local claimed="$PENDING_SYNC_DIR/$job_id.json.claimed"
  local pending="$PENDING_SYNC_DIR/$job_id.json"
  if [[ ! -f "$claimed" ]]; then
    echo "Error: job $job_id is not claimed"
    exit 1
  fi
  mv -- "$claimed" "$pending"
  echo "Released sync job $job_id back to queue"
}
