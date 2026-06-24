export const meta = {
  name: 'adversarial-verify',
  // meta must be a PURE LITERAL for the Workflow runtime — no string concatenation (BinaryExpression is
  // rejected at load), so description/whenToUse are single string literals even though they run long.
  description: 'Adversarial verification of a diff BEFORE a "done"/APPROVE verdict (roadmap A2 / CR-4). Runs five perspective-diverse skeptics against the commit range — each PROMPTED TO REFUTE, not to approve: (1) residual false-positives / over-fit, (2) missed cases, (3) robustness / adversarial inputs, (4) test adequacy (would the tests survive a mutation), (5) superfluous complexity / over-engineering (no hard rule violated). Each lens reads the real diff via an agent Bash call and returns structured findings; synthesis is DETERMINISTIC (any confirmed blocking finding => REQUEST_CHANGES; advisory-only => COMMENT; none => clean). Inputs: args.repoPath (default "."), args.diffBase, args.diffHead. Two copies of one model are not independent oracles (arXiv:2310.01798): this is a BEST-EFFORT pre-merge skeptic pass that widens coverage and fails closed on an empty diff or a non-returning lens — it does NOT self-certify. The authoritative gate remains a human/CI exec outside this workflow.',
  whenToUse: 'Invoke before emitting an APPROVE/done verdict on a change set, to subject it to independent adversarial lenses that try to break it rather than confirm it. Wired as the pre-verdict step of the code-reviewer agent; also runnable standalone on any commit range.',
  phases: [
    { title: 'Scope', detail: 'confirm the diff is non-empty and list changed files (fail closed otherwise)' },
    { title: 'Refute', detail: 'five perspective-diverse skeptics, each prompted to REFUTE the diff' },
    { title: 'Synthesize', detail: 'deterministic verdict from the confirmed findings' },
  ],
}

// ---------------------------------------------------------------------------
// EXTERNALITY (load-bearing): a Workflow script cannot exec or read files — only
// agents run Bash. Every lens reports the diff and its findings BY AN AGENT. The JS
// hardens this (fixed diverse lenses, fail-closed on empty diff / missing lens,
// deterministic verdict over the parsed findings) but two copies of one model are
// NOT independent oracles (arXiv:2310.01798). This is a BEST-EFFORT skeptic pass that
// catches plausible-but-wrong "approve"s; the AUTHORITATIVE verdict is a human/CI
// review of the same range. The workflow only SURFACES findings + a draft verdict.
// ---------------------------------------------------------------------------

// The five A2 lenses. Distinct agentType per lens so each looks through a different
// failure-mode aperture (perspective-diverse verify beats N identical refuters): a
// fragility thinker finds different holes than an exhaustive-space auditor. Every
// prompt is framed to REFUTE — the default posture is "this change is not yet safe."
const LENSES = [
  {
    key: 'residual-fp',
    agentType: 'zetetic-team-subagents:genius:feynman',
    aperture: 'residual false-positives and over-fit. Find places where the change (or a prior review of it) ' +
      'looks correct only because it was fitted to the cases in front of it: a guard that passes the shown ' +
      'inputs but encodes the example rather than the rule, a fix that suppresses a symptom at the throw site ' +
      'instead of the cause, a constant or branch that exists only to make one test green. Cargo-cult and ' +
      'coincidental-correctness are the targets.',
  },
  {
    key: 'missed-cases',
    agentType: 'zetetic-team-subagents:genius:borges',
    aperture: 'missed cases. Enumerate the input/state space the change touches and name the regions it does ' +
      'NOT handle: empty/null, boundary values, the second concurrent caller, the error path, the already-exists ' +
      'case, the unicode/locale case. A case is "missed" if no code in the diff handles it AND no test exercises it.',
  },
  {
    key: 'robustness',
    agentType: 'zetetic-team-subagents:genius:taleb',
    aperture: 'robustness against adversarial and hostile inputs. Assume the input is chosen by an adversary: ' +
      'oversized, malformed, injection-shaped, out-of-order, replayed. Find where the change is fragile — where ' +
      'a hostile input causes a crash, a silent wrong result, resource exhaustion, or an unsourced/invented ' +
      'constant standing in for a measured threshold.',
  },
  {
    key: 'test-adequacy',
    agentType: 'zetetic-team-subagents:test-engineer',
    aperture: 'test adequacy — would the tests SURVIVE a mutation. For each new or changed execution path, ' +
      'check that a test asserts its postcondition (not merely that it ran) and would FAIL if the logic were ' +
      'mutated (boundary flipped, operator swapped, return negated). A high-coverage diff whose tests kill no ' +
      'mutant is a blocking test-adequacy failure (mutation testing is owned by test-engineer).',
  },
  {
    key: 'simplicity',
    agentType: 'zetetic-team-subagents:simplifier',
    aperture: 'superfluous complexity — over-engineering that no hard rule forbids. Assume the change does more ' +
      'than its problem requires and try to prove it: an abstraction with fewer than three real, varying uses ' +
      '(rule-of-three); a one-implementation interface, base class, or generic parameter; a factory that builds ' +
      'one thing; a pass-through wrapper or layer that only forwards with no added meaning (needless indirection); ' +
      'a parameter, flag, or extension point no caller varies and no dated requirement needs (YAGNI / speculative ' +
      'generality); a performance optimization with no profile behind it (premature optimization). These are ' +
      'language-agnostic simplicity principles, not framework rules. A finding is "blocking" only if the complexity ' +
      'is both unused and a real maintenance hazard; otherwise advisory. Complexity that earns its keep (>=3 real ' +
      'uses, a cited constraint, a measured hot path) is NOT a finding. De-over-engineering is owned by simplifier.',
  },
]

const SCOPE_SCHEMA = {
  type: 'object',
  required: ['nonempty', 'files'],
  properties: {
    nonempty: { type: 'boolean', description: 'true iff the diff of the range has at least one changed file' },
    files: { type: 'array', items: { type: 'string' }, description: 'changed file paths in the range' },
  },
}

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['read_diff', 'findings'],
  properties: {
    read_diff: { type: 'boolean', description: 'true iff you actually ran the git diff and read it' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'file', 'title', 'evidence'],
        properties: {
          severity: { type: 'string', enum: ['blocking', 'advisory'] },
          file: { type: 'string', description: 'path:line anchor for the finding' },
          title: { type: 'string', description: 'one line — what is wrong' },
          evidence: { type: 'string', description: 'why it is wrong, citing the diff; an unfounded guess is not a finding' },
        },
      },
    },
  },
}

// synthesizeVerdict — DETERMINISTIC over the parsed lens results. Fail closed: a lens
// that did not return, or claims not to have read the diff, is itself a blocking gap.
function synthesizeVerdict(scope, lensResults) {
  const gaps = []
  if (!scope || scope.nonempty !== true) {
    return { verdict: 'REQUEST_CHANGES', blocking: [], advisory: [], gaps: ['scope agent returned null or empty diff — nothing verified (fail closed)'] }
  }
  const blocking = []
  const advisory = []
  LENSES.forEach((lens, i) => {
    const r = lensResults[i]
    if (!r) { gaps.push('lens ' + lens.key + ' did not return — fail closed'); return }
    if (r.read_diff !== true) { gaps.push('lens ' + lens.key + ' did not confirm reading the diff — fail closed'); return }
    for (const f of r.findings || []) {
      const tagged = { lens: lens.key, ...f }
      if (f.severity === 'blocking') blocking.push(tagged)
      else advisory.push(tagged)
    }
  })
  let verdict = 'APPROVE'
  if (blocking.length > 0 || gaps.length > 0) verdict = 'REQUEST_CHANGES'
  else if (advisory.length > 0) verdict = 'COMMENT'
  return { verdict, blocking, advisory, gaps }
}

// --- run --- (MARKER: tools/tests/adversarial-verify/extract-core.mjs slices this file
// at this line to load the pure core above for testing — do not rename this marker or
// move it above the LENSES / synthesizeVerdict declarations.)
const REPO = (args && args.repoPath) || '.'
const BASE = args && args.diffBase
const HEAD = args && args.diffHead
if (!BASE || !HEAD) {
  // Fail closed before spawning any agent: an unscoped verify is meaningless.
  log('adversarial-verify: missing args.diffBase / args.diffHead — refusing to run unscoped')
  return { verdict: 'REQUEST_CHANGES', blocking: [], advisory: [], gaps: ['no diff range supplied (diffBase/diffHead)'] }
}
const RANGE = BASE + '...' + HEAD
const diffCmd = 'git -C "' + REPO + '" diff ' + RANGE

phase('Scope')
const scope = await agent(
  'Report the scope of a diff. Run exactly: ' + diffCmd + ' --name-only\n' +
  'Return nonempty=true iff at least one file is listed, and files=the listed paths. Do not judge the change.',
  { schema: SCOPE_SCHEMA, label: 'scope', phase: 'Scope' }
)
if (!scope || scope.nonempty !== true) {
  log('adversarial-verify: empty diff for ' + RANGE + ' — fail closed')
  return synthesizeVerdict(scope, [])
}

phase('Refute')
// All four lenses always run (the A2 set is fixed, not file-derived) and concurrently.
const lensResults = await parallel(LENSES.map((lens) => () =>
  agent(
    'You are an ADVERSARIAL verifier reviewing code you did NOT write, in the repo at ' + REPO + '. Your ' +
    'default posture is that this change is NOT yet safe to merge; your job is to REFUTE it, not to approve it.\n' +
    'Read the diff: ' + diffCmd + ' (and read the surrounding file context for any hunk you cite).\n' +
    'Look through exactly one aperture: ' + lens.aperture + '\n' +
    'Return read_diff=true only if you actually ran the diff and read it. Return findings as a list; each ' +
    'finding needs a path:line anchor and evidence FROM THE DIFF — an unfounded guess is not a finding, omit it. ' +
    'severity=blocking if it would cause a wrong result, crash, security hole, or untested critical path; ' +
    'severity=advisory otherwise. If after a genuine search you find nothing through this aperture, return an ' +
    'empty findings list (do not invent issues to look thorough).',
    { agentType: lens.agentType, schema: FINDINGS_SCHEMA, phase: 'Refute', label: 'refute:' + lens.key }
  )
))

phase('Synthesize')
const result = synthesizeVerdict(scope, lensResults)
log('adversarial-verify ' + RANGE + ': ' + result.verdict +
  ' (' + result.blocking.length + ' blocking, ' + result.advisory.length + ' advisory, ' + result.gaps.length + ' gaps)')
return { range: RANGE, files: scope.files, ...result }
