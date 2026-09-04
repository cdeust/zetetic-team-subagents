#!/usr/bin/env python3
"""Blind quality scoring: two independent evaluator configurations score
each run's result_text against the task's fixed rubric, without being told
which condition (inline_skill / subagent_spawn) produced it.

Honesty caveat (must appear in every report using this script's output,
per README.md "Evaluator limitation"): these are LLM-judge evaluators, not
trained human reviewers. Zheng et al. 2023 ("Judging LLM-as-a-Judge with
MT-Bench and Chatbot Arena", arXiv:2306.05685) report GPT-4-as-judge
agreement with human preference at ~80-85% on MT-Bench -- meaningful but not
equivalent to human judgment. This benchmark uses two *differently
configured* judge calls (different model tier, different prompt phrasing)
as its two "evaluators" because no human evaluator labor is available in
this harness's execution context; it does not claim LLM-judge scores carry
the same evidentiary weight the design doc's Move 5 assigns to human blind
review, and any report built on this script's output must say so.

Usage:
  tools/bench-agent-cost/score_quality.py --raw-dir docs/bench-agent-cost/20260905/raw \\
      --task tasks/review_small_diff.json --out-dir docs/bench-agent-cost/20260905/scored
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EVALUATOR_CONFIGS = [
    {
        "id": "eval_a",
        "model": "haiku",
        "phrasing": "You are a strict technical reviewer scoring a work product against a fixed rubric.",
    },
    {
        "id": "eval_b",
        "model": "sonnet",
        "phrasing": "You are auditing whether a deliverable satisfies each rubric criterion, one at a time.",
    },
]


def strip_condition_leakage(text: str) -> str:
    """Best-effort redaction of phrases that would de-blind the evaluator
    (e.g. the work product narrating that it delegated to a subagent).
    This is a defense-in-depth measure, not the primary blinding mechanism
    -- the primary mechanism is that the evaluator prompt never states the
    condition and is only ever given result_text, never the sidecar."""
    patterns = [
        r"\bAgent tool\b", r"\bsubagent\b", r"\bdelegat\w*\b",
        r"\bcode-reviewer\b", r"\btest-engineer\b", r"\bengineer subagent\b",
        r"\binline\b", r"\bskill procedure\b",
    ]
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, "[redacted]", redacted, flags=re.IGNORECASE)
    return redacted


def build_judge_prompt(evaluator: dict, rubric: list[dict], blinded_text: str) -> str:
    criteria_lines = "\n".join(f"- {c['id']} ({c['points']} pts): {c['criterion']}" for c in rubric)
    return (
        f"{evaluator['phrasing']}\n\n"
        "Below is a work product. Score it against each rubric criterion. "
        "For each criterion, answer true only if the work product clearly satisfies it. "
        "Respond with ONLY a JSON object mapping each criterion id to true or false, "
        "no other text.\n\n"
        f"Rubric:\n{criteria_lines}\n\n"
        f"Work product:\n---\n{blinded_text}\n---\n"
    )


def invoke_judge(*, repo_root: str, prompt: str, model: str) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--effort", "low", "--allowed-tools", "", "--permission-mode", "bypassPermissions"]
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def parse_verdict(raw_result_text: str) -> dict:
    match = re.search(r"\{.*\}", raw_result_text, re.S)
    if not match:
        raise ValueError(f"judge did not return a JSON object: {raw_result_text!r}")
    return json.loads(match.group(0))


def score_one_run(*, run_record: dict, rubric: list[dict], repo_root: str) -> dict:
    blinded = strip_condition_leakage(run_record["result_text"])
    scores = {}
    for evaluator in EVALUATOR_CONFIGS:
        prompt = build_judge_prompt(evaluator, rubric, blinded)
        cli_result = invoke_judge(repo_root=repo_root, prompt=prompt, model=evaluator["model"])
        verdict = parse_verdict(cli_result.get("result", ""))
        points_by_id = {c["id"]: c["points"] for c in rubric}
        total = sum(points_by_id[cid] for cid, met in verdict.items() if met and cid in points_by_id)
        scores[evaluator["id"]] = {"verdict": verdict, "total_points": total}
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    task = json.loads(args.task.read_text(encoding="utf-8"))
    rubric = task["rubric"]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = str(Path(args.repo_root).resolve())

    raw_files = sorted(args.raw_dir.glob(f"{task['task_id']}_*.json"))
    if not raw_files:
        print(f"no raw runs found for task {task['task_id']} under {args.raw_dir}", file=sys.stderr)
        return 1

    for raw_path in raw_files:
        run_record = json.loads(raw_path.read_text(encoding="utf-8"))
        print(f"scoring {raw_path.name} ...")
        scores = score_one_run(run_record=run_record, rubric=rubric, repo_root=repo_root)
        out_path = args.out_dir / raw_path.name.replace(".json", ".scored.json")
        out_path.write_text(json.dumps(scores, indent=2), encoding="utf-8")
        for eval_id, s in scores.items():
            print(f"  {eval_id}: {s['total_points']}/{task['rubric_max_points']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
