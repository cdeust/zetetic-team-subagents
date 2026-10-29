---
description: "Canonical craftsmanship checklist — the enforcing trigger+detector+fix for every coding-standards.md §1–§5/§4/§9 rule plus mutation testing. The single source the per-agent craftsmanship gate inherits; run it before shipping any code-producing change."
---

# Craftsmanship Moves — the operationalizing layer for `coding-standards.md`

This file is **not** a copy of `coding-standards.md` (that would violate DRY/§9). `coding-standards.md` states the rules and their rationale; **this file states, for each rule, the concrete trigger that fires it, the literal detector test that decides it, and the fix** — so the rule is *enforced behavior* rather than recalled prose. Every entry cites its `§` for the rationale; read the `§` when a trigger fires and the fix is non-obvious.

It is loaded on demand by each code-touching agent's **Craftsmanship gate** Move. Because it is a single source, the thresholds and detectors cannot drift between agents (the audit found §4 recalled as 40/300 in one agent and ~100 in another — that is the failure mode this file removes).

## How to run it

When your **Craftsmanship gate** trigger fires (you are about to ship, approve, or hand off a change that produces or modifies source code): walk every trigger below against your diff. **A fired trigger is a blocking finding** — fix it at the source, or hand off to the agent that owns it. Do not ship past a fired trigger without an ADR (High-stakes) or a documented at-the-use-site rationale (Medium/Low), per `coding-standards.md` §10.

**Scope.** Apply to the application/source code the change produces. Documented domain exemptions in your own `<domain-context>` still hold (e.g. DB migrations/DDL are exempt from §4 size limits but not from §8 sources; research notebooks are exempt until promoted to production — §10). An exemption must be *written*, not assumed.

---

## §1 — SOLID

**§1.1 SRP — the "and" test.**
*Trigger:* you are about to commit a function/class/module. *Detector:* describe what it does in one sentence; if the honest description contains "and" — or two stakeholders could independently require it to change — it has more than one reason to change. *Fix:* split along the concern boundary (I/O vs computation, policy vs mechanism, transport vs protocol, validation vs transformation); each piece gets its own contract and test boundary. (§1.1)

**§1.2 OCP — the zero-edit test.**
*Trigger:* you are about to add an `if kind == …` / `switch`/`case`/`elif` branch to behavior that already has one or more such branches. *Detector:* "to add the *next* kind-of-thing, do I edit this existing code?" If yes → OCP violation. *Fix:* extend via a new implementation behind an interface/protocol/trait + a registry or dispatch table keyed by kind; adding a kind then registers one entry and edits nothing existing. A growing conditional chain per new case is the canonical smell. (§1.2)

**§1.3 LSP — the substitutability check.**
*Trigger:* you are about to override a method, implement an interface, or subtype. *Detector:* does the override (a) throw where the parent does not (incl. `NotImplementedError`/`UnsupportedOperation`), (b) weaken a postcondition, or (c) strengthen a precondition? Any of the three → LSP violation. *Fix:* honor the parent contract exactly, or do not claim the subtype relationship (prefer composition / a separate interface). A subtype must be usable everywhere the base is, with no caller knowing the difference. (§1.3)

**§1.4 ISP — the client-mock-stub test.**
*Trigger:* you are about to add a method to an existing interface/protocol, or a consumer must implement/mock one. *Detector:* would a client's mock of this interface contain stub methods it does not care about? Did a protocol grow past the handful of methods any single client uses? → interface too wide. *Fix:* split into focused role interfaces; each client depends only on the methods it actually calls. No god interfaces. (§1.4)

**§1.5 DIP — depend on abstractions.** *(Structurally enforced via §2.2 + §5.1; the signature-level check lives at §5.4.)*
*Trigger:* a high-level/inner module is about to reference a concrete low-level type. *Detector:* does an inner-layer file import or name a concrete adapter/SDK/client type instead of an interface it declares? *Fix:* the inner layer declares the abstraction it needs; the outer layer implements it; wiring happens at the composition root (§5.2). Verify with the import-direction grep in §2.2. (§1.5)

---

## §2 — Clean Architecture

**§2.2 — the absolute import matrix.** *(No agent currently enumerates this — it is the single source for it.)*
*Trigger:* any added/changed `import`/`require`/`use` statement, or any new module placed in a layer. *Detector:* dependencies point **inward only**, against this matrix:

| Layer | May import |
|---|---|
| Shared / common | standard library only |
| Core / domain | shared/common + standard library |
| Application / use-case | core/domain + shared/common |
| Infrastructure / adapters | application + core + shared + stdlib — **NOT handlers** |
| Handlers / controllers (composition root) | core + infrastructure (wiring layer) |
| Server / transport | handlers — **NOT core or infrastructure directly** |

*Fix:* an outward edge (inner imports outer) is a violation — invert it with an interface declared in the inner layer + an implementation in the outer (§5.1). Verify direction with `grep -rE "from infrastructure|import infrastructure" core/` → must be empty (adapt the path/idiom to the stack). A cycle is always a layer violation. **No layer violation ships without an ADR (§2.2 is a code-reviewer block).** (§2.1–§2.3)

---

## §3 — The 3R's

**§3.1 Readability — descriptive names + no unsourced magic numbers.**
*Trigger:* you introduced a name shorter/terser than the concept, or a bare numeric/string literal in logic. *Detector:* would the next reader know what `nrm`/`d`/`tmp` is without scrolling? Does every numeric constant have a name or a `// source:` comment? *Fix:* rename to the concept (`normalizePaymentAmount`, not `nrm`); give every constant a name or a §8 source comment (citation / `benchmark <path>` / `measured on <date>`). Logic flows top-down within a function. (§3.1, §8)

**§3.2 Reliability — types to the boundary, validate once, idiomatic errors.**
*Trigger:* a value crosses a layer/module boundary, or you are about to handle an error. *Detector:* is anything typed `any`/`unknown`/untyped `dict`/`map`/`interface{}` crossing a boundary? Is validation duplicated past the system edge, or absent at it? Is the error path off-idiom (exceptions in Go, swallowed `Result`, untyped `catch`)? *Fix:* use the language's type system fully; validate at system boundaries **only** and trust internal contracts; follow the stack's error idiom (exceptions in Python/Java, `Result`/`error` in Rust/Go, typed `Error` unions in TS). Handle errors at the layer that can act, not at the throw site. (§3.2)

**§3.3 Reusability — the rule-of-three counter.**
*Trigger:* you are about to extract a shared abstraction, base class, helper, or generic. *Detector:* count the *concrete, current* call sites that need it. Fewer than three → premature abstraction. *Fix:* wait until three concrete uses exist, then extract into the shared/common layer as a pure, DI-parameterized unit. Premature abstraction is worse than duplication; duplication earns its abstraction at the third use. (§3.3)

---

## §4 — Size limits (the single source; do not recall these numbers from memory)

*Trigger:* you finished writing/modifying a file, function, class, signature, or nested block. *Detector + Fix:*

| Unit | Hard limit | On breach |
|---|---|---|
| File | **500 lines** | split along a concern boundary (auto-generated files exempt — mark `// auto-generated`) |
| Function / method | **50 lines** | extract helpers (pure dispatch tables exempt — one line per case) |
| Class | **300 lines** | extract collaborators (it is violating SRP) |
| Parameters | **4 max** | introduce a parameter object / DTO / struct (explicit composition-root ctor exempt with rationale) |
| Nesting depth | **3 levels** | guard clauses / early returns / extract |

Medium-stakes allows ≤20% flex on these; High-stakes is exact, no flex without an ADR (§10). DDL/migrations and unpromoted notebooks are exempt per the owning agent's domain-context. (§4.1–§4.5, §10)

---

## §5 — Reverse DI + Factory

**§5.1 Reverse-DI — core declares its ports.**
*Trigger:* core/inner code needs an external capability (DB, network, clock, gateway). *Detector:* does core import a concrete implementation, or does it declare an interface/protocol/trait *in its own type system* and accept it? *Fix:* core declares the port; infrastructure provides the adapter; never the reverse. (§5.1)

**§5.2 Factory / composition root — wiring lives at the edge.**
*Trigger:* you are about to instantiate a concrete dependency (`new StripeGateway(...)`, `PostgresRepo(...)`) inside core/application code. *Detector:* is the `new`/constructor call happening anywhere other than a factory/builder in the composition-root layer (handlers/main/app)? *Fix:* move construction into a factory function at the composition root that assembles the graph at startup; inject the result. (§5.2)

**§5.3 Forbidden DI constructs.**
*Trigger:* you are about to wire dependencies by name-lookup, global, or runtime patching. *Detector + Fix:* refuse — **service locators** (global "get me a thing by name" registry — defeats static analysis), **global mutable singletons** (anything but frozen read-once config), and **reflection/monkey-patch wiring** when static wiring works. Replace with constructor injection from the composition root. (§5.3)

**§5.4 Constructor injection — typed to abstractions.**
*Trigger:* you are writing a constructor / DI'd function signature. *Detector:* is every injected parameter annotated to an interface/protocol/trait, **not** a concrete class? *Fix:* type each dependency parameter to the abstraction it needs; concrete types appear only in the composition root's factory. (§5.4)

---

## §9 — DRY & enumerated anti-patterns

**DRY — duplication, grab-bags, shotgun surgery.**
*Trigger:* you copied logic, reached for a `utils`/`helpers`/`common`/`misc` module, or one logical change touched many files. *Detector:* (a) is the same logic in two+ places that must change together? (b) does the module have a single cohesive purpose, or is it a landing zone? (c) did a one-concept change require edits across N files (shotgun surgery → a missing abstraction)? *Fix:* (a) extract at the third occurrence (§3.3) into a named, cohesively-purposed unit — never a grab-bag; (b) every module earns a 2–3-word responsibility name; (c) introduce the coordinator/abstraction the scattered edits imply. (§9, §6.2)

Also refuse, per §9: dead code / "future-proofing" with no current caller (built ⇒ called); untyped maps across boundaries (→ §3.2); band-aid fixes at the throw site without root-cause (§6); a conditional special-case where a strategy belongs (→ §1.2); adding docstrings/comments/types to code you did not change.

---

## Test-suite strength — mutation, not coverage

*Trigger:* you are about to call a test suite adequate for High- or Medium-stakes code (to ship, approve, or rest a behavior-preservation claim on it). *Detector:* line/branch coverage proves a line *executed*, not that a test would *fail* if the line were wrong — a high-coverage suite that kills no mutants tests nothing. *Fix:* the suite must **kill mutants**, not merely cover lines: every mutant in the *changed lines* is killed or explicitly marked equivalent with a written rationale. This is owned and operationalized by `tools/mutation-gate.sh` (named runner per stack: mutmut/Cosmic-Ray (Py), Stryker (JS/TS), PIT (JVM), `cargo-mutants` (Rust), `go-mutesting` (Go)); a refactoring's pass-count-equal behavior-preservation proof and the review's test-adequacy check are valid only against a mutation-strong suite. (coding-standards.md §3.2 test-strength clause; §9; DeMillo–Lipton–Sayward 1978; Jia & Harman 2011)
