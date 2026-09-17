# Advisor loop

With a goal slug in `$ARGUMENTS`, read `.zetetic/goals/<slug>.md` and persist the
requested advisor selection in its `## Advisor` section. Preserve explicit model
and backend selections, including disabled or required consultation policy. Run
one `/zetetic:goal-loop <slug>` tick with that selection. Goal-loop owns the
consultation and the next phase; this command makes no separate advisor call.

Without a goal slug, resolve `advisor-model` with
`tools/skill-runner.sh advisor-model` and follow its standalone executor protocol.
Supply the decision question and relevant evidence. The executor retains ownership
and applies or rejects advice against that evidence.

This command adds no scheduler. Under an available `/loop`, each tick reads the
persisted goal and consultation records. On other hosts, use the portable
`advisor-model` skill with the goal file and then its next eligible goal skill.

$ARGUMENTS
