# Examples: Five Sessions, Five Recognitions

These are illustrative reconstructions, not verbatim transcripts. The system behaviors shown (the hook that blocks, the agent that refuses, the chain that surfaces a finding) are real and reproducible (see the table at the end).

---

## #1: The unsourced constant

A retry window for an external payment API was being tuned by trial-and-error. The developer typed `RETRY_DELAY_S = 2.7` and went to commit, expecting nothing to fight back.

```
$ git commit -m "tune retry backoff"

UNSOURCED   (error)    payments/retry.py:1: # It always works at this delay
MAGIC_NUMBER (error)    payments/retry.py:2: RETRY_DELAY_S = 2.741592

Profile: strict  (staged mode)
Errors:   2  (blocking)
FAILED: 2 blocking violation(s).

BLOCKED: Zetetic violations in staged files.

$ /verify-claim "RETRY_DELAY_S = 2.741592 for the payment API"

→ Searched: PCI guidance, AWS exponential-backoff docs, Stripe retry rec.
→ No primary source mentions 2.741592 specifically.
→ Recommendation: this is not a sourced constant. Either cite the
  measurement that produced it, or run a benchmark and cite that.

$ # measured p99 retry success at three values
$ python bench/retry_window.py
  1.0s: 91.2% / 2.0s: 97.8% / 3.0s: 98.1%

$ git commit -m "set retry to 3.0s based on measured p99 success rate"
# retry.py:2 now reads: RETRY_DELAY_S = 3.0  # source: bench/retry_window.py 2026-04-25
PASSED.
```

> **The system didn't find the answer; it found that you didn't have one yet.**

---

## #2: The latency bug

An API showed p99 latency 200ms above the sum of profiled component latencies. Profiling tools said everything was fine. The team had been chasing it for a week.

```
$ /genius route "p99 latency exceeds the sum of profiled components by 200ms"
→ Routes to Curie (residual-with-a-carrier) + Knuth (profile-before-optimizing)

[Curie]   The residual is a real measurement, not noise.
          Carriers I've seen for unaccounted latency:
          - lock contention on a per-connection mutex
          - kernel scheduler quanta on a low-priority cgroup
          - blocking syscall in a path the profiler doesn't sample
          Run a contention-aware profile: perf lock record, then perf lock report.

[Knuth]   Before optimizing further: where is the actual hot path?
          Run py-spy / perf with --call-graph and look for sample concentration
          OUTSIDE the functions you've already optimized.

$ perf lock record -a -- ./bench
$ perf lock report
... ConnectionPool::get_or_create  contention=187ms  acquisitions=3,400 ...
```

> **The 200ms that didn't belong anywhere belonged to a lock nobody was watching.**

---

## #3: The literature search before a design decision

Before committing to a new attention layer for a model in production, the team needed to know what the 2024–2026 literature actually shows about linear attention alternatives. Reading 40 papers in a week is not realistic. Reading abstracts is not enough.

```
$ /deep-research "transformer attention alternatives 2024-2026, focus on
                  long-context efficiency vs. quality trade-offs"

[Peirce]    Hypothesis space: 4 distinct mechanisms (linear, state-space,
            sparse, MoE-attention). Searching primary sources for each.

[Cochrane]  Coverage check: 38 papers retrieved across 4 mechanisms.
            Heterogeneity in benchmarks is high — three different long-context
            evals dominate, none is universal. Will report effect sizes per
            benchmark, not pooled.

[Feynman]   Integrity check on 5 most-cited claims: two cite a paper that
            does not contain the claim. Marked as UNVERIFIED in the brief.

[Toulmin]   Argument structure: claim / evidence / warrant / qualifier per
            mechanism. Three mechanisms have qualifiers ("under context > 32k");
            one has none — flagged as overclaim.

→ docs/research/attention-alternatives-2026.md  (cited brief, 12 pp)
→ docs/research/attention-alternatives-2026.provenance.md  (every source, status)
→ docs/research/attention-alternatives-2026.difficulty.md  (3 contradictions
   the literature has not resolved)
```

> **The question wasn't answered; it was made answerable.**

---

## #4: The architecture decision the agent refused to make

A login bug needed to ship before a demo. The dev asked a delegate (built-in `general-purpose`, `GENIUS: curie, dijkstra`) to add a `try/except` around the failing call and log the error. Standard band-aid. Five minutes of work.

```
$ /implement "wrap the auth.verify() call in try/except, log to sentry,
              return False on any exception"

[curie, dijkstra]  Refusing: a patch that hides the symptom is not a root cause
            (a cause needs a repro AND a fix that removes the symptom).
            Producing the RCA artifact instead.

ROOT CAUSE ANALYSIS
  Symptom: auth.verify() raises TimeoutError under load
  Trace:   auth/verify.py:42 → calls oauth_provider.introspect() with 5s timeout
  Layer violation: domain layer (auth) calls infrastructure (oauth_provider) directly
  Architectural cause: missing port; oauth lives at the boundary, not at the core

  The try/except would mask the symptom but not fix the layer violation.
  Under sustained load, every request would now silently fail-open, returning
  False. That is the worse failure mode (permission denial vs. permission breach).

PROPOSED FIX (layer assignment + contract)
  - Define IdentityVerifier interface in core/auth
  - OAuth implementation moves to infrastructure/oauth_introspector
  - Composition root wires them; timeout becomes a constructor parameter
  - Postcondition: under timeout, raise VerificationUnavailable (named failure
    mode), do NOT return False

  Estimated effort: 2 hours. Demo ships in 4. Math checks out.

$ # dev followed the architectural fix
$ # demo shipped on time
```

> **The refusal was the help.**

---

## #5: The incident postmortem

A 3am pager: "checkout flow broken, ~2% error rate." It cleared by 6am with no deploy, no obvious cause, no log line that pointed at it. Standard response: "transient, monitor, close."

```
$ /incident-investigation
  → Chains: Ginzburg → Braudel → Deming → Peirce → Hamilton

[Ginzburg]  Forensic timeline reconstruction. Looking at marginal evidence
            the on-call ignored: load-balancer health-check intervals,
            database replica lag, downstream payment-provider 503 rate.

            Finding: payment-provider 503 rate climbed from 0.1% to 4.2%
            between 02:48 and 05:53. Retries on our side were succeeding
            (eventually), so the alert never tripped. But the retry budget
            we held added latency that pushed checkout over its 2s SLA.

[Braudel]   Three-timescale decomposition.
            Event:        the 503 spike (3 hours)
            Conjuncture:  payment-provider's incremental rollout this week (5 days)
            Structure:    our retry policy has been "transparent" for 18 months
                          — i.e., it hides upstream failures from our metrics.
                          The structure is what made the conjuncture invisible.

[Deming]    Common-cause vs. special-cause check.
            This is a SPECIAL cause (the rollout). But the 18-month structural
            issue (transparent retries) is a COMMON cause that has been silently
            inflating our latency tail every time any upstream wobbles.

[Peirce]    Root cause (structural, not the pager-trigger):
            Our retry policy reports SUCCESS to metrics regardless of attempt
            count. We have no signal for "succeeded in 8 attempts vs. 1."
            Every upstream wobble looks identical to a healthy state.

[Hamilton]  Remediation (graceful degradation, not just fix-and-forget):
            1. Add retry-attempt-count metric (P0, this sprint)
            2. Add retry-attempt-count alert at p95 > 2 (P0, this sprint)
            3. Document the structural pattern in difficulty book (now)
            4. Schedule a review of all transparent-retry sites (P2, next quarter)

→ docs/incidents/2026-04-25-checkout-503.md  (full ADR)
→ tasks/difficulty-book.md  +1 entry: "transparent retries hide upstream health"
```

> **Five analysts, one incident, and the part that mattered was what each one couldn't see alone.**

---

## What these examples are not

- They are not benchmarks. None of them prove "X% better than baseline."
- They are not autonomous. A human reads each agent's output and decides what to do next.
- They are not proof of correctness. The PII scanner can be fooled. The hook can be bypassed (`git commit --no-verify` from a non-Claude-Code shell). The refusal conditions are intent statements documented in agent prompts, not enforced contracts at runtime.

What they are: five recognizable shapes of work where having the system in the loop produced an artifact (a sourced commit, a contention profile, a cited brief, an RCA, a structural-cause ADR) that the same hour without the system would not have produced. The recognition is the entire point.

---

## Reproducing these examples

Each scenario corresponds to a real skill or agent invocation:

| Example | Invocation | Source |
|---|---|---|
| #1 Unsourced constant | `tools/zetetic-checker.sh --staged` + `/verify-claim` | [`tools/zetetic-checker.sh`](../tools/zetetic-checker.sh) + [`skills/zetetic/verify-claim.md`](../skills/zetetic/verify-claim.md) |
| #2 Latency bug | `/genius route "<problem>"` | [`agents/genius/curie.md`](../agents/genius/curie.md) + [`agents/genius/knuth.md`](../agents/genius/knuth.md) |
| #3 Literature search | `/deep-research "<topic>"` | [`skills/research/deep-research.md`](../skills/research/deep-research.md) |
| #4 Architecture refusal | `/implement` (delegate with `GENIUS: curie, dijkstra`) | [`agents/genius/curie.md`](../agents/genius/curie.md) and [`agents/genius/dijkstra.md`](../agents/genius/dijkstra.md): refusal-conditions sections |
| #5 Incident postmortem | `/incident-investigation` | [`skills/engineering/incident-investigation.md`](../skills/engineering/incident-investigation.md) |
