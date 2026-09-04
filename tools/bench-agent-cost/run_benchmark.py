#!/usr/bin/env python3
"""Paired cost/quality benchmark harness -- Phase 3 of
/Users/cdeust/.claude/plans/staged-rolling-shannon.md.

Runs, for one task, N paired replications comparing two representations of
the same work (inline skill execution vs. full subagent spawn), with
everything else held constant: same model, effort, tool grant, and git
snapshot. Order is randomized per replication (Fisher discipline). Each run
writes its raw usage JSON and a provenance sidecar to disk immediately, so a
killed process loses at most the in-flight run (contract: "design long work
so that dying costs one step, not the whole run").

Usage:
  tools/bench-agent-cost/run_benchmark.py --task tasks/review_small_diff.json \\
      --replications 5 --model haiku --effort low --out-dir docs/bench-agent-cost/20260905

See docs/bench-agent-cost/README.md for the pre-registered protocol this
implements and the reason a haiku/low smoke run is a distinct artifact from
the frozen sonnet/medium production protocol.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import prompts, provenance, usage as usage_lib  # noqa: E402

CONDITIONS = ("inline_skill", "subagent_spawn")
ALLOWED_TOOLS = "Read,Agent,Glob,Grep"


@dataclass(frozen=True)
class RunConfig:
    """Invocation-level settings held constant across every replication and
    condition (coding-standards §4.4 parameter object)."""
    repo_root: str
    out_dir: Path
    model: str
    effort: str
    seed: int


def load_task(task_path: Path) -> dict:
    with open(task_path, encoding="utf-8") as fh:
        return json.load(fh)


def run_key(task_id: str, replication: int, condition: str) -> str:
    return f"{task_id}::{replication}::{condition}"


def load_completed(out_dir: Path) -> set[str]:
    state_file = out_dir / "state.json"
    if not state_file.exists():
        return set()
    return set(json.loads(state_file.read_text(encoding="utf-8")))


def mark_completed(out_dir: Path, key: str) -> None:
    state_file = out_dir / "state.json"
    completed = load_completed(out_dir)
    completed.add(key)
    state_file.write_text(json.dumps(sorted(completed), indent=2), encoding="utf-8")


def build_prompt(task: dict, condition: str, repo_root: str) -> str:
    spec = prompts.TaskPromptSpec(
        repo_root=repo_root,
        skill_name=task["skill_name"],
        primary_agent=task["primary_agent"],
        task_instruction=task["task_instruction"],
        fixture_path=task["fixture_path"],
    )
    if condition == "inline_skill":
        return prompts.build_inline_prompt(spec)
    return prompts.build_subagent_prompt(spec)


def invoke_claude(prompt: str, config: RunConfig) -> dict:
    """Precondition: `claude` CLI on PATH. Postcondition: returns the parsed
    JSON result object from a single `claude -p --output-format json` call.
    Raises CalledProcessError on a non-zero exit -- a CLI failure is never
    silently recorded as a scoreless run."""
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", config.model,
        "--effort", config.effort,
        "--allowed-tools", ALLOWED_TOOLS,
        "--permission-mode", "bypassPermissions",
    ]
    result = subprocess.run(cmd, cwd=config.repo_root, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@dataclass(frozen=True)
class ReplicationStep:
    """Identifies one (task, replication, order-position, condition) cell
    of the design matrix (coding-standards §4.4 parameter object)."""
    task: dict
    replication: int
    position: int
    condition: str


def run_one_condition(step: ReplicationStep, config: RunConfig) -> None:
    key = run_key(step.task["task_id"], step.replication, step.condition)
    if key in load_completed(config.out_dir):
        print(f"  skip (already recorded): {key}")
        return

    prompt = build_prompt(step.task, step.condition, config.repo_root)
    print(f"  running: {key} (order position {step.position}/2)")
    cli_result = invoke_claude(prompt, config)
    usage_row = usage_lib.extract_usage(cli_result)
    matches = usage_lib.condition_matches_representation(usage_row, step.condition)

    identity = provenance.RunIdentity(
        task_id=step.task["task_id"], condition=step.condition, replication=step.replication,
        order_position="first" if step.position == 1 else "second",
        model=config.model, effort=config.effort, prompt_text=prompt, seed=config.seed,
    )
    sidecar = provenance.build_sidecar(repo_root=config.repo_root, identity=identity)

    record = {
        "provenance": sidecar,
        "usage_raw": usage_row,
        "representation_check_passed": matches,
        "result_text": cli_result.get("result", ""),
    }
    raw_dir = config.out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"{step.task['task_id']}_{step.condition}_rep{step.replication}.json"
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    mark_completed(config.out_dir, key)
    flag = "OK" if matches else "MISMATCH -- discard at analysis"
    print(f"    wrote {out_path} [{flag}]")


def run_one_replication(task: dict, replication: int, order: list[str], config: RunConfig) -> None:
    for position, condition in enumerate(order, start=1):
        run_one_condition(ReplicationStep(task, replication, position, condition), config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path, help="path to a tasks/*.json file")
    parser.add_argument("--replications", type=int, default=5)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--seed", type=int, default=20260905, help="RNG seed for A/B order randomization")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task = load_task(args.task)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    config = RunConfig(
        repo_root=str(Path(args.repo_root).resolve()), out_dir=args.out_dir,
        model=args.model, effort=args.effort, seed=args.seed,
    )

    print(f"Task: {task['task_id']} | replications={args.replications} | model={args.model} effort={args.effort}")
    for replication in range(1, args.replications + 1):
        order = list(CONDITIONS)
        rng.shuffle(order)
        print(f"replication {replication}: order = {order}")
        run_one_replication(task, replication, order, config)
    print(f"\nDone. Raw records + state.json under {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
