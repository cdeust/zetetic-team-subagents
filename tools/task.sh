#!/bin/sh
# task.sh -- shell front door of tools/lib/tasks.py (docs/async-tasks.md).
# Usage: task.sh start KIND KEY [--requeue] [--repo D] [--cwd D] -- CMD...
#        task.sh status ID [--repo D] | latest KIND [KEY] [--repo D] | inbox [--repo D]
# Every verb prints one JSON document and exits 0; there is no wait verb, by design.
set -u
HERE=$(cd "$(dirname "$0")" && pwd) || exit 2
exec python3 "$HERE/lib/tasks.py" "$@"
