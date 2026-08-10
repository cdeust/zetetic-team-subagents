# features/ — the only thing the owner has to write

Drop a Markdown file here describing what you want. One file, one feature. Nothing else is
required of you: no plan, no ticket, no scoping session.

`/loop /zetetic:engineering-loop` picks up the oldest file with no `## Delivered` section, runs
the whole cycle unattended — recall, refine, implement, verify, benchmark, review, remember —
and appends `## Delivered` with the pull request link, the measured evidence, and every judgment
call it made. That section is what you read when you come back.

The loop surfaces before that only when the request is ambiguous in a way that changes the work.
Everything else it resolves itself, and it denies its own output before you ever see it if the
work is below the standard in the loop definition.

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
