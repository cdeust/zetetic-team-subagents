"""Parse a `claude -p --output-format json` result line into the raw usage
fields this benchmark records. Pure functions only -- no subprocess calls
here (see runner.py for that), so this module is unit-testable in isolation.

Field names are taken from a live `claude -p --output-format json` invocation
(CLI 2.1.261, captured 2026-09-05) -- see docs/bench-agent-cost/README.md
"Provenance" section for the full sample payload this was verified against.
"""
from __future__ import annotations

from typing import Any


class MalformedCliOutputError(ValueError):
    """Raised when a `claude -p` JSON line is missing a field this benchmark
    depends on. Refusing to guess a default keeps a partial run from being
    silently recorded as a zero-cost run (§8: no invented constants)."""


REQUIRED_TOP_LEVEL_FIELDS = (
    "session_id",
    "total_cost_usd",
    "duration_ms",
    "duration_api_ms",
    "usage",
    "num_turns",
    "is_error",
    "subtype",
)

REQUIRED_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def extract_usage(cli_result: dict[str, Any]) -> dict[str, Any]:
    """Extract the raw usage/cost/timing fields this benchmark records from
    one `claude -p --output-format json` result object.

    Precondition: cli_result is the parsed JSON object from stdout of a
    single `claude -p --output-format json` invocation (subtype == "result"
    envelope, per CLI 2.1.261).
    Postcondition: returns a flat dict with exactly the fields the sidecar
    schema (docs/bench-agent-cost/README.md) declares. Raises
    MalformedCliOutputError if a required field is absent -- never fills in
    a placeholder.
    """
    missing = [f for f in REQUIRED_TOP_LEVEL_FIELDS if f not in cli_result]
    if missing:
        raise MalformedCliOutputError(f"missing top-level fields: {missing}")
    usage = cli_result["usage"]
    missing_usage = [f for f in REQUIRED_USAGE_FIELDS if f not in usage]
    if missing_usage:
        raise MalformedCliOutputError(f"missing usage fields: {missing_usage}")

    subagent_stats = cli_result.get("subagent_stats", {})

    return {
        "session_id": cli_result["session_id"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
        "cache_read_input_tokens": usage["cache_read_input_tokens"],
        "total_cost_usd": cli_result["total_cost_usd"],
        "duration_ms": cli_result["duration_ms"],
        "duration_api_ms": cli_result["duration_api_ms"],
        "num_turns": cli_result["num_turns"],
        "is_error": cli_result["is_error"],
        "subtype": cli_result["subtype"],
        "subagents_spawned": subagent_stats.get("spawned", 0),
    }


def total_tokens(usage_row: dict[str, Any]) -> int:
    """Sum of all four token-count fields -- the single scalar this
    benchmark uses as the primary compute-proxy metric (Move 6:
    tokens/wall-clock are cost proxies, never a carbon claim)."""
    return (
        usage_row["input_tokens"]
        + usage_row["output_tokens"]
        + usage_row["cache_creation_input_tokens"]
        + usage_row["cache_read_input_tokens"]
    )


def condition_matches_representation(usage_row: dict[str, Any], condition: str) -> bool:
    """Sanity check: did the run actually exercise the representation the
    condition name claims? A "subagent_spawn" run with zero spawned
    subagents, or an "inline_skill" run with one or more, means the prompt
    failed to produce the intended representation and the run must be
    discarded, not silently counted (Fisher discipline: the manipulation
    must have taken)."""
    spawned = usage_row["subagents_spawned"]
    if condition == "subagent_spawn":
        return spawned >= 1
    if condition == "inline_skill":
        return spawned == 0
    raise ValueError(f"unknown condition: {condition}")
