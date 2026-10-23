# Memory concurrency verification

Hosted run39905286973 failed C1 with one successful create and no duplicate
responses, while unit and regression passed. The local unmodified concurrency
suite passed normally. Simulating a slow system-wide `sync` with a seven-second
fixture reproduced the exact C1 failure signature. Seven seconds exceeds the
existing five-second no-progress lock deadline; no production timeout changed.
This reproduces a cause of that signature, without proving the hosted disk state.

The writer previously called system-wide `sync` while holding the scope lock.
It now flushes only the completed temporary file with
[os.fsync](https://docs.python.org/3/library/os.html#os.fsync) before the existing
atomic rename. No directory crash-durability claim is added.

With the same slow-sync fixture, C1 and all six concurrency checks pass.
Two new regressions fail before the change and pass afterward: a system-wide
flush is unavailable, and a file-flush failure must preserve the previous
memory. The exact UTF-8 content and paths with spaces are checked.

All six existing memory suites pass: concurrency, end-to-end, MCP, expanded
PII, PII and stale-lock recovery. The two new tests pass. Ruff and Bash syntax
checks pass, as does ShellCheck at warning severity; its default severity also
reports a pre-existing SC1003 informational diagnostic on the unchanged path
validation pattern. Independent review found no blocking defect.

C1 now keeps its process outputs inside its disposable root and prints them
on failure, so a future hosted failure has diagnostics and leaves no separate
output files. The common workflow is unchanged by this follow-up.
