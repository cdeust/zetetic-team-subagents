// Deterministic regression tests for the adversarial-verify workflow's synthesis core.
// The agent lenses are non-deterministic (not unit-testable — repo precedent: workflows
// aren't unit-tested); this harness pins the DETERMINISTIC verdict logic, which is where
// fail-closed correctness lives. The roadmap WF-0.2 proof — "replayed on the UNSOURCED
// finding class -> reproduces the blocking verdict" — is case (3) below.
import { LENSES, synthesizeVerdict } from './extract-core.mjs'

let pass = 0, fail = 0
function check(name, cond) {
  if (cond) { console.log('  PASS: ' + name); pass++ }
  else { console.log('  FAIL: ' + name); fail++ }
}
const clean = () => ({ read_diff: true, findings: [] })
const fiveClean = [clean(), clean(), clean(), clean(), clean()]

console.log('adversarial-verify synthesis-core tests')

// Sanity: the five fixed A2 lenses are present and distinct.
check('five-lenses', LENSES.length === 5)
check('lens-keys', JSON.stringify(LENSES.map((l) => l.key)) ===
  JSON.stringify(['residual-fp', 'missed-cases', 'robustness', 'test-adequacy', 'simplicity']))
check('lens-agenttypes-distinct', new Set(LENSES.map((l) => l.agentType)).size === 5)

// (1) empty diff -> fail closed (REQUEST_CHANGES + gap), regardless of lens results.
let r = synthesizeVerdict({ nonempty: false, files: [] }, fiveClean)
check('empty-diff-request-changes', r.verdict === 'REQUEST_CHANGES')
check('empty-diff-gap', r.gaps.length === 1)

// (1b) scope agent returned null (runtime agent failure) -> fail closed, not a crash.
r = synthesizeVerdict(null, [])
check('null-scope-request-changes', r.verdict === 'REQUEST_CHANGES' && r.gaps.length === 1)

// (2) non-empty diff, all lenses clean -> APPROVE.
r = synthesizeVerdict({ nonempty: true, files: ['a.py'] }, fiveClean)
check('all-clean-approve', r.verdict === 'APPROVE' && r.blocking.length === 0 && r.gaps.length === 0)

// (3) REGRESSION (WF-0.2): the robustness lens flags an UNSOURCED-class blocking finding
//     (an invented constant standing in for a measured threshold). Synthesis must
//     reproduce a blocking verdict and surface the finding tagged with its lens.
const unsourced = {
  read_diff: true,
  findings: [{ severity: 'blocking', file: 'retry.py:2', title: 'unsourced constant DELAY = 2.741592',
    evidence: 'magic float with no `source:` annotation; threshold invented, not measured' }],
}
r = synthesizeVerdict({ nonempty: true, files: ['retry.py'] }, [clean(), clean(), unsourced, clean(), clean()])
check('unsourced-blocking-request-changes', r.verdict === 'REQUEST_CHANGES')
check('unsourced-finding-surfaced', r.blocking.length === 1 && r.blocking[0].lens === 'robustness')
check('unsourced-finding-evidence-kept', /source:/.test(r.blocking[0].evidence))

// (4) advisory-only findings -> COMMENT (not blocking).
const advisory = { read_diff: true, findings: [{ severity: 'advisory', file: 'x.py:9', title: 'nit', evidence: 'style' }] }
r = synthesizeVerdict({ nonempty: true, files: ['x.py'] }, [clean(), advisory, clean(), clean(), clean()])
check('advisory-only-comment', r.verdict === 'COMMENT' && r.advisory.length === 1)

// (5) a lens that did not return (null) -> fail closed via gap.
r = synthesizeVerdict({ nonempty: true, files: ['a.py'] }, [clean(), null, clean(), clean(), clean()])
check('missing-lens-fail-closed', r.verdict === 'REQUEST_CHANGES' && r.gaps.length === 1)

// (6) a lens that did not confirm reading the diff -> fail closed via gap.
r = synthesizeVerdict({ nonempty: true, files: ['a.py'] }, [clean(), { read_diff: false, findings: [] }, clean(), clean(), clean()])
check('lens-did-not-read-fail-closed', r.verdict === 'REQUEST_CHANGES' && r.gaps.length === 1)

console.log('----')
console.log('adversarial-verify: ' + pass + ' passed, ' + fail + ' failed')
process.exit(fail === 0 ? 0 : 1)
