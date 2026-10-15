#!/usr/bin/env python3
"""ttl-sweep and audit helpers of tools/memory-tool.sh.

  memory_admin.py ttl-pairs <registry>         "scope ttl_days" lines for scopes with a TTL
  memory_admin.py since <iso8601>              epoch seconds of an --since value (exit 1 if invalid)
  memory_admin.py audit-report <log> <cutoff>  the audit log of the window + summary + anomalies

Extracted verbatim from the heredocs of memory-tool.sh, which could not stay
inside the function-size limit. Output is unchanged byte for byte.
"""

import collections
import datetime
import json
import os
import sys

READ_ONLY_COMMANDS = ("view", "search", "scopes", "preamble", "sync-status")
SINCE_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S")
WRITES_PER_HOUR_ANOMALY = 50  # source: memory-tool.sh audit, behaviour preserved from the heredoc
SCOPES_PER_AGENT_ANOMALY = 3  # source: same
CONSECUTIVE_DENIALS_ANOMALY = 5  # source: same


def ttl_pairs(registry_path):
    """Print "scope ttl_days" for scopes with a non-null TTL, then the default-TTL scopes."""
    with open(registry_path) as handle:
        reg = json.load(handle)
    scopes = reg.get("scopes", {})
    for name, entry in scopes.items():
        ttl = entry.get("ttl_days")
        if ttl is not None:
            print(f"{name} {int(ttl)}")
    # Scopes without an explicit TTL key inherit the defaults block's TTL.
    default_ttl = reg.get("defaults", {}).get("ttl_days")
    if default_ttl is not None:
        mem_root = os.environ.get("MEMORY_ROOT", os.path.expanduser("~/.claude/memories"))
        for d in os.scandir(mem_root):
            if d.is_dir() and not d.name.startswith(".") and d.name not in scopes:
                print(f"{d.name} {int(default_ttl)}")


def since_epoch(value):
    """Epoch seconds (UTC) of `value`, trying the accepted formats; None if none fits."""
    for fmt in SINCE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(value, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        return int(parsed.timestamp())
    return None


def read_entries(log_path, cutoff):
    """Parse the tab-separated audit log; keep well-formed entries at or after `cutoff`."""
    entries = []
    with open(log_path) as handle:
        for raw in handle:
            raw = raw.rstrip("\n")
            parts = raw.split("\t")
            if not raw or len(parts) < 8:
                continue
            ts_str, agent, scope, cmd, vpath, bytes_s, sha, result = parts[:8]
            try:
                stamp = datetime.datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
                epoch = int(stamp.replace(tzinfo=datetime.timezone.utc).timestamp())
            except ValueError:
                continue
            if epoch < cutoff:
                continue
            entries.append({
                "ts": ts_str, "epoch": epoch, "agent": agent, "scope": scope,
                "cmd": cmd, "vpath": vpath, "bytes": int(bytes_s or 0),
                "sha": sha, "result": result,
            })
    return entries


def scope_limits(reg_path):
    """{scope: max_file_kb} from the registry; empty when there is no registry."""
    limits = {}
    if reg_path and os.path.isfile(reg_path):
        with open(reg_path) as handle:
            reg = json.load(handle)
        defaults_kb = reg.get("defaults", {}).get("max_file_kb", 100)
        for sname, sentry in reg.get("scopes", {}).items():
            limits[sname] = sentry.get("max_file_kb", defaults_kb)
    return limits


def large_files(scope_dir, max_kb):
    """(file, KB) of the files in `scope_dir` that reach 90% of `max_kb`."""
    for fname in os.listdir(scope_dir):
        fpath = os.path.join(scope_dir, fname)
        if not os.path.isfile(fpath):
            continue
        kb = os.path.getsize(fpath) / 1024
        if kb >= max_kb * 0.9:
            yield fname, kb


def files_near_limit():
    """(scope, file, KB, max KB) of files within 10% of their scope's max_file_kb."""
    try:
        limits = scope_limits(os.environ.get("MEMORY_REGISTRY", ""))
        mem_root = os.environ.get("MEMORY_ROOT", os.path.expanduser("~/.claude/memories"))
        near = []
        for sname, max_kb in limits.items():
            scope_dir = os.path.join(mem_root, sname)
            if os.path.isdir(scope_dir):
                near.extend((sname, fname, kb, max_kb) for fname, kb in large_files(scope_dir, max_kb))
        return near
    except Exception:  # FAILS_ON: unreadable or malformed registry; the report is best effort
        return []


def print_log(entries):
    print(f"=== Audit log ({len(entries)} entries) ===")
    for e in entries:
        print(f"  {e['ts']}  {e['agent']:20s}  {e['scope']:15s}  {e['cmd']:12s}  {e['result']:12s}  {e['vpath']}")


def print_summary(entries):
    writes = [e for e in entries if e["cmd"] not in READ_ONLY_COMMANDS]
    denials = [e for e in entries if e["result"] == "acl_denied"]
    by_agent_bytes = collections.Counter()
    for e in entries:
        by_agent_bytes[e["agent"]] += e["bytes"]
    near_limit = files_near_limit()
    print()
    print("=== Summary ===")
    print(f"  Total writes in window : {len(writes)}")
    print(f"  ACL denials            : {len(denials)}")
    if denials:
        denial_by = collections.Counter((e["agent"], e["scope"]) for e in denials)
        for (agent, scope), count in denial_by.most_common():
            print(f"    agent={agent} scope={scope} : {count}")
    print()
    print("  Top 5 agents by byte volume:")
    for agent, size in by_agent_bytes.most_common(5):
        print(f"    {agent:30s}  {size:>10d} bytes")
    if near_limit:
        print()
        print("  Files within 10% of max_file_kb:")
        for sname, fname, kb, max_kb in near_limit:
            print(f"    /memories/{sname}/{fname}  {kb:.1f}KB / {max_kb}KB limit")


def burst_anomalies(entries):
    """A scope with more than 50 writes inside one rolling hour."""
    found = []
    bucket = collections.defaultdict(list)
    for e in entries:
        if e["cmd"] not in READ_ONLY_COMMANDS:
            bucket[e["scope"]].append(e["epoch"])
    for scope, epochs in bucket.items():
        epochs.sort()
        for i, start in enumerate(epochs):
            window = [t for t in epochs[i:] if t - start <= 3600]
            if len(window) > WRITES_PER_HOUR_ANOMALY:
                when = datetime.datetime.fromtimestamp(start, datetime.timezone.utc).strftime("%H:%M:%SZ")
                found.append(f"  [ANOMALY] scope '{scope}': {len(window)} writes in 1-hour window starting {when}")
                break
    return found


def spread_anomalies(entries):
    """An agent writing to more than 3 different scopes."""
    agent_scopes = collections.defaultdict(set)
    for e in entries:
        if e["cmd"] not in READ_ONLY_COMMANDS:
            agent_scopes[e["agent"]].add(e["scope"])
    return [f"  [ANOMALY] agent '{agent}' wrote to {len(scopes)} scopes: {sorted(scopes)}"
            for agent, scopes in agent_scopes.items() if len(scopes) > SCOPES_PER_AGENT_ANOMALY]


def denial_anomalies(entries):
    """An agent with 5 consecutive acl_denied results."""
    found = []
    run = collections.defaultdict(int)
    for e in sorted(entries, key=lambda x: x["epoch"]):
        key = e["agent"]
        if e["result"] != "acl_denied":
            run[key] = 0
            continue
        run[key] += 1
        if run[key] == CONSECUTIVE_DENIALS_ANOMALY:
            found.append(f"  [ANOMALY] agent '{key}' has {run[key]} consecutive acl_denied (possible poisoning attempt)")
    return found


def print_anomalies(entries):
    anomalies = burst_anomalies(entries) + spread_anomalies(entries) + denial_anomalies(entries)
    print()
    if not anomalies:
        print("  No anomalies detected.")
        return
    print("=== Anomalies ===")
    for line in anomalies:
        print(line)


def audit_report(log_path, cutoff):
    entries = read_entries(log_path, cutoff)
    if not entries:
        print("No audit entries in the requested window.")
        return
    print_log(entries)
    print_summary(entries)
    print_anomalies(entries)


def main(argv):
    command = argv[0]
    if command == "ttl-pairs":
        ttl_pairs(argv[1])
    elif command == "since":
        epoch = since_epoch(argv[1])
        if epoch is None:
            print("error", file=sys.stderr)
            return 1
        print(epoch)
    elif command == "audit-report":
        audit_report(argv[1], int(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
