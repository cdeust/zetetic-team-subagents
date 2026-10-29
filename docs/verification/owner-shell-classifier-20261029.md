# Native owner workflow shell classification

The actual Claude review of ci-autonome PR8 identified an unsafe allowance in the
shared owner workflow: interpreter-wide Bash rules bypass shell classification.
The reviewed artifact is comment6494974069:
https://github.com/cdeust/ci-autonome/pull/8#issuecomment-6494974069.

The earlier permission analysis established that a later `--permission-mode`
argument overrides the pinned action's `acceptEdits`. It did not establish that
native `auto` prevents authorized workspace repairs. Removing the override and
adding broad interpreter allowances therefore lacked the required execution
proof. This correction restores native `auto` and retains only the Task allowance
in the workflow. No interpreter-wide rules are added by this workflow. The pinned
action still supplies its own required tools.

The existing owner identity, same-repository and non-default target checks remain.
Generated workflow repairs still go through their canonical source and render-ci.
Neither a workflow-file ban nor a human approval step is introduced.

Primary evidence: the installed Claude CLI help lists auto as a supported mode.
The pinned action appends user arguments after its tag-mode arguments:
https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/modes/tag/index.ts#L211-L218.
Its command parsing keeps the last scalar permission mode:
https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/base-action/src/parse-sdk-options.ts.

The changed contract failed before the workflow correction. The source receipt
continues to reconstruct the original exported workflow byte for byte, while
recording the delivered adaptation digest. A real repair and push with this
corrected policy still require hosted acceptance; static checks alone do not
establish those capabilities.
