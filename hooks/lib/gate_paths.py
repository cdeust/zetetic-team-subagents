"""Where the gate's modules find the async-task layer (tools/lib/tasks.py, task_store.py).

Importing this module puts ``tools/lib`` on ``sys.path`` and loads ``task_store`` (re-exported below: use
``gate_paths.task_store``); import it BEFORE ``tasks``.
The gate modules import each other by bare name (hooks/lib is on the path), so the plugin root is
derived from this file's own location.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "tools", "lib"))
import task_store  # noqa: E402

__all__ = ["HERE", "PLUGIN_ROOT", "task_store"]
