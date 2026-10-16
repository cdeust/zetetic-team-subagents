# Public APIs reference

How to use the community list at <https://github.com/public-apis/public-apis> when a task
needs a free or public API: a prototype, test data, or research input.

**What it is.** A manually curated README of public APIs, grouped by category, plus a separate MCP-servers table.
Each API row has the columns `API | Description | Auth | HTTPS | CORS`. Licence: MIT.

**Measured at fetch time (2026-10-16, `gh api repos/public-apis/public-apis`):**
last push 2026-10-15T18:31:49Z, not archived, 489,209 stars. A recent push to the
repository says nothing about any single row: the list is community-maintained and rows
are not re-verified on a schedule. Re-measure these numbers instead of trusting them.

## When to use it

- You need a keyless or free-tier API to prototype against, or sample data for a test.
- You are searching for what exists in a domain (weather, geocoding, books, currency) and
  have no named provider yet.

Do not use it as evidence about an API. A row proves only that someone listed it once.
Do not use it when the task already names a provider, or for production dependencies.

## Procedure

1. Find the category in the README index and read only that section. Do not copy the
   list into the repository or into a prompt.
2. Shortlist by the columns. `Auth` is `No`, `apiKey` or `OAuth`; prefer `No` for
   throwaway work. `HTTPS` must be `Yes` for anything carrying user data. `CORS` is
   `Yes`, `No` or `Unknown`, and matters only for calls made from browser code; without
   CORS an API is usable server side only (CONTRIBUTING.md).
3. Verify the chosen API on its own official documentation before writing code against
   it: the endpoint exists, the response shape matches, and the documented Auth, HTTPS and
   CORS agree with the row. Rows go stale: an API can be dead, moved behind a key, or
   re-licensed. If the official docs and the row disagree, the docs win; say so.
4. Read its terms of use and rate limits. Check that your use (prototype, test data,
   research, redistribution of the data) is allowed, and that the limit fits the use.
5. Make one real request and record what came back (status, a trimmed body). A call
   that fails is a result: pick the next candidate, do not mock the response.
6. Keep keys out of code and commits. Read them from the environment or a secrets store,
   add the variable name (not the value) to the example env file, and never paste a key
   into a command, log or PR body.

## Reporting

Name the API, its official docs URL, the date you verified it, and what you ran. State
that the selection came from the community list and was then checked at the source.
