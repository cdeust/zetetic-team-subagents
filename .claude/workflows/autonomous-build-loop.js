export const meta = {
  name: 'autonomous-build-loop',
  // meta must be a PURE LITERAL for the Workflow runtime — no string concatenation here (BinaryExpression
  // is rejected at load), so description/whenToUse are single string literals even though they run long.
  description: 'Closed-loop autonomous build on ANY target repository: refine -> plan -> verify-plan -> builder (general-purpose agent) build on an isolated iteration branch -> best-effort in-loop acceptance checks -> iterate until green or the budget is spent. The target repo (args.repoPath), the deterministic gate runner (args.gateRunner) and an optional base gate config (args.gateConfig) are inputs, so the loop runs from any working directory against a repo that need not contain this tooling. The loop DRAFTS and converges a candidate on the integration branch; it does not self-certify. The AUTHORITATIVE external gate is a real exec OUTSIDE the loop: a human/CI re-running the gate runner against the target repo and reading the real exit code before merging. Fails closed; does not push; does not modify main.',
  whenToUse: 'A non-trivial build task you want drafted and iterated to a candidate under acceptance checks in a chosen target repository, with per-iteration branch isolation, for a human/CI to certify and merge.',
  phases: [
    { title: 'Refine', detail: 'compile the verifiable acceptance contract' },
    { title: 'Setup', detail: 'create the integration branch off an explicit base ref' },
    { title: 'Branch', detail: 'create + checkout the iteration branch off integration' },
    { title: 'Plan', detail: 'decompose against the contract' },
    { title: 'Verify-plan', detail: 'zetetic-check the plan before any code is written' },
    { title: 'Build', detail: 'the builder commits subtasks onto the checked-out iteration branch' },
    { title: 'Accept', detail: 'deterministic gate runners + independent reviews + independent compare' },
    { title: 'Converge', detail: 'merge-on-green (reported), or preserve/discard branch and iterate' },
  ],
}

// ---------------------------------------------------------------------------
// EXTERNALITY (load-bearing): a Workflow script cannot exec or read files — only
// agents run Bash, so every in-loop "check" (gate verdict, changed files, merge) is
// reported BY AN AGENT. The JS hardens this (parses raw tool stdout not a model
// boolean, two gate runners cross-checked, lenses derived from the diff), but two
// copies of one model are NOT independent oracles (arXiv:2310.01798) — in-loop
// signals are BEST-EFFORT. The AUTHORITATIVE gate is a real exec OUTSIDE the loop
// against the target: <gateRunner> [--config <gateConfig>] --root <repoPath>
// --diff-base <baseRef> --diff-head <integrationBranch>, run by a human/CI before
// merging. The loop only DRAFTS/converges + returns the target+branch to certify.
// ---------------------------------------------------------------------------

const CONTRACT_SCHEMA = {
  type: 'object',
  required: ['goal', 'acceptance_criteria'],
  properties: {
    goal: { type: 'string', description: 'one-sentence measurable success criterion' },
    scope: { type: 'string' },
    out_of_scope: { type: 'array', items: { type: 'string' } },
    acceptance_criteria: {
      type: 'array',
      minItems: 1,
      items: {
        type: 'object',
        required: ['id', 'text', 'kind'],
        properties: {
          id: { type: 'string' },
          text: { type: 'string' },
          kind: { type: 'string', enum: ['deterministic', 'review', 'manual'] },
          checkable_cmd: { type: ['string', 'null'], description: 'shell line exiting 0 iff met; REQUIRED (non-null) when kind=deterministic, else use kind=review' },
        },
      },
    },
  },
}
const READY_BRANCH_SCHEMA = {
  type: 'object',
  required: ['ready', 'current_branch'],
  properties: {
    ready: { type: 'boolean' },
    current_branch: { type: 'string', description: 'git -C <repoPath|worktree> rev-parse --abbrev-ref HEAD after the step' },
    head: { type: 'string' },
    worktree_path: { type: 'string', description: 'absolute path of the iteration worktree (Branch step only)' },
  },
}
// Setup resolves EVERY path-shaped input to an absolute, verified form (the loop's
// composition root): the target repo, the immutable base commit, the gate runner,
// the optional base gate config, and the optional operator semantic layer. The loop
// refuses to start if a required one is missing — fail closed before branching,
// rather than emitting a confusing gate error mid-iteration.
const SETUP_SCHEMA = {
  type: 'object',
  required: ['ready', 'current_branch', 'repo_path', 'gate_runner_abs', 'gate_runner_ok', 'gate_config_ok'],
  properties: {
    ready: { type: 'boolean' },
    current_branch: { type: 'string' },
    head: { type: 'string' },
    repo_path: { type: 'string', description: 'absolute git toplevel of the target repo the loop builds in' },
    base_sha: { type: 'string', description: 'immutable SHA the integration branch was forked from (rev-parse of baseRef)' },
    gate_runner_abs: { type: 'string', description: 'absolute path to the acceptance-gate runner' },
    gate_runner_ok: { type: 'boolean', description: 'true iff the gate runner exists and is executable' },
    gate_config_abs: { type: ['string', 'null'], description: 'absolute path to the base gate config, or null if none requested' },
    gate_config_ok: { type: 'boolean', description: 'true iff no base config was requested, or it resolved to a readable file' },
    semantic_layer_abs: { type: ['string', 'null'], description: 'absolute path to the operator semantic-layer tool, or null if none requested' },
    semantic_layer_ok: { type: 'boolean', description: 'true iff no semantic layer was requested, or it resolved to an executable file' },
  },
}
const PLAN_SCHEMA = {
  type: 'object',
  required: ['summary', 'ready'],
  properties: {
    summary: { type: 'string' },
    subtasks: { type: 'array', items: { type: 'string' } },
    critical_path: { type: 'string' },
    ready: { type: 'boolean', description: 'true only if complete enough to build now' },
  },
}
const SOUND_SCHEMA = { type: 'object', required: ['sound'], properties: { sound: { type: 'boolean' }, issues: { type: 'array', items: { type: 'string' } } } }
const BUILD_SCHEMA = {
  type: 'object',
  required: ['built_branch'],
  properties: {
    built_branch: { type: 'string', description: 'the branch the build actually committed to' },
    merged_subtasks: { type: 'array', items: { type: 'string' } },
    rejected_subtasks: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
}
// The runner returns the tool's RAW output; the controller (not the model) decides from it.
const DET_RAW_SCHEMA = {
  type: 'object',
  required: ['raw_stdout', 'exit_code'],
  properties: {
    raw_stdout: { type: 'string', description: 'the EXACT JSON the tool printed to stdout, unaltered' },
    exit_code: { type: 'integer', description: 'the tool process exit code (0 accept / 3 reject / 2 usage)' },
  },
}
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['approved'],
  properties: {
    approved: { type: 'boolean', description: 'true iff you read the diff AND found no blocking issue' },
    dimension: { type: 'string' },
    blocking: { type: 'array', items: { type: 'string' } },
    evidence: { type: 'array', items: { type: 'string' }, description: 'file:line citations from the diff you reviewed' },
  },
}
const COMPARE_SCHEMA = {
  type: 'object',
  required: ['unmet'],
  properties: {
    unmet: { type: 'array', items: { type: 'string' }, description: 'contract criteria the build does not satisfy (id + why)' },
    met: { type: 'array', items: { type: 'string' } },
  },
}
const MERGE_SCHEMA = {
  type: 'object',
  required: ['merged', 'current_branch'],
  properties: {
    merged: { type: 'boolean', description: 'true iff the iteration branch actually merged into the integration branch' },
    current_branch: { type: 'string', description: 'git -C <repoPath> rev-parse --abbrev-ref HEAD when the merge ran (must be the integration branch)' },
    integration_head: { type: 'string' },
    conflicts: { type: 'array', items: { type: 'string' } },
  },
}

// Default iteration ceiling; on exhaustion the loop fails closed (does not ship a red build).
// source: Milestone 2 design fork decision (budget = 4 iterations, overridable via args.maxIterations).
const DEFAULT_MAX_ITERATIONS = 4
// A full iteration (plan+build+gates) is costly; do not start one below this many output tokens.
// source: operational default, mirrors the Workflow loop-until-budget pattern.
const TOKEN_FLOOR = 80000

// Parse one deterministic-runner result IN JS from the tool's raw output (not a model boolean). Any
// parse error, exit/accepted inconsistency, or leftover unmet fails closed. Best-effort: see EXTERNALITY.
function parseVerdict(d) {
  if (!d || typeof d.raw_stdout !== 'string') return { ok: false, accepted: false, unmet: ['gate runner returned no stdout — fail closed'], files: [] }
  let v
  try { v = JSON.parse(d.raw_stdout) } catch (e) { return { ok: false, accepted: false, unmet: ['gate stdout was not valid JSON — fail closed'], files: [] } }
  const accepted = v.accepted === true
  const exitOk = d.exit_code === 0
  const files = Array.isArray(v.changed_files) ? v.changed_files : []
  if (accepted !== exitOk) return { ok: false, accepted: false, unmet: ['gate accepted/exit_code disagree — fail closed'], files }
  if (accepted && (v.unmet || []).length > 0) return { ok: false, accepted: false, unmet: v.unmet, files }
  return { ok: true, accepted, unmet: v.unmet || [], files }
}

// Pick reviewer lenses from the reported changed files. Fail-safe toward MORE review: include security
// if any path looks sensitive, architecture if the change spans top-level dirs, and ALL lenses if the
// two runners' file lists disagree or are empty (an untrusted/empty list must not narrow review).
// source: coding-standards §10 stakes (sensitive = auth/crypto/billing/PII).
function reviewLenses(files1, files2) {
  const security = { agentType: 'general-purpose', geniuses: 'taleb, boyd', dimension: 'security (auth / crypto / billing / PII)' }
  const architecture = { agentType: 'general-purpose', geniuses: 'simon, alexander', dimension: 'architecture / layer boundaries' }
  const lenses = [{ agentType: 'general-purpose', geniuses: 'popper, feynman', dimension: 'clean-architecture / SOLID / size limits' }]
  const topDirs = (fs) => Array.from(new Set(fs.map((f) => f.split('/')[0]))).sort().join(',')
  const trusted = files1.length && files2.length && topDirs(files1) === topDirs(files2)
  if (!trusted) return lenses.concat(security, architecture)  // untrusted/empty -> widen, do not narrow
  const joined = files1.join('\n').toLowerCase()
  if (/auth|crypto|cipher|password|secret|token|billing|payment|\bpii\b|login|oauth|session/.test(joined)) lenses.push(security)
  if (new Set(files1.map((f) => f.split('/')[0])).size > 1) lenses.push(architecture)
  return lenses
}

// Every delegation carries a `GENIUS: <name>[, <name>]` line (hooks/pre-agent-genius-gate.py denies an
// Agent call without it). The names are files in agents/genius/; the delegate applies their method.
const GL = (names) => 'GENIUS: ' + names + '\n'

// --- inputs ---------------------------------------------------------------
// args may arrive as an object OR a JSON STRING (launch-dependent). Normalize, so a
// stringified args is not mistaken for a bare task — which would drop repoPath/
// gateRunner and silently build in the cwd instead of the requested target repo.
let A = args
if (typeof A === 'string') { try { const p = JSON.parse(A); if (p && typeof p === 'object') A = p } catch (e) { /* bare task string */ } }
const rawTask = typeof A === 'string' ? A : (A && A.task)
if (!rawTask) {
  log('autonomous-build-loop: no task provided. Pass args.task (or a task string). Nothing to build.')
  return { accepted: false, error: 'missing args.task' }
}
const rawMax = A && A.maxIterations
const maxIterations = Number.isInteger(rawMax) ? rawMax : DEFAULT_MAX_ITERATIONS
if (maxIterations < 1) {
  log('maxIterations must be >= 1 (got ' + maxIterations + ')')
  return { accepted: false, error: 'maxIterations must be >= 1' }
}
const integrationBranch = (A && A.integrationBranch) || 'abl/integration'
const baseRef = (A && A.baseRef) || 'HEAD'

// Path-shaped inputs. Defaults are HOME-REPO-RELATIVE (valid only when cwd is this
// repo). For an EXTERNAL target (repoPath set), base gate config + semantic layer
// default OFF — their home-relative commands would run in the FOREIGN repo (127, or
// worse a lying green from same-named foreign scripts); the contract's checks are
// the gate. hasArg distinguishes an explicit null (force off) from "use the default".
const hasArg = (k) => A && typeof A === 'object' && Object.prototype.hasOwnProperty.call(A, k)
const repoPathArg = (A && A.repoPath) || null
const isExternal = !!repoPathArg
const gateRunner = (A && A.gateRunner) || 'tools/acceptance-gate.sh'
const gateConfig = hasArg('gateConfig') ? A.gateConfig : (isExternal ? null : 'memory/acceptance-gates.loop.yaml')
const semanticLayer = hasArg('semanticLayer') ? A.semanticLayer : (isExternal ? null : 'tools/semantic-layer.sh')

// --- Refine: the acceptance contract is the spec everything else is judged against ---
phase('Refine')
const contract = await agent(
  GL('polya, popper') + 'Act as the refine layer (session-optimizer:refine). Turn the raw task below into a VERIFIABLE ' +
  'acceptance contract: a one-sentence measurable goal, explicit scope and out_of_scope, and at least ' +
  'one acceptance criterion. For each criterion choose kind: "deterministic" WITH a non-null ' +
  'checkable_cmd shell line that exits 0 iff the criterion is met (prefer these — they are ' +
  'machine-checkable); "review" when an independent reviewer must judge it; "manual" otherwise. If you ' +
  'cannot write a checkable_cmd, use kind=review. CRITICAL: the gate runs each checkable_cmd with its ' +
  'working directory set to the TARGET REPOSITORY ROOT (which is NOT your current directory), so write ' +
  'every path RELATIVE to the repo root (e.g. test -f GREETING.md, cat GREETING.md) — NEVER an absolute ' +
  'path and NEVER cd anywhere. Resolve vague references to concrete REPO-RELATIVE artifacts.\n\nTASK:\n' + rawTask,
  { schema: CONTRACT_SCHEMA, phase: 'Refine' }
)
if (!contract) return { accepted: false, error: 'refine produced no contract' }
log('contract goal: ' + contract.goal)

// --- Setup: resolve+verify the target repo and gate tooling (composition root),
//     then create the integration branch in it before the first iteration branches off. ---
phase('Setup')
const setup = await agent(
  GL('hamilton') + '<role>You prepare the autonomous build loop on its target repository. Use only explicit paths; never ' +
  'assume the process working directory is the target.</role>\n' +
  '<target_repo_path>' + (repoPathArg || 'the current directory') + '</target_repo_path>\n' +
  '<rules>Do not check out over uncommitted work. Do not touch main. Do not push.</rules>\n' +
  '<steps>\n' +
  '1. REPO = the git toplevel of <target_repo_path>: ' + (repoPathArg
    ? 'REPO=$(git -C "' + repoPathArg + '" rev-parse --show-toplevel); if that fails, set ready=false.'
    : 'REPO=$(git -C . rev-parse --show-toplevel).') +
  ' Confirm git -C "$REPO" rev-parse --is-inside-work-tree.\n' +
  '2. If ' + integrationBranch + ' is absent in REPO, create it at ' + baseRef + ' (git -C "$REPO" branch ' +
  integrationBranch + ' ' + baseRef + '). Capture base_sha = git -C "$REPO" rev-parse ' + baseRef +
  ' (immutable SHA, stable whatever HEAD points at later).\n' +
  '3. GATE = absolute path of "' + gateRunner + '" (resolve a relative path against your cwd); verify ' +
  'test -x "$GATE".\n' +
  '4. ' + (gateConfig
    ? 'GATE_CONFIG = absolute path of "' + gateConfig + '"; gate_config_abs=GATE_CONFIG, gate_config_ok=(test -r).'
    : 'No base config: gate_config_abs=null, gate_config_ok=true.') + '\n' +
  '5. ' + (semanticLayer
    ? 'SEM = absolute path of "' + semanticLayer + '"; semantic_layer_abs=SEM, semantic_layer_ok=(test -x).'
    : 'No semantic layer: semantic_layer_abs=null, semantic_layer_ok=true.') + '\n' +
  '</steps>\n' +
  '<report>ready (iff steps 1-2 ok), current_branch (git -C "$REPO" rev-parse --abbrev-ref HEAD), head (' +
  integrationBranch + ' head SHA), repo_path=REPO (absolute), base_sha, gate_runner_abs=GATE, gate_runner_ok, ' +
  'gate_config_abs, gate_config_ok, semantic_layer_abs, semantic_layer_ok.</report>',
  { schema: SETUP_SCHEMA, phase: 'Setup' }
)
if (!setup || !setup.ready || !setup.repo_path) return { accepted: false, error: 'could not prepare target repo / integration branch ' + integrationBranch }
// Backstop: a requested external target MUST be what Setup resolved — never the cwd. An agent that resolves
// the wrong toplevel (or a dropped repoPath) would otherwise build in the WRONG repo. Basename compare is
// robust to /tmp vs /private/tmp symlinks and to relative repoPath inputs. Fail closed on any mismatch.
const baseName = (p) => String(p || '').replace(/\/+$/, '').split('/').pop()
if (repoPathArg && baseName(setup.repo_path) !== baseName(repoPathArg)) return { accepted: false, error: 'requested repoPath ' + repoPathArg + ' but Setup resolved ' + setup.repo_path + ' — refusing to build the wrong repository' }
if (!setup.gate_runner_ok) return { accepted: false, error: 'gate runner not found/executable at ' + (setup.gate_runner_abs || gateRunner) + ' — pass an absolute args.gateRunner when running outside the loop home repo' }
if (!setup.gate_config_ok) return { accepted: false, error: 'base gate config not readable at ' + (setup.gate_config_abs || gateConfig) + ' — pass an absolute args.gateConfig, or null for contract-only gating' }
// Cross-field invariant: a REQUESTED base config that Setup could not resolve to an absolute path must
// fail closed, not silently degrade to contract-only gating (a strictly weaker gate). The controller
// re-derives this from the known request rather than trusting gate_config_ok alone (arXiv:2310.01798).
if (gateConfig && !setup.gate_config_abs) return { accepted: false, error: 'base gate config was requested (' + gateConfig + ') but Setup resolved no absolute path — refusing to gate without it' }
// Absolute, verified handles every later step uses instead of cwd-relative paths.
const REPO = setup.repo_path
const GATE = setup.gate_runner_abs
const BASE_SHA = setup.base_sha || baseRef  // pinned SHA for the human re-run; falls back to the symbolic ref
const SEMLAYER = setup.semantic_layer_abs || null  // resolved operator semantic layer, or null to skip persistence
const baseCfgFlag = setup.gate_config_abs ? ('--config "' + setup.gate_config_abs + '" ') : ''
// Deterministic contract checks the gate will enforce. When there are none AND no base config, the gate
// would be invoked with an empty gate set (exit 2 = config error); a sentinel keeps the empty-diff
// rejection in force and lets a review-only contract still pass through reviewers + compare-to-contract.
const detCount = (contract.acceptance_criteria || []).filter((c) => c.kind === 'deterministic' && c.checkable_cmd).length
const needSentinel = detCount === 0 && !setup.gate_config_abs

let backlog = []
let residual = []
let accepted = false
let iter = 0

while (!accepted && iter < maxIterations) {
  if (budget.total && budget.remaining() < TOKEN_FLOOR) {
    log('stopping before a new iteration: token budget below floor (' + Math.round(budget.remaining() / 1000) + 'k left)')
    break
  }
  iter += 1
  const iterBranch = 'abl/iter-' + iter
  log('=== iteration ' + iter + '/' + maxIterations + ' (' + iterBranch + ') ===')

  // --- Branch: the LOOP creates a DEDICATED, ISOLATED WORKTREE for the iteration at an absolute path, so the
  //     build has one unambiguous absolute root distinct from the session cwd (a spawned specialist cannot
  //     drift to the home repo) and the target repo's own working tree is left untouched. ---
  phase('Branch')
  const branch = await agent(
    GL('hamilton') + '<target_repo>' + REPO + '</target_repo>\n' +
    '<task>Create a dedicated, isolated git WORKTREE for this iteration so the build never touches the ' +
    'target repo\'s own working tree. Choose an absolute path WT OUTSIDE ' + REPO + ' (e.g. ' +
    'WT="$(mktemp -d)/' + iterBranch.replace('/', '-') + '"), then run: git -C "' + REPO + '" worktree add ' +
    '-B ' + iterBranch + ' "$WT" ' + integrationBranch + '. Do not touch main, do not push.</task>\n' +
    '<report>ready=true iff the worktree exists with ' + iterBranch + ' checked out; worktree_path=WT ' +
    '(absolute); current_branch = git -C "$WT" rev-parse --abbrev-ref HEAD.</report>',
    { schema: READY_BRANCH_SCHEMA, phase: 'Branch' }
  )
  if (!branch || !branch.ready || branch.current_branch !== iterBranch || !branch.worktree_path) {
    backlog = ['could not create iteration worktree for ' + iterBranch + ' (on ' + ((branch && branch.current_branch) || '?') + ')']
    log('worktree setup failed — fail closed this iteration: ' + backlog[0])
    continue
  }
  const WT = branch.worktree_path  // absolute worktree root; the build/gate/reviews use this, not REPO's tree

  phase('Plan')
  const plan = await agent(
    GL('polya, simon') + 'Plan the implementation that satisfies this acceptance contract. Decompose into subtasks with ' +
    'named artifacts and a critical path (near-decomposability, Simon). Set ready=true only if the plan is ' +
    'complete enough to build now.\n\nCONTRACT:\n' + JSON.stringify(contract, null, 2) +
    (backlog.length ? '\n\nOUTSTANDING FROM LAST ITERATION (must be fixed):\n- ' + backlog.join('\n- ') : ''),
    { schema: PLAN_SCHEMA, phase: 'Plan' }
  )

  phase('Verify-plan')
  const planVerdict = await agent(
    GL('popper, feynman') + 'Zetetically verify this plan BEFORE any code is written. Does it actually satisfy every ' +
    'acceptance criterion, respect rules/coding-standards.md (layer dependencies, SOLID, size limits), ' +
    'and avoid dead/unwired code? Be a skeptic; set sound=false with specific issues if not.\n\n' +
    'CONTRACT:\n' + JSON.stringify(contract) + '\n\nPLAN:\n' + JSON.stringify(plan),
    { schema: SOUND_SCHEMA, phase: 'Verify-plan' }
  )
  if (planVerdict && planVerdict.sound === false) {
    backlog = planVerdict.issues && planVerdict.issues.length ? planVerdict.issues : ['plan unsound']
    log('plan rejected before build: ' + backlog.join(' | '))
    continue
  }

  phase('Build')
  const build = await agent(
    GL('dijkstra, liskov') + '<role>You are the builder; build exactly what the plan specifies to satisfy the contract.</role>\n' +
    '<workdir>' + WT + '</workdir>  <working_branch>' + iterBranch + '</working_branch>\n' +
    '<rules>ALL build work happens inside <workdir> — an isolated worktree with ' + iterBranch + ' already ' +
    'checked out. Treat <workdir> as the repository root: cd "' + WT + '" before shell commands, and use ' +
    'ABSOLUTE paths under <workdir> for every file you create or edit. NEVER write outside <workdir> (it is ' +
    'distinct from your process cwd). If you spawn specialists, give each the SAME <workdir> and absolute-path ' +
    'rule. COMMIT all work to ' + iterBranch + ' (git -C "' + WT + '" add -A && commit) so the gate can scope ' +
    integrationBranch + '...' + iterBranch + '. Do not touch main, do not push.</rules>\n' +
    '<contract>' + JSON.stringify(contract) + '</contract>\n<plan>' + JSON.stringify(plan) + '</plan>\n' +
    (backlog.length ? '<fix_from_last_iteration>- ' + backlog.join('\n- ') + '</fix_from_last_iteration>\n' : '') +
    '<report>built_branch = the branch you committed to; subtasks merged/rejected.</report>',
    { agentType: 'general-purpose', schema: BUILD_SCHEMA, phase: 'Build' }
  )
  const builtBranch = (build && build.built_branch) || iterBranch
  if (builtBranch !== iterBranch) {
    backlog = ['build committed to ' + builtBranch + ' but the loop expected ' + iterBranch]
    log('branch mismatch — fail closed this iteration: ' + backlog[0])
    continue
  }

  phase('Accept')
  // The worktree WT already has iterBranch checked out with the build's committed output — the gate runs
  // --root WT and evaluates exactly that (the empty-diff rejection still requires the build to have COMMITTED).
  // (1) DETERMINISTIC gate — two runners; JS parses each tool output (not a model boolean) and requires
  //     agreement + consistency. Best-effort (EXTERNALITY): catches transcription drift, not collusion.
  const detRun = (n) => () => agent(
    GL('curie') + 'Run the deterministic acceptance gate for this iteration and return its RAW output — do not judge, ' +
    'summarize, or alter it.\nSteps:\n' +
    '(a) Write the contract\'s deterministic checks to an absolute temp JSON file (C="$(mktemp)"): a JSON ' +
    'object {"version":1,"gates":[ ... ]} with ONE gate per acceptance criterion whose kind="deterministic" ' +
    'and checkable_cmd is non-null — each {"name":"contract:<id>","cmd":<checkable_cmd>,"mandatory":true,' +
    '"origin":"contract"}. ' + (needSentinel
      ? 'If there are none, include EXACTLY one sentinel gate {"name":"build:nonempty-diff","cmd":"true",' +
        '"mandatory":true,"origin":"loop"} so the gate still enforces the empty-diff rejection.'
      : 'If there are none, write {"version":1,"gates":[]} (the base config supplies the mandatory gates).') + '\n' +
    '(b) Run EXACTLY this one line. The gate evaluates the COMMITTED tip of ' + iterBranch + ' in its own ' +
    'throwaway worktree (--rev), so it is immune to working-tree state; --root only locates the refs: "' +
    GATE + '" ' + baseCfgFlag + '--config "$C" --root "' + REPO + '" --rev ' + iterBranch + ' --diff-base ' +
    integrationBranch + ' --diff-head ' + iterBranch + '\n' +
    '(c) Return raw_stdout = the EXACT stdout the tool printed, and exit_code = the process exit code. ' +
    'Transcribe both precisely.\n\nCONTRACT:\n' + JSON.stringify(contract),
    { schema: DET_RAW_SCHEMA, label: 'gate:deterministic#' + n, phase: 'Accept' }
  )
  const [draw1, draw2] = await parallel([detRun(1), detRun(2)])
  const dv1 = parseVerdict(draw1)
  const dv2 = parseVerdict(draw2)
  const detOk = dv1.ok && dv2.ok && dv1.accepted === true && dv2.accepted === true

  // (2) INDEPENDENT reviewer agents (distinct agentTypes from the builder), lenses derived from the diff.
  const lenses = reviewLenses(dv1.files || [], dv2.files || [])
  const reviews = await parallel(lenses.map((l) => () =>
    agent(
      GL(l.geniuses) + 'You are reviewing code you did NOT write, in the target repo at ' + REPO + '. Read the diff of the ' +
      'commit range ' + integrationBranch + '...' + iterBranch + ' (run: git -C "' + REPO + '" diff ' +
      integrationBranch + '...' + iterBranch + ') and review it for: ' + l.dimension + '. Approve ONLY if you ' +
      'read the diff and found no blocking issue; cite file:line evidence for your verdict.\n\nCONTRACT GOAL: ' +
      contract.goal,
      { agentType: l.agentType, schema: REVIEW_SCHEMA, phase: 'Accept', label: 'review:' + l.dimension }
    )
  ))

  // (3) COMPARE-TO-CONTRACT — an INDEPENDENT reviewer-type agent (not the builder's default lineage)
  //     judges the review/manual criteria a command cannot check, against the actual diff, with evidence.
  const compare = await agent(
    GL('popper, feynman') + 'You are reviewing code you did NOT write, in the target repo at ' + REPO + '. Read the diff of ' +
    integrationBranch + '...' + iterBranch + ' (git -C "' + REPO + '" diff ' + integrationBranch + '...' +
    iterBranch + ') and compare it to the acceptance contract. For every criterion with kind=review or ' +
    'manual, decide whether the implementation satisfies it and cite file:line evidence. Return the unmet ' +
    'criteria (id + why). Judge against the contract AS WRITTEN; do not invent requirements.\n\nCONTRACT:\n' +
    JSON.stringify(contract),
    { agentType: 'general-purpose', schema: COMPARE_SCHEMA, phase: 'Accept', label: 'compare-to-contract' }
  )

  phase('Converge')
  const okReviews = reviews.filter(Boolean)
  const reviewsOk = okReviews.length === lenses.length && okReviews.every((r) => r.approved)
  const cmpOk = !!compare && (compare.unmet || []).length === 0
  const gatesGreen = detOk && reviewsOk && cmpOk

  residual = Array.from(new Set([].concat(
    detOk ? [] : [].concat(dv1.unmet || [], dv2.unmet || []),
    okReviews.filter((r) => !r.approved).flatMap((r) => r.blocking || [(r.dimension || 'review') + ' not approved']),
    okReviews.length === lenses.length ? [] : ['a reviewer did not return — fail closed'],
    (compare && compare.unmet) || [],
    compare ? [] : ['compare-to-contract did not return — fail closed']
  )))

  let greenButUnmerged = false
  if (gatesGreen) {
    // Gates green -> attempt the merge. The merge result is agent-reported (best-effort); the JS checks
    // the reported current_branch is the integration branch. The AUTHORITATIVE ancestry/exit check is the
    // human re-run on the integration branch (see EXTERNALITY + the return note).
    const merge = await agent(
      GL('lamport') + 'In the target repo at ' + REPO + ', check out ' + integrationBranch + ' and merge the iteration ' +
      'branch ' + iterBranch + ' into it (git -C "' + REPO + '" checkout ' + integrationBranch + ' && ' +
      'git -C "' + REPO + '" merge --no-ff ' + iterBranch + '). Do NOT push and do NOT touch main. If the ' +
      'merge conflicts, abort it cleanly (git -C "' + REPO + '" merge --abort) and report merged=false with ' +
      'the conflicting paths. On a successful merge, remove the now-merged iteration worktree (git -C "' +
      REPO + '" worktree remove --force "' + WT + '"). Report merged, the current branch (git -C "' + REPO +
      '" rev-parse --abbrev-ref HEAD) as current_branch, and the new integration head SHA as integration_head.',
      { schema: MERGE_SCHEMA, phase: 'Converge', label: 'integrate-on-green' }
    )
    if (merge && merge.merged === true && merge.current_branch === integrationBranch && merge.integration_head) {
      accepted = true
      log('iteration ' + iter + ' green and merged into ' + integrationBranch + ' (head ' + merge.integration_head + ', reported)')
    } else {
      greenButUnmerged = true  // keep the verified-green branch; do not throw the work away
      residual = residual.concat(['merge of ' + iterBranch + ' into ' + integrationBranch + ' did not land: ' +
        ((((merge && merge.conflicts) || []).join(', ')) || 'unknown') + ' — branch ' + iterBranch + ' preserved'])
      backlog = residual
      log('gates green but merge did not land — preserving ' + iterBranch + ' for re-merge; carried forward')
    }
  } else {
    backlog = residual
    log('iteration ' + iter + ' not accepted; residual: ' + residual.join(' | '))
  }

  if (!accepted && !greenButUnmerged) {
    // Rejected iteration: the controller owns the branch lifecycle — discard the branch, persist the backlog.
    await agent(
      GL('hamilton') + 'Housekeeping for a rejected iteration: remove the iteration worktree and branch (discarded). Run: ' +
      'git -C "' + REPO + '" worktree remove --force "' + WT + '"; git -C "' + REPO + '" branch -D ' + iterBranch +
      '. Do NOT touch main, do NOT push.' +
      (SEMLAYER
        ? ' Then record these unmet acceptance items as gaps in the OPERATOR\'s cross-session semantic layer ' +
          '(not the target repo), keyed by the task "' + contract.goal + '", via the resolved absolute tool "' +
          SEMLAYER + '" (if it is not reachable, report that and continue — persistence is best-effort, not ' +
          'gating).'
        : '') +
      '\nItems:\n- ' + residual.join('\n- '),
      { phase: 'Converge', label: 'cleanup+persist' }
    )
  }
}

if (!accepted) {
  log('NOT SHIPPED — ' + iter + ' iteration(s) exhausted without a merged green. Residual: ' + residual.join(' | '))
}
return {
  accepted,
  iterations: iter,
  repoPath: REPO,
  integrationBranch,
  residual: accepted ? [] : residual,
  note: accepted
    ? 'in-loop checks green and abl/iter-' + iter + ' merged into ' + integrationBranch + ' in ' + REPO +
      ' (reported). AUTHORITATIVE step before shipping: re-run the gate yourself against the target — "' +
      GATE + '" ' + baseCfgFlag + '--root "' + REPO + '" --diff-base ' + BASE_SHA + ' --diff-head ' +
      integrationBranch + ' (the pinned base SHA is stable regardless of the checked-out branch; append the ' +
      'contract checkable_cmds as an extra --config to reproduce the full gate) — read the real exit code, ' +
      'review the diff, then merge ' + integrationBranch + ' to main.'
    : 'fail closed: budget/iterations exhausted without a merged green — integration NOT certified',
}
