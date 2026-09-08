# CMA facilitator agents: enterprise pilot engagements

Phase A of [issue #26](https://github.com/cdeust/zetetic-team-subagents/issues/26)
("enterprise: CMA facilitator agents"). Version-controlled manifests for the
4 Claude Managed Agents (CMA) that carry the meta-work of a Claude Code
enterprise pilot engagement, plus the shared environment they attach to.

## Architecture: two planes, no overlap

The engagement runs on two distinct planes, decided in the issue #26
"Architecture finale" comment (2026-07-15):

1. The field (local, at the client site): the architect brings the
   zetetic-team-subagents roster and the Cortex/zetetic ecosystem, installed
   locally at the client under the Claude Enterprise edition. This plane does
   the actual engineering work. Nothing about it changes here, no agent is
   ported to CMA.
2. The engagement's meta-work (CMA, server-side): 4 small, specialized,
   versioned facilitator agents that handle the steps the field plane
   should not carry: reporting, analysis, fleet health, and security audit.

| Facilitator | Handles | CMA capability exploited |
|---|---|---|
| `reporting` | Scorecards and readouts from exported OTel/Admin data | scheduled deployment (weekly cron); outcome rubric on the readout; `.xlsx`/`.docx` deliverables via skills |
| `analysis` | Baseline/adoption diagnosis: cohorts, chasm, common- vs special-cause variation | engagement memory store (baseline, decision history); Console-traced sessions |
| `agent-management` | Deployed-fleet health: plugin/marketplace version drift, config drift vs managed templates, inventory | versioned agent + `github_repository` mount of the client's config repo; webhooks (ASSUMED: no webhook is wired in this phase, listed as a candidate CMA capability for drift-alert notification, to validate in Phase B) |
| `security-data-audit` | Security questionnaire, MCP governance, data-surface/retention audit | outcome-rubric-gradable checklist; versioned memory store + redact |

Why this split: the local plane keeps what no CMA agent can offer (full
roster, worktrees, hooks, Cortex); CMA offers what the local plane cannot
(autonomous cron, org-side versioned objects, sessions the client can see in
their own Console, gradable outcomes, a durable and redactable per-engagement
memory). The facilitators are also billable pilot deliverables: the client
sees the reporting/audit sessions in their Console, not an internal cost.

## Interim memory mechanism (Phase A): native CMA memory stores

Per the issue's priority-ordering comment (2026-07-15): facilitator memory
uses **native CMA memory stores** (FUSE-mounted, versioned, redactable) for
this phase. The centralized cross-engagement memory (Cortex#144) and the
`cortex-relay` MCP bridge (Cortex#151) come later, in that dependency order.
None of the 4 manifests declare `mcp_servers`; this is deliberate, not an
oversight. When the relay ships, migrating a facilitator to it is an
`ant beta:agents update` adding an `mcp_servers` entry and a vault, not a
manifest rewrite.

## Manifest layers (Phase B)

Phase B verification against the SDK (`anthropic` 0.116, `types/beta/*.py`)
and the API reference (platform.claude.com/docs/en/api/beta) showed that
memory stores, vaults, resources and schedules are **first-class workspace
objects attached to deployments**, not environment fields (issue #26,
mapping comment, 2026-07-16). The manifests are layered accordingly:

| File | API object | Verified against |
|---|---|---|
| `*.agent.yaml` | agent (versioned) | CreateAgent schema (Phase A) + SDK `agent_create_params.py` |
| `pilot.environment.yaml` | environment (create-once) | SDK `environment_create_params.py`; **created live** as `env_01EDqGQaZ6NeQV8X8VakKnUn` (2026-07-16) |
| `pilot.engagement.yaml` | memory stores + vaults (per engagement) | SDK `memory_store_create_params.py`, `vault_create_params.py` |
| `*.deployment.yaml` | deployments (one per facilitator) | SDK `deployment_create_params.py` + docs `/v1/deployments` |

## Deployment flow: `deploy.py`

```bash
# Compile every manifest and print the exact payloads (no API calls, no key)
python3 enterprise/managed-agents/deploy.py --dry-run

# Deploy for real (idempotent: create-once or versioned update, never delete)
export ANTHROPIC_API_KEY=...   # only accepted via the environment
python3 enterprise/managed-agents/deploy.py
```

`deploy.py` upserts in dependency order: environment, agents, memory
stores + vaults, then deployments, and resolves the **names** used in
`*.deployment.yaml` (`agent`, `environment`, `resources[].memory_store`,
`vaults[]`) to live IDs at deploy time, pinning each deployment to the
agent version current at that moment. Re-running it re-pins; a deployment
whose prerequisites failed is skipped with an explicit finding, never
half-created.

Each manifest stays the single source of truth for its object: do not
hand-edit an agent or deployment through the Console once it is under
version control here; edit the YAML and re-run `deploy.py`.

### Memory store and vault per engagement

`pilot.engagement.yaml` declares the per-engagement objects: one shared
memory store (`pilot-engagement`) that every facilitator deployment mounts
via its `resources[]` block, and one credential vault
(`pilot-engagement-data-access`) referenced by the deployments that read
client data (`agent-management`, `security-data-audit`). Credential
**values** are registered out-of-band against the vault (secret values are
write-only in the API), never embedded in an agent's `system` prompt,
never committed to this repository. At the start of a new engagement, copy
the file with a new engagement prefix.

### Scheduled deployment (reporting)

`reporting` is the one facilitator whose job repeats on a clock; see the
`schedule` block in `reporting.deployment.yaml` (5-field POSIX cron +
IANA timezone, weekly Monday 08:00 Europe/Paris). The weekly cadence
exists so a scorecard/readout draft is already sitting in
`/mnt/session/outputs/` before the consultant or sponsor asks for it. The
other three facilitators deploy without a schedule and are fired on demand
via `POST /v1/deployments/{id}/run` (their kickoff events are versioned in
their `*.deployment.yaml`). Note: a deployment's `initial_events` are
replayed verbatim on every run: kickoff text uses relative dates only.

## PoC criteria: Phase B (in progress)

Phase B validates the 3 facilitators whose capabilities are most novel
against a real CMA workspace:

(a) **reporting**: a scheduled deployment fires on cron against a test
    OTel data export, produces a `.docx` readout, and the readout satisfies
    a defined outcome rubric.
(b) **agent-management**: a deliberate version drift is introduced into a
    test config repository; the facilitator detects it and reports it with
    the field/expected/actual evidence format its system prompt requires.
(c) **security-data-audit**: the governance checklist runs against a test
    environment with a known-good and a known-bad `managed-settings.json`
    (once with `allowManagedMcpServersOnly: true`, once without) and
    correctly flags the difference.

Phase B status (2026-07-16, first live run; see the issue #26 run
comment): the `pilot` environment was **created live**
(`env_01EDqGQaZ6NeQV8X8VakKnUn`); the 4 agent creates were rejected with
HTTP 400 "credit balance too low": a billing gate, not a schema
verdict. By decision, no credit top-up happens before a pilot client is
signed, so live CreateAgent validation is deferred to the first pilot
engagement. The deployment/memory-store/vault layer compiles against the
verified SDK schemas (`--dry-run`) but has not been exercised live.
None of (a)-(c) has completed; they run as day-one steps of the first
pilot, funded by it.

## Phase C (later)

Integration into the pilot offer: which facilitators ship by default in a
standard pilot, and how they are priced.
