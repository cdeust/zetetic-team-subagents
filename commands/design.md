# Design

Run the `design` skill's UX/UI procedure: name the user/task/success-criterion, enforce
WCAG 2.2 AA from the first sketch, walk the 10 Nielsen heuristics, and refuse patterns that
defeat usability or research integrity.

## Not the host's native `/design`

Claude Code ships a separate, non-plugin, host-level `/design` capability that generates a
visual design canvas / artifact (a mockup-generation tool). This command is a **different job**,
not a competing implementation of the same one: this one produces a rigorous UX/UI audit and
design spec (named user, WCAG compliance plan, heuristic evaluation, refusal checks), not a
visual mockup. The two are complementary -- run the host's native canvas for a visual draft,
run this for the audit/spec discipline underneath it -- never presented as interchangeable.

They do not collide at the invocation level either: per Claude Code's plugin documentation
(Create plugins / Plugins reference, verified 2026-09-05, `docs.claude.com/en/docs/claude-code/
plugins[-reference]`), plugin commands are namespaced exactly like plugin skills --
`/<plugin-name>:<command-name>`, never bare -- specifically to prevent a plugin command from
conflicting with a host-native or another plugin's command of the same short name. This
plugin's name (`.claude-plugin/plugin.json`) is `zetetic-team-subagents`, so this command
resolves as `/zetetic-team-subagents:design`; the host's native `/design` remains a fully
separate, unnamespaced, non-overridable capability. Neither overrides the other.

## Instructions

1. Resolve the skill file: `tools/skill-runner.sh design`.
   If the output opens with a `!!! MODEL-TIER ESCALATION REQUIRED !!!` banner, spawn the named
   agent as a real subagent via the Agent tool instead of inlining -- but for this skill's
   current `agents:` list (`ux-designer`, `model: sonnet`, matching this runner's baseline) no
   banner should fire; if one does, the frontmatter has drifted and should be re-verified before
   proceeding.

2. Read the resolved skill file. Follow its **Procedure** section step by step against
   `$ARGUMENTS` (the screen, flow, component, or existing markup/design to design or audit).

3. Before delivering output, check every **Zetetic Gate** in the skill file. If any gate fails,
   report the failure and stop -- do not produce partial output that bypasses a gate.

4. Produce output in the skill's **Output Format** section. Check the **Hand-offs** section
   (`frontend-engineer` for implementation feasibility, `architect`+`alexander` for design-system
   architecture, `feynman` for research-integrity doubts, `arendt` for dark-pattern/ethics
   concerns) and suggest the next step if a hand-off condition is met.

5. For work that needs to survive this session's own compaction or needs an isolated context
   independent of this session's history (a long, multi-round accessibility audit spanning many
   files), spawn `ux-designer` as a real subagent via the Agent tool instead of running this
   command inline.

$ARGUMENTS
