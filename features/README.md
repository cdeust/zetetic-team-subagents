# features/ — the only thing the owner has to write

Drop a Markdown file here describing what you want. One file, one feature. Nothing else is
required of you: no plan, no ticket, no scoping session.

`/loop /zetetic:engineering-loop` picks up the oldest file with no `## Delivered` section, runs
the whole cycle unattended — recall, refine, implement, verify, benchmark, review, remember —
and appends `## Delivered` with the pull request link, the measured evidence, and the proof the
feature runs in the ecosystem. That section is what you read when you come back.

**There is one accepted outcome: the feature built and working.** Not a partial feature, not a
design proposal, not a question about what you meant. Ambiguity is resolved from the surrounding
code, not handed back. The loop denies its own output before you ever see it when the work is
below the standard, and keeps going until it is not.

The only thing that stops it is something only you can supply — a credential, an access, an
authority. Nothing else.

## What to write

Whatever makes the intent unambiguous. A paragraph is usually enough. What helps most:

- what the feature does, from the outside
- what "working" looks like — the signal you would check
- anything explicitly out of scope

## Example

```markdown
# Incremental re-index on file save

When a watched file changes, re-index only that file and the edges that touch it, instead of
re-indexing the repository. Working means: a single-file edit produces the same graph as a full
re-index of the same tree, measured on this repo, and takes under a second.

Out of scope: watching the filesystem — the trigger already exists.
```
