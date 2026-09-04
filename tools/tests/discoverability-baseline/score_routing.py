#!/usr/bin/env python3
"""Discoverability baseline (Phase 3): measure routing precision/recall of
a router against rules/skill-routing-table.md's 15 GOA shapes, using the
hand-labeled corpus in labeled_prompts.json.

This is the primary discoverability signal per the plan's Phase 3 note: a
raw "was the genius agent file read" count proves nothing about whether it
was the RIGHT file for the prompt. Precision/recall against ground-truth
labels does.

The router itself (route_with_claude) is a live `claude -p` call and is
therefore NOT part of the pytest suite (tools/tests/discoverability-baseline/
run-tests.sh below tests only the pure scoring math against synthetic
predictions). Run this script directly to produce the real baseline:

  tools/tests/discoverability-baseline/score_routing.py --repo-root .
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent

# Type aliases so a signature with two id->id maps reads as one parameter
# per map, not one per internal comma (coding-standards §4.4).
IdToShape = dict[str, str]


def load_corpus() -> dict:
    return json.loads((HERE / "labeled_prompts.json").read_text(encoding="utf-8"))


def load_routing_table_text(repo_root: Path) -> str:
    return (repo_root / "rules" / "skill-routing-table.md").read_text(encoding="utf-8")


def build_router_prompt(routing_table_text: str, prompt_text: str, shape_ids: list[str]) -> str:
    return (
        "You are a router. Below is a routing table of 15 problem shapes with descriptions. "
        "Given a user request, output ONLY the single shape id that best matches it, or the "
        "literal word 'none' if no shape genuinely applies. No other text.\n\n"
        f"{routing_table_text}\n\n"
        f"Valid ids: {', '.join(shape_ids)}\n\n"
        f"User request: {prompt_text}\n"
    )


@dataclass(frozen=True)
class RouterQuery:
    """Parameter object for route_with_claude (coding-standards §4.4: more
    than 4 parameters is a missing data type)."""
    repo_root: Path
    prompt_text: str
    routing_table_text: str
    shape_ids: list[str]
    model: str


def route_with_claude(query: RouterQuery) -> str:
    prompt = build_router_prompt(query.routing_table_text, query.prompt_text, query.shape_ids)
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", query.model,
           "--effort", "low", "--allowed-tools", "", "--permission-mode", "bypassPermissions"]
    result = subprocess.run(cmd, cwd=str(query.repo_root), capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout).get("result", "").strip()
    match = re.search(r"[a-z-]+", raw)
    candidate = match.group(0) if match else raw
    return candidate if candidate in query.shape_ids else "none"


def precision_recall(predictions: IdToShape, labels: IdToShape, shape_ids: list[str]) -> dict:
    """Precondition: predictions and labels are keyed by the same prompt
    ids. Postcondition: per-shape precision/recall/F1 plus overall accuracy.
    A shape with zero predicted or zero true instances reports None rather
    than a divide-by-zero-masking 0.0 (an unscored shape is not the same
    fact as a perfectly-missed shape)."""
    per_shape = {}
    for shape in shape_ids:
        tp = sum(1 for pid in labels if predictions.get(pid) == shape and labels[pid] == shape)
        fp = sum(1 for pid in labels if predictions.get(pid) == shape and labels[pid] != shape)
        fn = sum(1 for pid in labels if predictions.get(pid) != shape and labels[pid] == shape)
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) > 0 else None
        per_shape[shape] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}

    correct = sum(1 for pid in labels if predictions.get(pid) == labels[pid])
    accuracy = correct / len(labels) if labels else None
    return {"per_shape": per_shape, "accuracy": accuracy, "n": len(labels)}


def route_all(corpus: dict, repo_root: Path, model: str) -> IdToShape:
    routing_table_text = load_routing_table_text(repo_root)
    shape_ids = corpus["shape_ids"]
    predictions: IdToShape = {}
    for p in corpus["prompts"]:
        query = RouterQuery(
            repo_root=repo_root, prompt_text=p["text"],
            routing_table_text=routing_table_text, shape_ids=shape_ids, model=model,
        )
        pred = route_with_claude(query)
        predictions[p["id"]] = pred
        marker = "OK" if pred == p["label"] else "MISS"
        print(f"  [{marker}] {p['id']}: predicted={pred!r} label={p['label']!r}")
    return predictions


def print_report(report: dict) -> None:
    print(f"\nOverall accuracy: {report['accuracy']:.3f} (n={report['n']})")
    for shape, m in report["per_shape"].items():
        if m["tp"] + m["fp"] + m["fn"] == 0:
            continue
        print(f"  {shape}: precision={m['precision']} recall={m['recall']} f1={m['f1']} "
              f"(tp={m['tp']} fp={m['fp']} fn={m['fn']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    corpus = load_corpus()
    labels = {p["id"]: p["label"] for p in corpus["prompts"]}

    predictions = route_all(corpus, repo_root, args.model)
    report = precision_recall(predictions, labels, corpus["shape_ids"])
    print_report(report)

    if args.out:
        args.out.write_text(json.dumps({"predictions": predictions, "report": report}, indent=2), encoding="utf-8")
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
