# Zetetic Reasoning

A portable evidence-synthesis slice for Codex and Gemini CLI. It contains one
skill and eight compact, sourced reasoning references. It does not execute
commands or install background components.

## Install in Codex

```bash
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-reasoning@zetetic-marketplace
```

## Install in Gemini CLI

Install the skill directly from the repository:

```bash
gemini skills install https://github.com/cdeust/zetetic-team-subagents.git \
  --path plugins/zetetic-reasoning/skills/evidence-synthesis
```

From a local clone, the package can also be installed as an extension:

```bash
gemini extensions install ./plugins/zetetic-reasoning
```

## Scope

The package supports evidence synthesis only. It asks the host to inspect
primary sources, distinguish observation from inference, expose the strongest
counter-evidence, state uncertainty and refuse a conclusion when verification
is impossible. It does not provide automated enforcement or the repository's
larger agent roster.
