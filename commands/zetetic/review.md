# Quick Review

Review of the staged changes with Claude Code's native commands, not a home-made procedure.

## Instructions

1. Run `/code-review` on the staged diff (`git diff --cached`).
2. Run `/security-review` on the same diff.
3. One run each, one cycle: apply what they report and the review is over. No second round.

$ARGUMENTS
