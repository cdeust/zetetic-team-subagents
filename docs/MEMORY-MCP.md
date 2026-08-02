# Memory MCP server

A native MCP server exposing Anthropic's `memory_20250818` schema, backed by a local-FS implementation with scope-based ACL, atomic writes, audit log, async Cortex replica queue, and PII scrubbing.

## What it gives the agent

```python
# From within a Claude Code session, agents call:
memory.view(path="/memories/engineer/decisions.md")
memory.create(path="/memories/engineer/2026-04-25.md", file_text="...")
memory.str_replace(path="...", old_str="...", new_str="...")
memory.insert(path="...", insert_line=1, insert_text="...")
memory.delete(path="...")
memory.rename(old_path="...", new_path="...")
```

Plus a `memory_extensions` tool exposing `search` (grep across scope), `scopes` (list), `preamble` (system-prompt preamble), `sync-status` / `drain-sync` / `commit-sync` / `release-sync` (Cortex replica queue), `ttl-sweep` (TTL eviction), `audit` (audit-log consumer).

## Architecture (one paragraph)

The MCP server is a thin Python stdio shim (`tools/memory-mcp-server.py`) that maps tool calls to subprocess invocations of `tools/memory-tool.sh`: a 1000-line Bash CLI that owns the contract. The CLI uses `mkdir`-based locks for portable mutual exclusion, atomic write-to-tmp+rename for durability, a JSON `scope-registry.json` for ACL, a `~/.claude/memories/.audit.log` append-only log for observability, and a `~/.claude/memories/.pending-sync/` directory for jobs queued to Cortex via `/session:memory-sync`.

## Enable in Claude Code / Desktop

The repo's `.mcp.json` registers the server automatically:

```json
{
  "mcpServers": {
    "memory": {
      "command": "python3",
      "args": ["tools/memory-mcp-server.py"],
      "env": {
        "MEMORY_AGENT_ID": "${MEMORY_AGENT_ID:-unknown}"
      }
    }
  }
}
```

If your MCP host doesn't auto-discover `.mcp.json`:

```bash
claude mcp add memory -- python3 tools/memory-mcp-server.py
```

Set `MEMORY_AGENT_ID` in your shell or MCP host env to the agent's slug: every write is attributed in the audit log under that ID. `scripts/spawn-agent.sh` exports this automatically.

## Smoke test

```bash
bash scripts/test-memory-mcp.sh
# Expected: 13 passed, 0 failed
```

## Verbatim error strings (Anthropic contract)

The CLI returns Anthropic's verbatim error strings. Claude is trained on these specific strings, and paraphrasing them degrades model behavior:

- `"File created successfully at: {path}"` / `"Error: File {path} already exists"`
- `"The memory file has been edited."`
- ``"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."``
- ``"Error: Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: [0, {n_lines}]"``
- `"Successfully deleted {path}"` / `"Successfully renamed {old_path} to {new_path}"`

Plus local-extension errors for path-traversal rejection and ACL denials. Full table in [`memory/contract.md`](../memory/contract.md) §3.

## Scope ACL

24 scopes declared in `memory/scope-registry.json` with `owners` (write list), `readers` (read list), `ttl_days`, and `max_file_kb`. Default: per-team-agent dedicated scope (engineer → `/memories/engineer/`); 97 genius agents share `/memories/genius/<slug>/` by subpath convention. Curator scopes (`global`, `lessons`) are write-locked to `_user` and the `orchestrator` agent.

`strict_unknown_scope: true`: writes to undeclared scopes are denied. Adding a new scope requires editing `scope-registry.json`.

## PII scrubbing

Every `create` / `str_replace` / `insert` runs through `pii-scanner.py` (or the persistent `pii-daemon.py` to amortize Python interpreter cold-start) before disk write. Matches against 14 calibrated regex classes (FPR=0%, FNR=0% on a 172-fixture corpus, verifiable via `bash scripts/test-memory-pii-expanded.sh`) plus a Shannon-entropy threshold (H > 4.5 bits/char) for high-confidence classes. Blocked writes emit a `pii_blocked` audit entry naming the matched class (never the matched bytes). Latency: scanner is sub-50ms on a ~10 KB payload in dev measurements; no committed benchmark has been published yet: `scripts/test-memory-pii.sh` reports the wall-clock per run when `MEMORY_PII_BENCHMARK=1` is set.

## Cortex replica queue

Every successful mutation enqueues a JSON job to `~/.claude/memories/.pending-sync/<ts>-<rand>.json`. The `/session:memory-sync` slash command drains the queue: for each job, calls `cortex:remember` with `agent_topic=<scope>` (which Cortex stores as `agent_context`, enabling `agent_briefing.py` to retrieve scope-tagged memories at SubagentStart). Local FS is the source of truth; Cortex is the eventually-consistent replica.

## Test totals

| Suite | Count | Purpose |
|---|---|---|
| `test-memory-e2e.sh` | 10 | I1–I10 invariants (durability, ACL, traversal, queue, TTL, audit) |
| `test-memory-concurrency.sh` | 6 | mkdir-lock + mv -n correctness |
| `test-memory-stale-lock.sh` | 3 | PID-liveness reclaim |
| `test-memory-mcp.sh` | 13 | JSON-RPC schema + propagation |
| `test-agent-id-propagation.sh` | 7 | spawn-site env-var wiring |
| `test-memory-pii.sh` | 30 | TP/TN/EDGE corpus |
| `test-memory-pii-expanded.sh` | 172 | 53 TP + 110 TN + edges |
| **Total** | **241** | |
