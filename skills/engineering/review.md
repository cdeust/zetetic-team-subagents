---
name: review
description: >
  Code review enforcing Clean Architecture, SOLID principles, layer boundary integrity,
  and the zetetic standard — every violation cites the specific principle and code location.
category: engineering
trigger: >
  When a PR needs review; when code has changed and nobody has checked architectural integrity;
  when "it works in tests" is the only defense for a merge.
agents:
  - popper
  - simon
shapes: []
input: A PR, a diff, or a set of changed files to review.
output: >
  Review report: violations by category (layer, SOLID, anti-pattern, security), each with
  file:line, principle violated, and suggested fix.
zetetic_gate:
  logical: "Every violation must cite the specific principle"
  critical: "Review the actual code, not the description of the code"
  rational: "Severity proportional to consequence — critical-path bugs > style nits"
  essential: "Flag only what matters; do not generate noise"
composes: []
aliases: [code-review, pr-review]
hand_off:
  security_finding: "/secure — taleb does a deep dive"
  architecture_violation: "/decompose — simon proposes restructuring"
  correctness_doubt: "/prove-correct — dijkstra verifies the logic"
---

## Purpose

Review code changes for Clean Architecture violations (wrong dependency direction, core importing infrastructure), SOLID violations (god classes, LSP breaks, leaky abstractions), anti-patterns (swallowed errors, untyped dicts, dead code), and security issues. Every finding cites the principle and the exact code location.

## Procedure

The review is Claude Code's own, not one written for this skill: run `/code-review` on the diff (correctness, Clean Architecture and SOLID layer integrity), then `/security-review` (security). One run each, one cycle. Apply what they report and the review is over: no second round.

The genius patterns in `agents:` (popper, simon) govern the code while it is written, not a longer review: the delegate that writes the change applies them, and the change respects the published method they carry.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Every finding cites the principle | Remove findings without a principle |
| Critical | Review the actual diff, not the PR description | Re-read the code if review was summary-based |
| Rational | Critical-path findings before style nits | Reorder by severity |
| Essential | No noise — only actionable findings | Cut findings that don't affect correctness or maintainability |

## Output Format

The unmodified output of `/code-review` and `/security-review`: findings with file:line, then the author's list of what was applied.

## Anti-patterns

- Reviewing the PR description instead of the code.
- "LGTM" without reading the diff.
- Style nits drowning out real issues.
- Findings without a cited principle ("this feels wrong" is not a review).
