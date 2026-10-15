# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-write-verbs.sh — create / str_replace / rethink / insert / delete /
# rename of memory-tool.sh. Sourced, never executed. Every verb: resolve the
# path, check the scope ACL, then mutate under the scope lock.

cmd_create() {
  local vpath="$1" file_text="$2"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" write "create" "$vpath"
  ensure_parent "$real"
  _do_create() {
    if [[ -e "$real" ]]; then
      echo "Error: File $vpath already exists"
      audit "create" "$vpath" 0 duplicate
      exit 1
    fi
    local bytes=${#file_text}
    size_check "$bytes" "$vpath" "$scope" "$scope"
    _pii_gate "$file_text" "create" "$vpath" "$bytes"
    _desc_gate "$file_text" "create" "$vpath"
    atomic_write "$real" "$file_text"
    local sha; sha=$(printf '%s' "$file_text" | sha256_of)
    audit "create" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "create" "$vpath" "$scope"
    echo "File created successfully at: $vpath"
  }
  with_lock "$scope" _do_create
}

# Prints the number of occurrences of <needle> in <file>; when there are several,
# a second line lists the line number of each. Usage: _occurrences <file> <needle>
_occurrences() {
  python3 - "$1" "$2" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); needle = sys.argv[2]
content = p.read_text()
count = content.count(needle)
print(count)
if count > 1:
    # Emit line numbers of every occurrence.
    start = 0
    lines = []
    while True:
        idx = content.find(needle, start)
        if idx == -1: break
        line_num = content.count("\n", 0, idx) + 1
        lines.append(str(line_num))
        start = idx + 1
    print(",".join(lines))
PY
}

# Prints <file> with the first <old> replaced by <new>. Usage: _replace_once <file> <old> <new>
_replace_once() {
  python3 - "$1" "$2" "$3" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
content = p.read_text()
new = content.replace(sys.argv[2], sys.argv[3], 1)
sys.stdout.write(new)
PY
}

cmd_str_replace() {
  local vpath="$1" old_str="$2" new_str="$3" expected_sha="${4:-}"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" write "str_replace" "$vpath"
  _do_replace() {
    if [[ ! -f "$real" ]]; then
      echo "Error: The path $vpath does not exist. Please provide a valid path."
      audit "str_replace" "$vpath" 0 missing
      exit 1
    fi
    _cas_gate "$real" "$expected_sha" "str_replace" "$vpath"
    # Count occurrences (python for multi-line old_str safety).
    local occ lines
    occ=$(_occurrences "$real" "$old_str")
    local count="${occ%%$'\n'*}"
    lines="${occ#*$'\n'}"
    if [[ "$count" == "0" ]]; then
      echo "No replacement was performed, old_str \`$old_str\` did not appear verbatim in $vpath."
      audit "str_replace" "$vpath" 0 not_found
      exit 1
    fi
    if (( count > 1 )); then
      echo "No replacement was performed. Multiple occurrences of old_str \`$old_str\` in lines: $lines. Please ensure it is unique"
      audit "str_replace" "$vpath" 0 ambiguous
      exit 1
    fi
    local new_content
    new_content=$(_replace_once "$real" "$old_str" "$new_str")
    local bytes=${#new_content}
    size_check "$bytes" "$vpath" "$scope"
    _pii_gate "$new_content" "str_replace" "$vpath" "$bytes"
    atomic_write "$real" "$new_content"
    local sha; sha=$(printf '%s' "$new_content" | sha256_of)
    audit "str_replace" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "str_replace" "$vpath" "$scope"
    echo "The memory file has been edited."
    # Snippet with line numbers around the change (context lines).
    awk '{ printf "%6d\t%s\n", NR, $0 }' "$real" | head -20
  }
  with_lock "$scope" _do_replace
}

# R6 — atomic whole-file rewrite of an EXISTING file (letta memory_rethink).
# Optional expected_sha enables compare-and-swap against lost updates.
cmd_rethink() {
  local vpath="$1" file_text="$2" expected_sha="${3:-}"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" write "rethink" "$vpath"
  _do_rethink() {
    if [[ ! -f "$real" ]]; then
      echo "Error: The path $vpath does not exist. Use create for new files."
      audit "rethink" "$vpath" 0 missing
      exit 1
    fi
    _cas_gate "$real" "$expected_sha" "rethink" "$vpath"
    local bytes=${#file_text}
    size_check "$bytes" "$vpath" "$scope"
    _pii_gate "$file_text" "rethink" "$vpath" "$bytes"
    _desc_gate "$file_text" "rethink" "$vpath"
    atomic_write "$real" "$file_text"
    local sha; sha=$(printf '%s' "$file_text" | sha256_of)
    audit "rethink" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "rethink" "$vpath" "$scope"
    echo "File rewritten successfully at: $vpath (sha256: $sha)"
  }
  with_lock "$scope" _do_rethink
}

cmd_insert() {
  local vpath="$1" insert_line="$2" insert_text="$3"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" write "insert" "$vpath"
  _do_insert() {
    if [[ ! -f "$real" ]]; then
      echo "Error: The path $vpath does not exist"
      audit "insert" "$vpath" 0 missing
      exit 1
    fi
    local n_lines; n_lines=$(awk 'END{print NR}' "$real")
    if ! [[ "$insert_line" =~ ^[0-9]+$ ]] || (( insert_line < 0 || insert_line > n_lines )); then
      echo "Error: Invalid \`insert_line\` parameter: $insert_line. It should be within the range of lines of the file: [0, $n_lines]"
      audit "insert" "$vpath" 0 invalid_line
      exit 1
    fi
    local new_content
    new_content=$(python3 - "$real" "$insert_line" "$insert_text" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); ln = int(sys.argv[2]); text = sys.argv[3]
lines = p.read_text().splitlines(keepends=True)
lines.insert(ln, text if text.endswith("\n") else text + "\n")
sys.stdout.write("".join(lines))
PY
)
    local bytes=${#new_content}
    size_check "$bytes" "$vpath" "$scope"
    _pii_gate "$new_content" "insert" "$vpath" "$bytes"
    atomic_write "$real" "$new_content"
    local sha; sha=$(printf '%s' "$new_content" | sha256_of)
    audit "insert" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "insert" "$vpath" "$scope"
    echo "The file $vpath has been edited."
  }
  with_lock "$scope" _do_insert
}

cmd_delete() {
  local vpath="$1"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" write "delete" "$vpath"
  _do_delete() {
    if [[ ! -e "$real" ]]; then
      echo "Error: The path $vpath does not exist"
      audit "delete" "$vpath" 0 missing
      exit 1
    fi
    rm -rf -- "$real"
    audit "delete" "$vpath" 0 ok
    enqueue_sync "delete" "$vpath" "$scope"
    echo "Successfully deleted $vpath"
  }
  with_lock "$scope" _do_delete
}

cmd_rename() {
  local old_vpath="$1" new_vpath="$2"
  local old_real new_real
  resolve_path "$old_vpath" old_real || exit 1
  resolve_path "$new_vpath" new_real || exit 1
  local old_scope new_scope
  old_scope="$(scope_of "$old_vpath")"
  new_scope="$(scope_of "$new_vpath")"
  _acl_guard "$old_scope" write "rename" "$old_vpath"
  _acl_guard "$new_scope" write "rename" "$new_vpath"
  ensure_parent "$new_real"
  local scope="$old_scope"
  _do_rename() {
    if [[ ! -e "$old_real" ]]; then
      echo "Error: The path $old_vpath does not exist"
      audit "rename" "$old_vpath" 0 missing
      exit 1
    fi
    if [[ -e "$new_real" ]]; then
      echo "Error: The destination $new_vpath already exists"
      audit "rename" "$new_vpath" 0 duplicate
      exit 1
    fi
    mv -- "$old_real" "$new_real"
    audit "rename" "$old_vpath->$new_vpath" 0 ok
    enqueue_sync "rename" "$old_vpath" "$new_scope" "$new_vpath"
    echo "Successfully renamed $old_vpath to $new_vpath"
  }
  with_lock "$scope" _do_rename
}
