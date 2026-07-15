---
name: coding-standards
description: Zetetic coding standards — SOLID, Clean Architecture, 3R (readability/reliability/reusability), size limits, reverse dependency injection, factory pattern. Authoritative rules all coding agents must follow.
version: 1.0.0
applies_to: [engineer, architect, code-reviewer, frontend-engineer, dba, devops-engineer, test-engineer, mlops, refactorer]
---

# Zetetic Coding Standards

These are **hard rules**. Coding agents enforce them; refactorer strictly applies them. Exceptions must be justified with a written rationale (comment at use site or ADR) and approved by a human reviewer.

Primary sources cited per section. Rules without a source are not standards — they are preferences.

---

## 1. SOLID Principles

Source: Martin, R. C. (2000). *"Design Principles and Design Patterns."* Object Mentor.

### 1.1 Single Responsibility Principle (SRP)
- One reason to change per module, class, or function.
- If two stakeholders can independently require changes to the same code, split.
- **Test:** if you describe what the code does and the description contains "and," you are violating SRP.

### 1.2 Open/Closed Principle (OCP)
- Extend behavior through new implementations, not by modifying existing ones.
- Use the language's abstraction mechanism (interface, protocol, trait, abstract class) and a registry or dispatch table — not conditional chains that grow per new case.
- **Test:** adding a new kind-of-thing requires zero edits to existing code? → OCP satisfied.

### 1.3 Liskov Substitution Principle (LSP)
- Subtypes must be substitutable for their base types without breaking correctness.
- **Never** override a method to throw `NotImplementedError`, silently weaken postconditions, or strengthen preconditions.
- Source: Liskov, B. (1987). *"Data Abstraction and Hierarchy."* OOPSLA '87.

### 1.4 Interface Segregation Principle (ISP)
- Small, focused interfaces. No god interfaces.
- Clients should not depend on methods they do not use.
- **Test:** if a client's mock of the interface has stub methods it doesn't care about, the interface is too wide.

### 1.5 Dependency Inversion Principle (DIP)
- High-level modules must not depend on low-level modules. Both depend on abstractions.
- Abstractions must not depend on details. Details depend on abstractions.
- **Practical form:** core defines the interface; infrastructure implements it; composition roots wire them at construction time.

---

## 2. Clean Architecture

Source: Martin, R. C. (2017). *Clean Architecture*. Prentice Hall. Chapters 15–23.

### 2.1 Concentric Layers with Inward Dependencies
Identify the project's specific layer vocabulary (`core/domain/infrastructure/handlers`, `domain/application/adapters`, `pkg/internal/cmd`, etc.) before touching code.

Standard layer roles:
- **Core / Domain** — pure business logic. Zero I/O. No filesystem, network, or database. Testable without mocks.
- **Application / Use Cases** — orchestrates domain objects. Defines use-case contracts.
- **Infrastructure / Adapters** — all I/O. Implements interfaces defined by inner layers.
- **Handlers / Controllers** — the composition roots. The only layer that wires core + infrastructure together.
- **Shared / Common** — pure utility functions with no dependencies on other project layers.

### 2.2 Dependency Rule (absolute)
- Shared/common → standard library only
- Core/domain → shared/common + standard library only
- Application/use-case → core/domain + shared/common
- Infrastructure → application + core + shared + standard library (NOT handlers)
- Handlers → core + infrastructure (wiring layer)
- Server/transport → handlers (NOT core or infrastructure directly)

**Violation of this rule is a code-reviewer block. No exceptions without an ADR.**

### 2.3 Ports and Adapters
- Core declares *ports* (interfaces it needs) in its own type system.
- Infrastructure provides *adapters* (implementations of those ports).
- Handlers inject adapters at construction.

---

## 3. The 3R's — Readability, Reliability, Reusability

### 3.1 Readability
- Descriptive names over terse. `normalizePaymentAmount` > `nrm`.
- Logic flows top-down within a function.
- No magic numbers. Every numeric constant has a name or a source comment (see §8).
- Comments only when the *why* is non-obvious. Never explain *what* — well-named code does that.

### 3.2 Reliability
- Use the language's type system fully. Type hints / interfaces / generics / traits / protocols — all of it.
- Validate at system boundaries only. Trust internal contracts.
- Handle errors at the appropriate layer — don't catch-and-log in core.
- No `any` / `unknown` / untyped `dict` / `interface{}` in consumer code.
- Follow the language's error-handling idiom: exceptions in Python/Java, Result in Rust, error returns in Go, try/catch with typed Error unions in TypeScript.
- **Test-suite strength is measured by mutation, not coverage.** Line/branch coverage proves a line *executed*, not that a test would *fail* if the code were wrong — a high-coverage suite that kills no mutants tests nothing. For High- and Medium-stakes code, the suite must kill injected mutants: every mutant in the changed lines is killed, or explicitly marked equivalent with a written rationale. Coverage gates the floor; mutation score gates the strength. Source: DeMillo, Lipton & Sayward (1978). *"Hints on Test Data Selection: Help for the Practicing Programmer."* IEEE Computer 11(4); Jia & Harman (2011). *"An Analysis and Survey of the Development of Mutation Testing."* IEEE TSE 37(5).

### 3.3 Reusability
- Extract shared logic into the common/shared layer (pure functions, no I/O).
- Parameterize behavior through dependency injection.
- **Three concrete uses before extracting.** Premature abstraction is worse than duplication.

---

## 4. Size Limits (hard rules)

Source: Martin, R. C. (2008). *Clean Code*, Ch. 3 (functions) and Ch. 10 (classes). Informed by measured refactoring benchmarks.

### 4.1 File size: **500 lines max**
- A file exceeding 500 lines is a structural failure — split along a concern boundary.
- Exception: auto-generated files (parsers, protobuf, GraphQL schemas) — mark with `// auto-generated`.

### 4.2 Method / function size: **50 lines max**
- A method exceeding 50 lines is a structural failure — extract helpers.
- Exception: pure dispatch tables (a switch/match with one line per case).
- **Test:** if you cannot see the whole function on one screen, it is too long.

### 4.3 Class size: **300 lines max**
- A class exceeding 300 lines is violating SRP — extract collaborators.

### 4.4 Parameter count: **4 parameters max**
- More than 4 parameters is a missing data type. Introduce a parameter object / DTO / struct.
- Exception: constructor of an explicit composition root with justified wiring.

### 4.5 Nesting depth: **3 levels max**
- More than 3 levels of nested control flow (if/for/try/with) is unreadable — extract or use guard clauses / early returns.

---

## 5. Reverse Dependency Injection + Factory Pattern

Source: Martin (2017) Ch. 11 (DIP) and Ch. 22 (Clean Architecture Main component).

### 5.1 Reverse DI — Core Declares What It Needs
- Core modules declare what they need via **interface / protocol / trait types** in their constructors or function signatures.
- Core NEVER imports concrete infrastructure types.
- Example (Python): `class CheckoutService: def __init__(self, payments: PaymentGateway, inventory: InventoryRepo): ...` — `PaymentGateway` and `InventoryRepo` are Protocols defined in core.

### 5.2 Factory / Composition Root
- Factory functions or builder classes live in the composition-root layer (handlers, main, app).
- They assemble the dependency graph at startup.
- Pattern: `def build_checkout_service(config: Config) -> CheckoutService: return CheckoutService(payments=StripeGateway(config.stripe_key), inventory=PostgresInventoryRepo(config.db))`.

### 5.3 Forbidden
- **Service locators** — a global "get me a thing by name" registry that defeats static dependency analysis.
- **Global mutable singletons** — anything except frozen configuration objects.
- **Runtime monkey-patching / reflection-based wiring** when static wiring works.
- **`import` statements in core that reference infrastructure modules** — layer violation.

### 5.4 Mandatory
- Constructor injection (or function-parameter injection for pure-functional codebases).
- Each constructor parameter has a type annotation referring to an abstraction (interface / protocol / trait), not a concrete class.

---

## 6. Root-Cause Thinking (not band-aids)

### 6.1 When something breaks
1. **Reproduce.** No reproduction → no fix.
2. **Trace.** Follow the call chain to where the invariant breaks.
3. **Classify the cause** — one of:
   - Missing or wrong contract (SRP/DIP boundary failure)
   - Layer violation (§2.2 broken)
   - Concerns tangled (SRP broken at the function level)
   - Local-reasoning defeated (§7.3 broken)
   - Stakes/discipline mismatch (rigor shortfall)
4. **Fix at the classified source** — never at the throw site.
5. **Verify** — reproduction passes, no other test regresses.

### 6.2 Symptoms that indicate architectural failure
- Circular imports → layer violation
- God functions → SRP violation
- Shotgun surgery (change one thing, edit 10 files) → missing abstraction
- Feature envy (method uses another object's state more than its own) → wrong responsibility assignment
- Flaky test → hidden shared state or timing assumption

---

## 7. Local Reasoning (structured constructs only)

Source: Dijkstra, E. W. (1968). *"Go To Statement Considered Harmful."* CACM 11(3).

### 7.1 Restrict yourself to constructs where behavior can be understood from the surrounding text
- Sequence, selection (if/else/match), bounded iteration (for/while with termination argument), function call with clear contract.

### 7.2 Default-refuse the following constructs
| Construct | Default | Justification required to override |
|---|---|---|
| Global mutable state | Refuse | Read-once-at-startup config only |
| Monkey-patching (runtime attribute injection) | Refuse | Test teardown only |
| Reflection for control flow (`getattr` dispatch, `exec`, `eval`) | Refuse | DSL or serialization; isolated and audited |
| Exceptions for expected control flow | Refuse | Only exceptional conditions (disk full, network drop) |
| Pointer/reference aliasing on mutable objects | Refuse | Benchmark-validated performance; document the owner |
| Dynamic dispatch where method body is unknown at call site | Refuse | Interface/protocol/trait with enumerated implementations |
| "Clever" one-liners | Refuse | Benchmark-validated hot path; otherwise split into named steps |
| Macros / codegen / operator overloading / decorators with side effects / context managers that mutate globals | Refuse | Isolated, audited, justified at use site |

### 7.3 Trigger
The next reader of this code would need to understand more than the function plus its contract to predict its behavior → refuse the construct.

---

## 8. Zetetic Source Discipline

Applies to every coding claim, every algorithm, every constant.

- **No source → no implementation.** Every algorithm, equation, constant, and threshold must trace to a published paper, verified benchmark, or documented empirical result.
- **Multiple sources preferred.** A single source is a hypothesis; cross-reference before accepting.
- **Read the actual paper,** not blog summaries.
- **No invented constants.** Every hardcoded number must have:
  - `// source: <citation>` comment, OR
  - `// source: benchmark <path-to-benchmark>` with the benchmark committed, OR
  - `// source: measured on <date> in <environment>, data at <link>`
- **"It works" is not a source.**
- **Say "I don't know"** when you don't. A confident wrong answer destroys trust; an honest "I don't know" preserves it.

---

## 9. Anti-Patterns (enumerated refusals)

- Writing a function body before the signature and contract.
- Catching / swallowing errors "just in case" without a named failure mode.
- Creating utility grab-bag modules (`utils.py`, `helpers.ts`, `common.go`) — every module has a single cohesive purpose.
- Passing untyped dictionaries / maps / objects across layer boundaries.
- Importing from a layer that should not be visible (§2.2).
- Dead code, backward-compat shims, or "future-proofing" code with no current caller. **If it's built, it must be called.**
- Adding a conditional for a special case when the special case should be a separate strategy / implementation.
- Defending "clever" code by the author's claim to understand it — §7.3 failure.
- Tests as the primary correctness argument for code whose failure modes they cannot exercise (concurrency, numerical, adversarial input) — see Dijkstra.
- Treating line/branch coverage as evidence of test adequacy — a high-coverage suite that kills no mutants tests nothing; strength is measured by mutation, not execution (§3.2).
- Adding docstrings, comments, or type annotations to code you did not change.
- Band-aid fixes at the throw site without root-cause analysis (§6).

---

## 10. Stakes-Calibrated Application

These rules apply proportionally:

- **High stakes** (auth/billing/crypto/concurrency/data-integrity, public API, DB migrations, files touched by >1 author in 90 days, files >500 lines): **full rule enforcement, no exceptions without ADR**.
- **Medium stakes** (core business logic, user-facing): rules 1, 2, 3, 5, 7, 8, 9 fully enforced; 4 (size limits) enforced with ≤20% flexibility on limits.
- **Low stakes** (scripts/experiments/prototypes marked as such, or UI polish / copy / CSS): rules 1, 7, 8 enforced; others can be informal.

**Rules 1 (SOLID), 2 (layer dependency), 7 (local reasoning), 8 (sources), and 13 (Definition of Done — Completion Contract) apply at all stakes levels.**

Stakes classification is **objective**, never self-declared. See engineer.md Move 6 for criteria.

---

## 11. Compliance Check (how agents use this file)

When referenced by an agent's `<domain-context>`, the agent:
1. Loads this file's rules as binding constraints.
2. Applies them in the agent's Moves — especially Move 3 (refuse constructs that defeat local reasoning) and any layer-assignment Move.
3. Produces a compliance report as part of the output format — one line per rule referenced, with `pass / fail + rationale` for rules that apply to the change.
4. **Refuses to ship** code violating a High-stakes rule without an approved ADR.

---

## 12. Mutation Testing — tests must kill mutants (mandatory on changed code)

Source: DeMillo, Lipton & Sayward (1978); Jia & Harman (2011) — see Primary Sources.

Line/branch coverage proves code *ran*, not that a test would *fail* if the code were wrong. A green suite on one backend can hide a real defect on another. (2026-06-23: a `recall` handler returned `numpy.float32`/`datetime` values; the MCP host could not build `structuredContent` from them and rejected the call on **PostgreSQL**, while **SQLite**-backed tests — which return `float`/`str` — stayed green. Coverage was 100%; the bug shipped.) Mutation testing is the objective check that a test SUITE can detect a regression: inject a small change (a *mutant*); a test must fail (*kill* it). A surviving mutant is a behaviour no test pins.

### 12.1 Rule
- **Every change to load-bearing logic runs mutation testing on the changed files before it ships** — the touched modules and their tests (a scoped run), not the whole repo.
- Each surviving mutant is one of: (a) a missing test → add it; (b) a provable **equivalent** mutant (no observable behaviour change — e.g. a case-insensitive codec name) → document it at the use site or in the run notes. There is no third option ("ignore") without a written rationale.
- Mutation testing routinely surfaces **dead code** (every mutant of an unreachable branch survives) — remove it (§9), don't test it.

### 12.2 Tooling per language (decided; wire concretely per repo)
| Language | Tool | Config |
|---|---|---|
| Python | **mutmut** (3.x) | `[tool.mutmut]` in `pyproject.toml`: `source_paths`, `only_mutate` (scope to changed files), `pytest_add_cli_args_test_selection`, `also_copy` (mutmut copies `tests/`/`test/` but **not** `tests_py/`); set `use_setproctitle = false` on macOS |
| TypeScript / JS | **StrykerJS** (`@stryker-mutator/core`) | `stryker.conf.json` — template at `templates/mutation/stryker.conf.json` |
| Rust | **cargo-mutants** | `cargo mutants --in-place -f <changed-file>` |
| Kotlin / JVM | **PIT** (`gradle-pitest-plugin`) | plugin id `info.solidsoft.pitest` in `build.gradle(.kts)`; `./gradlew pitest`; scope per-change via `targetClasses`; survivors are `status="SURVIVED"` in `build/reports/pitest/mutations.xml`. Source: gradle-pitest-plugin.solidsoft.info |
| Swift | **Muter** | `muter.conf.json` (`muter init`); `muter --files-to-mutate <files> --format json`; a mutant survives when its `testSuiteOutcome` is `passed`. Source: github.com/muter-mutation-testing/muter |

The portable dispatcher is `tools/mutation_check.sh` — it detects the language by
extension and runs the row's tool (`--list` shows the table; `--discover` reports
the current repo's language + tool + readiness for an agent on an unfamiliar repo).
Adding a language is one registry row + one `run_<lang>` (§1.2 Open/Closed), so
the supported set grows without editing the dispatch — an agent landing on a
Kotlin/Gradle or Swift/SwiftUI repo is not limited to a hardcoded few.

Concrete-wiring status: **Cortex** (Python) wired + demonstrated (`scripts/mutation_check.sh`); dispatcher + per-language runners delivered in `tools/mutation_check.sh`. Deferred (per-repo config, tools not yet installed): **prd-spec-generator** (TS → Stryker), **automatised-pipeline** (Rust → cargo-mutants), and any Kotlin/Swift repo (PIT / Muter).

### 12.3 Cross-backend / cross-config discipline
When a module serves more than one backend or runtime (PostgreSQL vs SQLite, two serializers, …), the regression tests mutation testing relies on must encode the **backend-agnostic contract** — assert the property directly, or feed each backend's representative shape. A mutation run against only the "easy" backend will not kill the bug that hides in the other. Pin the contract at the one boundary every path crosses.

### 12.4 Threshold
No blunt percentage gate (equivalent mutants make 100% unattainable). The standard is **0 surviving non-equivalent mutants on changed code**: track the score, triage every survivor (killed, or documented-equivalent).

### 12.5 Two-tier enforcement — a blocking narrow gate AND a non-blocking wide sweep
Mutation enforcement is split, because the two jobs have opposite failure costs:

| Tier | Scope | Blocking? | Tool | Cadence |
|---|---|---|---|---|
| **Per-commit** | changed files only | **yes** | `tools/mutation_check.sh` (scoped), via the git pre-commit hook | every commit |
| **Critical-zone sweep** | the whole project's load-bearing zones, run **by scope** | **no** | `tools/mutation-sweep.sh` (reads `memory/critical-zones.conf`) | CI / periodic |

- The **per-commit** tier is blocking but narrow: it only mutates the lines this change touched, so it stays fast and never punishes a change for a pre-existing gap elsewhere (§12.1).
- The **sweep** tier is wide but report-only: a broad mutation run surfaces a long tail of survivors at once, and gating commits on it would freeze the team for months. It **always exits 0** and emits a per-zone report; we ratchet coverage up **one zone per iteration**, triaging that zone's survivors with evidence. Making the wide sweep block by default would repeat the product-safety anti-pattern (heavy/broad automation must be report-only unless explicitly opted in).
- A surviving mutant migrates from the sweep's backlog into the blocking tier organically: once a critical zone is wired and clean, any later change to it is gated per-commit.

## 13. Definition of Done — the Completion Contract (blocking, all stakes levels)

Source: lead directive, 2026-07-15 (recorded after the AP #13–#18 series, where a reviewer classified an unasserted fallback-signal path as "non-blocking, repo convention"). Empirical backing: the FlashRank silent-failure incident (2026-07-11) — an unexercised error path degraded six benchmarks and production without a single signal.

**An implementation is complete and without remainder, or it does not exist.** A PR is a claim of completeness; this section defines what makes that claim verifiable and what happens when it is not.

### 13.1 The baseline (the FLOOR — explicitly non-exhaustive)

These are the most basic rules of software engineering, not a high bar. §10 stakes calibration may ADD requirements on top; nothing may subtract from this floor. Each item carries its own verification standard — prose assurance is never evidence.

| Item | Verification standard |
|---|---|
| **All edge cases covered** | Edge cases enumerated explicitly in the change report; each maps to a test. An unlisted edge case is an unhandled one. |
| **Failure paths tested like happy paths** | Every error arm, fallback, early return, and degraded mode introduced by the diff maps to a test asserting its OBSERVABLE effect — including the emission of the signal itself (log line, error value, notice), not merely a downstream side effect. An unexercised path is a latent silent failure. |
| **Deadlocks eliminated** | Written lock-ordering/blocking analysis when the diff touches locks, channels, pools, or cross-process waits: what is held, what is awaited, why it cannot cycle; timeouts on external waits. "No concurrency touched" is an acceptable analysis when true. |
| **Scalability addressed** | Growth dimensions of every new loop/collection/query named; no O(n²) on unbounded inputs, no unbounded memory growth, no per-item I/O where batching exists — or a measured justification. |
| **Functionally tested** | The behavior is proven by EXECUTING it (test run output quoted), never by reading the code. |
| **Readable and simplified** | The next reader understands each function from itself plus its contract (§7.3); no needless indirection (simplifier's bar). |
| **Norms and conventions** | This file's rules pass; the project's naming and structural conventions followed (checked against neighboring code, not assumed). |

### 13.2 The Completion Ledger — no finished PR without it

Every PR marked ready-for-review MUST embed a **Completion Ledger**: one row per §13.1 item AND one row per code path introduced by the diff, each with its **evidence** — the test name that asserts it, the command + output that proves it, the measurement, or the written analysis. Evidence is an external signal; "reviewed it, looks fine" is not a row.

**Path-enumeration duty (author):** enumerate every branch, early return, error arm, fallback, and degraded mode in `git diff base...HEAD`; each appears in the ledger mapped to its asserting test.

**Reconciliation duty (reviewer):** independently re-enumerate the diff's paths and reconcile against the ledger. Any unmapped path, any row without evidence, or a missing ledger ⇒ verdict **REFUSED** — immediately, without further analysis, at every stakes level. There is no "approve with reservations" for ledger gaps on new code.

### 13.3 Enumerated refusals
- Opening (or marking ready) a PR whose ledger is missing or incomplete — the PR is not finished; it does not ship.
- Classifying a coverage gap in NEW code as "non-blocking", "follow-up", "future evolution", or "matches existing convention". It is **blocking**. A defective existing convention does not exempt new code from being hardened.
- Shipping the happy path with failure paths "to be covered later".
- Counting a downstream side effect as coverage of a signal-emission path (the emission itself must be asserted).

### 13.4 Pre-existing debt discovered en route
Becomes a **dated, planned work item in the active series** (an issue with acceptance criteria), never a free-floating "worth a follow-up" note. Discovering debt creates an obligation to schedule it, not permission to ignore it.

### 13.5 Enforcement wiring
- **engineer/refactorer**: the change report ends with the Completion Ledger; without it the task is not done — do not hand off.
- **code-reviewer**: reconciliation duty (§13.2) is Move 0 — run it before any other analysis; a failed reconciliation short-circuits to REFUSED.
- **git:pr skill**: the PR description template requires the ledger section; a PR created through the skill without it is invalid.
- This section applies at **all stakes levels**, joining §1, §2, §7, §8 in §10's always-on list.

## Primary Sources

- Martin, R. C. (2000). "Design Principles and Design Patterns." *Object Mentor.*
- Martin, R. C. (2008). *Clean Code.* Prentice Hall.
- Martin, R. C. (2017). *Clean Architecture.* Prentice Hall.
- Liskov, B. (1987). "Data Abstraction and Hierarchy." *OOPSLA '87.*
- Dijkstra, E. W. (1968). "Go To Statement Considered Harmful." *CACM* 11(3), 147–148.
- DeMillo, R. A., Lipton, R. J., & Sayward, F. G. (1978). "Hints on Test Data Selection: Help for the Practicing Programmer." *IEEE Computer* 11(4), 34–41.
- Jia, Y., & Harman, M. (2011). "An Analysis and Survey of the Development of Mutation Testing." *IEEE TSE* 37(5), 649–678.
- Fowler, M. (2018). *Refactoring: Improving the Design of Existing Code,* 2nd ed. Addison-Wesley.
- Feathers, M. (2004). *Working Effectively with Legacy Code.* Prentice Hall.
- Evans, E. (2003). *Domain-Driven Design: Tackling Complexity in the Heart of Software.* Addison-Wesley.
