# shellcheck shell=bash
# Render all event paths from the canonical jobs, with no runtime YAML package.
# Source: tasks/ci-event-separation-20261024.md.
do_render_ci() {
  local target="${1:-}"
  local -a options=("${@:2}")
  if [[ -z "$target" ]]; then
    echo "usage: $0 render-ci <target-repository> [--dry-run] [--native-review [--no-schedule]]" >&2
    return 2
  fi
  [[ "$DRY_RUN" != true ]] || options+=(--dry-run)
  python3 "$PLUGIN_ROOT/scripts/lib/render_ci.py" "$target" "${options[@]}"
}
