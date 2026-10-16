# Public APIs reference

How to use the community list at <https://github.com/public-apis/public-apis> when a task
needs a free or public API: a prototype, test data, or research input.

**What it is.** A manually curated README (2,655 lines when measured on 2026-10-16) of
public APIs grouped by category. Licence: MIT. Three kinds of table share it, with
different columns:

- Category tables (after `## Index`): `API | Description | Auth | HTTPS | CORS`. Only these
  feed the free shortlist.
- `## APILayer APIs` (near the top, sponsored): `API | Description | Call this API`. No
  `Auth`, `HTTPS` or `CORS` column; these are the vendor's commercial products and need an
  APILayer key. Warning: exclude them from the free shortlist.
- `## MCP Servers`: `Name | Description | Auth | Transport | Install`. These are installed
  into an MCP client, not called over HTTP, so the HTTPS and CORS rules below do not apply
  to them (public-apis/public-apis CONTRIBUTING.md, "MCP Servers").

Rows are community-maintained and not re-verified on a schedule. Measure repository
liveness yourself instead of trusting a recorded number:
`gh api repos/public-apis/public-apis --jq '{pushed_at,archived,stargazers_count}'`.

## When to use it

- You need a keyless or free-tier API to prototype against, or sample data for a test.
- You are searching for what exists in a domain (weather, geocoding, books, currency) and
  have no named provider yet.

Do not use it as evidence about an API. A row proves only that someone listed it once.
Do not use it when the task already names a provider, or for production dependencies.

## Procedure

1. Find the category without loading the whole README into context. Download the raw file
   to a scratch file and read one section:
   `gh api repos/public-apis/public-apis/contents/README.md --jq .content | base64 -d > "$SCRATCH/pa-README.md"`,
   then `grep -n '^### ' "$SCRATCH/pa-README.md"` to get the line of each category, and
   `sed -n '<start>,<next start - 1>p'` on the one you need. Do not copy the list into the
   repository or into a prompt.
2. Shortlist the category-table rows by their columns. `Auth` (public-apis/public-apis
   CONTRIBUTING.md, <https://github.com/public-apis/public-apis/blob/master/CONTRIBUTING.md>)
   takes one of:
   - `No`: no authentication needed.
   - `apiKey`: send a private key or token; use the parameter the API's docs name.
   - `OAuth`: the API supports OAuth, so a registered app and token flow.
   - `X-Mashape-Key`: send a header of this name (the RapidAPI/Mashape key).
   - `User-Agent`: send a `User-Agent` header with your requests (often one that
     identifies your app).

   Prefer `No` for throwaway work. `HTTPS` must be `Yes` for anything carrying user data.
   `CORS` is `Yes`, `No` or `Unknown` and matters only for calls made from browser code;
   per that same CONTRIBUTING.md, without proper CORS configuration an API is usable server
   side only.
3. Verify the chosen API on its own official documentation before writing code against
   it: the endpoint exists, the response shape matches, and the documented Auth, HTTPS and
   CORS agree with the row. Rows go stale: an API can be dead, moved behind a key, or
   re-licensed. If the official docs and the row disagree, the docs win; say so.
4. Read its terms of use and rate limits. Check that your use (prototype, test data,
   research, redistribution of the data) is allowed, and that the limit fits the use.
5. Make one real request and record what came back (status, a trimmed body). A call
   that fails is a result: pick the next candidate, do not mock the response. For a keyed
   API, expand the key from an environment variable, for example
   `curl -sS -H "apikey: $API_KEY" "<url>"`, never a literal. Redact credential headers
   and key query parameters from anything you record.
6. Keep keys out of code and commits. Read them from the environment or a secrets store,
   add the variable name (not the value) to the example env file, if the repo has one, and
   never paste a key into a command, log or PR body.

## Reporting

Name the API, its official docs URL, the date you verified it, and what you ran. State
that the selection came from the community list and was then checked at the source.
