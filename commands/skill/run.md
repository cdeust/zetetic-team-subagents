# Run Skill

Execute a registered skill by name. The skill's procedure, zetetic gates, and output format guide the execution.

## Instructions

1. Parse: first word is the skill name, rest is the input/arguments.

2. Resolve the skill file: `tools/skill-runner.sh <skill-name>`
   If not found, list available skills and ask the user to choose.
   If the output opens with a `!!! MODEL-TIER ESCALATION REQUIRED !!!` banner, it names an agent whose declared `model:` tier exceeds this runner's baseline (sonnet). Spawn each named agent as a real subagent via the Agent tool before proceeding — do not read that agent's steps and execute them inline at this session's own tier. Inlining silently drops the capability upgrade the skill's author deliberately chose.

3. Read the resolved skill file. Follow its **Procedure** section step by step.

4. Before delivering output, check every **Zetetic Gate**. If any gate fails, report the failure and stop — do not produce partial output that bypasses a gate.

5. After output, check the **Hand-offs** section. If a hand-off condition is met, suggest the next skill to the user.

$ARGUMENTS
