#!/usr/bin/env python3
"""Scope ACL decisions and scope statistics for tools/memory-tool.sh.

  memory_acl.py check <registry> <scope> <read|write> <agent>
      prints `allow` or `deny`.
  memory_acl.py scopes <registry-or-empty> <agent> <scope-dir> [<scope-dir> ...]
      prints one line per directory, in the order given:  FILES<TAB>BYTES<TAB>ACCESS
      with ACCESS one of rw | r | w | none. An empty registry path means no
      registry: everything is allowed (first-run convenience).

Why one process for all scopes: `memory-tool.sh scopes` used to spawn two
python interpreters and two `find`s per scope. With 38 scopes and 1800 files it
cost 4.4 s of the SessionStart hook (measured 2026-10-14, 3 s limit); one
process computes the same numbers.

Contract (ACL): a read consults the scope's `readers`, a write its `owners`; a
scope absent from the registry takes `defaults`, and under
`strict_unknown_scope` a write to it is denied.
"""

import json
import os
import sys


def _matches(ids, agent, curators):
    for entry in ids:
        if entry == "*" or entry == agent:
            return True
        if entry == "_curator" and agent in curators:
            return True
        if entry == "_user" and agent == "_user":
            return True
    return False


def allowed(registry, scope, access, agent):
    """True when `agent` may `access` (read|write) `scope` under `registry`."""
    curators = set(registry.get("curator_agents", []))
    defaults = registry.get("defaults", {"owners": ["_user"], "readers": ["*"]})
    entry = registry.get("scopes", {}).get(scope)
    if entry is None:
        if registry.get("strict_unknown_scope", False) and access == "write":
            return False
        entry = defaults
    ids = entry.get("owners", []) if access == "write" else entry.get("readers", [])
    return _matches(ids, agent, curators)


def scope_stats(directory):
    """(file count, total bytes) of regular, non-dot-named files below `directory`.

    Same set as `find DIR -type f ! -name '.*'`: symlinks are not followed and
    dot-named files are skipped, but files inside dot-named directories count.
    """
    files = size = 0
    for here, _dirs, names in os.walk(directory):
        for name in names:
            path = os.path.join(here, name)
            if name.startswith(".") or os.path.islink(path):
                continue
            try:
                size += os.stat(path).st_size
            except OSError:  # FAILS_ON: file removed between listing and stat
                continue
            files += 1
    return files, size


def _access(registry, scope, agent):
    if registry is None:
        return "rw"
    can_read = allowed(registry, scope, "read", agent)
    can_write = allowed(registry, scope, "write", agent)
    return "rw" if can_read and can_write else "r" if can_read else "w" if can_write else "none"


def main(argv):
    if argv[0] == "check":
        with open(argv[1]) as handle:
            registry = json.load(handle)
        print("allow" if allowed(registry, argv[2], argv[3], argv[4]) else "deny")
        return 0
    registry_path, agent, directories = argv[1], argv[2], argv[3:]
    registry = None
    if registry_path:
        with open(registry_path) as handle:
            registry = json.load(handle)
    for directory in directories:
        scope = os.path.basename(directory.rstrip("/"))
        files, size = scope_stats(directory)
        print(f"{files}\t{size}\t{_access(registry, scope, agent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
