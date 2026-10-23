# Trusted release boundary, 2026-10-23

Scope: PR189 source helpers and generated pipeline; PR47 receives only the same
generated pipeline. Repository configuration and product versions are unchanged.

## Contract and evidence

The resolver rereads the PR after the merge response, checks its repository/base
and original tested head, and requires merged=true with the exact returned merge
SHA. It then compares main...SHA and requires behind or identical with the SHA
as merge base. The same checks precede deduplication for an already merged PR.
No output authorizing tests or publication is written before these checks.

The [GitHub merge endpoint](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)
accepts a head SHA precondition but exposes no atomic base-ref precondition.
The post-merge checks block release after a retarget race; they cannot undo a
merge already performed against another base. The
[compare endpoint](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
supplies the ancestry evidence. A read-only comparison of codebase main against
5c2e138f950f4cde34b0bd10c4c5b7ba6be89d34 returned behind and that exact SHA as
merge base while main was f3b51d308f0931a004cca073b353a2db4b2840cd.

The privileged release checkout is literal main. The embedded tag helper requires
HEAD equal origin/main and the explicit tested commit to be an ancestor of that
snapshot, using [git merge-base --is-ancestor](https://git-scm.com/docs/git-merge-base).
Annotated tag objects are rejected as targets. Tags still name TESTED_SHA and
use versions validated by the contract on that SHA. Existing remote tags remain
immutable; the existing atomic publication and strict pending-set progress
checks are retained. Push events require refs/heads/main even when the workflow
is called by another workflow. Resolved workflow_run events retain their resolver
gate. The review checkout also repeats the pull_request and same-repository guard.

## Verification

- Before the resolver correction, all 14 new trust tests failed. The final suite
  also checks reread merge state and prevents GITHUB_OUTPUT creation or push-run
  deduplication after an untrusted merge.
- Before the tag correction, three new real-Git tests failed; the foreign-target
  rejection already passed. The final tests prove that trusted main can differ
  from the older tested commit while the published tag still points to that commit.
- Both new non-main push gate cases failed before the condition was tightened.
- Final targeted pytest run: 232 passed in 8.98 seconds. Files: test_ci_post_merge,
  test_ci_post_merge_trust, test_ci_tag_publish, test_ci_post_merge_template,
  test_ci_template and test_ci_job_conditions.
- Renderer: 7 passed, 0 failed. Ruff check, actionlint, git diff --check and the
  craftsmanship checker passed; craftsmanship reported zero warnings and errors.
- Both embedded helpers match their source bytes after YAML parsing. Source and
  Mods renders match; both ci.json files and the caller workflow are unchanged.

Template blob: 297a9a6a4ae885b775b6e0b14d82ce51f4c70cd9.
Rendered pipeline blob: 957d2ed8e81051559198a69629eefaaaa5556170.
Caller blob: f76704764a44d42fb6173d506f924a8e55787aea.

These checks use simulated HTTP and disposable real Git remotes. Hosted execution
of this candidate and fresh CodeQL analysis remain pending publication.
