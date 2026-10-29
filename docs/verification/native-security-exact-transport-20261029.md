# Exact native security request transport

## Primary observed behavior

Viz PR213 controller comment6492065732 at08:42:50 contained `@codex security review` plus a hidden marker. Native code receipt6492093354 followed at08:44:13; native summary6489153112 records code Manual request08:44:15 while security remained Manual request08:05:21. The head522f877... had not been pushed since08:04:38. This does not establish that the marked command was accepted as a security request. In contrast source219 exact-only comment6491562935 at08:16:36 produced native security receipt6491639753 at08:20:43.

Hosted confirmation: private ci-autonome run40849421081/job123364886367 at immutable head1871896fe1aaaca8feeea9559e195d750c9aae20 posted comment6492934654 with body exactly `@codex security review` as GitHub Actions Bot. Its workflow grants only pull-requests:write (plus implicit metadata read). Native security summary6492939454 then completed that exact head at09:27:27, with explicit clean security receipt6492984358 at09:27:25. The earlier eyes acknowledgement was transient and is no longer listed after completion. No code-review completion is inferred: the canary code kind is absent. Prior issues:write with pull-requests:read returned403 in run40848869794.

Sources: https://github.com/cdeust/cortex-viz/pull/213#issuecomment-6492065732 ; https://github.com/cdeust/cortex-viz/pull/213#issuecomment-6492093354 ; https://github.com/cdeust/zetetic-team-subagents/pull/219#issuecomment-6491562935 ; https://github.com/cdeust/ci-autonome/actions/runs/40849421081 ; https://github.com/cdeust/ci-autonome/pull/6#issuecomment-6492984358 . REST create/update comment permissions: https://docs.github.com/en/rest/issues/comments .

## Outbox protocol

The native security command comment is now EXACT, without marker, head text, trailing newline, or instructions. FIX commands retain their previously accepted body. Security head/kind control is a separate no-mention comment with authenticated original actor/editor and an exact schema. Submitted control records must link a pristine exact command ID by the same immutable actor. Forged/untrusted control comments cannot steer recovery; a tampered trusted control fails closed.

Control states:

- prepared: no native command attempt has started; a later serialized invocation may create a fresh reservation.
- posting: persisted before the actual command POST; replay cannot prove whether emission happened, so it never resends.
- submitted: the actual command ID and same-actor body/editor linkage were verified. This is transport evidence, not a native verdict.
- uncertain: a command outcome could not be proven; replay diagnoses it without another command.
- aborted: head/proof changed before command emission; no native command was attempted.

Fresh live head, native proof, latest run and authenticated attempt jobs are checked before reservation, posting transition and actual command creation. A head move or intervening native completion aborts before command emission. Existing per-PR hosted serialization remains required; bootstrap must not race a hosted controller. GitHub comment creation has no idempotency key, so an ambiguous result cannot be turned into a safe automatic retry. Partial acknowledgement/update failures therefore remain explicit and cannot create duplicate native commands or a fabricated verdict. Positive later native completion still follows the normal independent gate path. No timing threshold or retry cap was invented.

Legacy marked security comments are not accepted as proof of valid security transport; eligible completed-unknown security may use the new exact protocol. Existing running reviews still suppress requests. Accepted FIX body and its v1 head/kind dedup are unchanged. The two mutation workers now use pull-requests:write and issues:read; discovery remains read-only, checkout contents:read, rerun actions:write, private no-schedule rendering preserved.

## Verification

Before the outbox, its tests reproduced eight failures and one error, including no exact command, missing separate control, duplicate/failure-state semantics and no head-transition abort. Final canonical native suite:156 tests OK, including15 outbox cases and the independent false-clean contradiction guard. Renderer tests execute the exported contracts through the actual consumer under Python-S. The focused integration and private no-schedule checks are reported separately from full source/hosted CI.

This commit is separate from f8e4380 and the required guard follow-up10295ee7044638ebc205fea0ac496ff2d9d0cd85. Root owns combined publication and full hosted CI. The hosted canary proves exact-command security transport, not an end-to-end native FIX publication or the entire multi-write outbox on a production queue. No remote writes were performed by this worker.
