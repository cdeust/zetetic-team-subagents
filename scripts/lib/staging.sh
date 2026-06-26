# lib/staging.sh — stage plugin files into a temp tree with optional overrides.
# Sourced by setup.sh. Relies on these globals/functions from the caller:
#   STAGING, manifest_lines (array), count_overridden, resolve_override(), sha_cmd()
# Globals are read at call time (not source time), so the caller may declare them
# after this file is sourced. Cross-platform: pure bash + sed/sha helpers.

# Stage a file (with optional model+effort override for agent .md files)
stage_file() {
  local src="$1" rel_dest="$2" apply_overrides="${3:-false}"
  local dest_dir; dest_dir="$(dirname "$STAGING/$rel_dest")"
  mkdir -p "$dest_dir"

  if [[ "$apply_overrides" == true ]] && [[ "$src" == *.md ]]; then
    local agent_rel="${rel_dest#agents/}"
    local agent_name="${agent_rel%.md}"

    # Current frontmatter values
    local current_model current_effort
    current_model=$(sed -n '/^---$/,/^---$/{ /^model:/s/^model: *//p; }' "$src" 2>/dev/null | head -1)
    [[ -z "$current_model" ]] && current_model="opus"
    current_effort=$(sed -n '/^---$/,/^---$/{ /^effort:/s/^effort: *//p; }' "$src" 2>/dev/null | head -1)

    # Resolve overrides — "model|effort" (either may be empty = keep default)
    local override; override="$(resolve_override "$agent_name")"
    local ov_model="${override%%|*}"
    local ov_effort="${override#*|}"
    local target_model="${ov_model:-$current_model}"
    local target_effort="${ov_effort:-$current_effort}"

    if [[ "$target_model" != "$current_model" ]] || [[ "$target_effort" != "$current_effort" ]]; then
      # Rewrite both lines (sed handles each; if effort line is absent and override provides one, insert it)
      local tmp; tmp=$(mktemp)
      cp "$src" "$tmp"
      if [[ "$target_model" != "$current_model" ]]; then
        sed -i.bak "s/^model: .*/model: $target_model/" "$tmp" && rm -f "${tmp}.bak"
      fi
      if [[ -n "$target_effort" ]] && [[ "$target_effort" != "$current_effort" ]]; then
        if [[ -n "$current_effort" ]]; then
          sed -i.bak "s/^effort: .*/effort: $target_effort/" "$tmp" && rm -f "${tmp}.bak"
        else
          # Insert effort: after model: line
          sed -i.bak "/^model:/a\\
effort: $target_effort
" "$tmp" && rm -f "${tmp}.bak"
        fi
      fi
      mv "$tmp" "$STAGING/$rel_dest"
      count_overridden=$((count_overridden + 1))
    else
      cp "$src" "$STAGING/$rel_dest"
    fi
  else
    cp "$src" "$STAGING/$rel_dest"
  fi

  local checksum; checksum="$(sha_cmd "$STAGING/$rel_dest")"
  manifest_lines+=("${checksum}  ${rel_dest}")
}

# Stage a directory tree (files + subdirectories)
stage_tree() {
  local src_root="$1" dest_prefix="$2" apply_models="${3:-false}"
  local counter_var="$4"
  local count=0

  [[ -d "$src_root" ]] || return

  # Top-level files
  for f in "$src_root"/*.md "$src_root"/*.sh "$src_root"/*.json; do
    [[ -f "$f" ]] || continue
    stage_file "$f" "${dest_prefix}/$(basename "$f")" "$apply_models"
    count=$((count + 1))
  done

  # Subdirectories
  for dir in "$src_root"/*/; do
    [[ -d "$dir" ]] || continue
    local dname; dname="$(basename "$dir")"
    for f in "$dir"*.md "$dir"*.sh "$dir"*.json; do
      [[ -f "$f" ]] || continue
      stage_file "$f" "${dest_prefix}/${dname}/$(basename "$f")" "$apply_models"
      count=$((count + 1))
    done
  done

  printf -v "$counter_var" "%d" "$count"
}
