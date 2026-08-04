# Roadmap — Agent team: zéro trou dans la raquette

**Objectif** : rendre la team d'agents *prouvablement* fiable (le processus attrape ses propres erreurs), pour
faire passer Cortex de « approuvé par quelques-uns » à « approuvé par le grand public ».
**Principe directeur** : la confiance = boucle fermée où *chaque affirmation est vérifiée de façon adverse* et
*chaque suite de tests est prouvée efficace par mutation*. Critères d'acceptation = signaux EXTERNES (mesure,
exécution), jamais le modèle qui se relit lui-même (arXiv:2310.01798).
**Ancrage** : session zetetic-checker UNSOURCED — fixtures d'exemple + CI verte cachaient une classe entière de
faux positifs, rattrapée seulement par une vérif adverse multi-agents. C'est le mode d'échec à éliminer partout.

---

## Taxonomie de couverture (la "raquette" complète — rien hors de cette grille)

| # | Type de test | Manque ? | Agent/outil propriétaire |
|---|---|---|---|
| 1 | Example / unit | présent | test-engineer |
| 2 | Contract / port (Liskov) | **absent** (suite-contrat partagée) | test-engineer + génie `liskov` |
| 3 | Property-based (invariants) | **absent** | test-engineer + génie `popper` |
| 4 | Metamorphic (relations, sans oracle) | **absent** | test-engineer + génie `curie` |
| 5 | Characterization / golden-master (Feathers) | **absent** | test-engineer |
| 6 | Boundary / equivalence partitioning | ad hoc | test-engineer + génie `borges` |
| 7 | Fuzz / adversarial input | **absent** | test-engineer + génie `popper` |
| 8 | Mutation (efficacité de la suite) | référencé, non construit | **nouveau** mutation-runner + test-suite-auditor |
| 9 | Concurrence / race / idempotence / déterminisme | **absent** | test-engineer + génie `lamport` |
| 10 | Robustesse numérique (NaN/inf/ties/vide) | **absent** | test-engineer + génie `curie` |
| 11 | Performance / régression SLO (p95 recall) | **absent** | experiment-runner + devops-engineer |
| 12 | Differential (vs baseline / impl de réf) | **absent** | test-engineer |
| 13 | Integration / e2e cross-couches | partiel | test-engineer |
| 14 | Spec-coverage / traçabilité (claim→test) | **absent** | **nouveau** outil + génie `wu` |
| 15 | Observability / invariants runtime (assertions prod) | **absent** | devops-engineer / mlops |
| 16 | Fixtures minées du réel (pas imaginées) | **absent** | test-engineer |

---

## TRACK A — Doter la team (capacités), pour qu'elle n'ait pas d'angle mort

- **A1. test-engineer — nouveaux *moves* nommés** : metamorphic, property-based, characterization-harness,
  boundary-enumeration, contract-from-interface, concurrency/idempotence, numerical-battery, differential,
  fixtures-from-real. Chaque move = recette + scaffold (Hypothesis/proptest/golden) + critère d'acceptation.
- **A2. Vérification adverse PAR DÉFAUT** : transformer le red-team manuel en phase obligatoire du pipeline.
  Livrable : `.claude/workflows/adversarial-verify.js` (4 lentilles : FP-résiduels/over-fit, cas manqués,
  robustesse, adéquation-tests) invoqué automatiquement par code-reviewer avant tout "done".
- **A3. Mutation runner** (= follow-up #2) : construire le vrai runner (refs dans tools/craftsmanship-checker.sh,
  tools/semantic_layer.py, tools/tests/hook-layer/). Gate "who-tests-the-tests".
- **A4. test-suite-auditor** : agent/move qui lance mutation + coverage-vs-spec et rapporte mutants survivants +
  invariants non couverts. Bloque si score mutation < seuil.
- **A5. Pont génie→test** : recette de composition transformant un raisonnement génie en artefact de test concret
  (`popper`→cas de falsification, `borges`→audit d'espace exhaustif, `lamport`→scénarios concurrents,
  `liskov`→suite-contrat, `wu`→liste d'hypothèses non testées, `curie`→discipline de mesure).
- **A6. Outil spec-coverage** : mappe chaque invariant documenté → id(s) de test ; CI rouge si un invariant
  documenté n'a aucun test.
- **A7. Fixture-mining** : capacité à dériver les fixtures du corpus/sessions réels (pas inventées).

---

## TRACK B — Appliquer à Cortex, couche par couche (boucle Feathers, incrémental)

Pour CHAQUE couche, dans l'ordre :
`(1) seams + characterization (épingler l'existant) → (2) abstraction sémantique sous le filet (préservation de
comportement, mutation-checked) → (3) promouvoir characterization → property/contract (invariants voulus) →
(4) red-team adverse de la suite → (5) seulement alors : ouvrir aux contributeurs (la suite-contrat = la doc d'onboarding)`

Ordre recommandé (du plus borné au plus diffus) :
1. **Store (PG + SQLite)** — le plus borné. Suite-contrat UNIQUE rejouée par les 2 backends → débloque les
   nouveaux backends contributeurs. (types 2, 5, 9)
2. **Retrieval / fusion** (WRRF, vector+FTS+trigram+heat+recency, rerank FlashRank) — metamorphic + property +
   numérique. Invariants : RRF indépendant de l'ordre sur ties ; match exact jamais évincé ; doc non pertinent
   ne change pas le top-k d'une requête sans rapport. (types 3, 4, 10, 12)
3. **Cycle mémoire** (décroissance / consolidation / heat) — property de monotonie (décroissance ne monte jamais
   le heat) + golden-master du dream cycle. (types 3, 5)
4. **Sync queue / concurrence** — race / idempotence / déterminisme (la doc *affirme* idempotent : le prouver). (type 9)
5. **Profils / EMA** — property + characterization. (types 3, 5)
+ transverse : **perf SLO** (p95 recall, type 11) et **invariants runtime** (type 15).

---

## Définition de "DONE = pas de trou" (signaux externes, mesurables)
- [ ] Score mutation ≥ seuil par module (mesuré par le runner A3).
- [ ] Suite-contrat verte sur PG ET SQLite (type 2).
- [ ] Property/metamorphic : N cas exécutés sans falsification par couche.
- [ ] Chaque invariant documenté tracé vers ≥1 test (outil A6).
- [ ] Workflow adverse (A2) sur la suite de chaque couche : 0 blocker survivant.
- [ ] SLO perf : régression p95 mesurée < seuil sur jeu de requêtes figé.
- [ ] Couverture de la taxonomie : les 16 lignes ont un propriétaire + ≥1 artefact par couche concernée.

## Premier pas exécutable (session fraîche)
**WF‑PRE (readiness audit) D'ABORD** — produire le readiness manifest, fermer les gaps jusqu'au vert total.
Aucune Phase 0 (instruments) tant que la team ne peut pas exécuter sans erreur. Ensuite seulement : Phase 0
(WF‑0.1 mutation runner), Phase 1 (capacités), puis Track B couche 1 (Store). L'ordre instruments-avant-mesure
et readiness-avant-instruments est non négociable.

---

## PLAN D'EXÉCUTION — chaîne de workflows successifs (PAS un workflow unique)

**Règles de méticulosité (non négociables)** :
- 1 workflow = 1 phase BORNÉE (fan-out réduit), jamais "tout d'un coup".
- **Porte de revue externe entre CHAQUE workflow** : je résume → l'utilisateur valide → workflow suivant.
  Aucun auto-chaînage d'étapes larges ou destructrices.
- Sortie de chaque workflow **vérifiée de façon adverse AVANT acceptation** (avec l'infra Phase 0).
- Resumable (`resumeFromRunId`) + checkpoint après chaque workflow.
- 1 couche Cortex à la fois ; ne JAMAIS toucher une couche avant que son filet characterization existe.
- 1 commit (petit, auditable) par artefact vérifié — l'historique auditable fait partie de la confiance publique.

### Phase −1 — READINESS : la team peut-elle exécuter sans erreur ? (TOUT PREMIER MAILLON)
Avant de construire ou lancer quoi que ce soit, prouver que chaque cause *évitable* d'échec ou de sortie fausse
est éliminée. Mode d'échec à tuer : agent qui ne charge pas, outil/lib manquant, doc périmée qui induit l'agent
en erreur (cf. bug `limit`→`max_results` qui cassait `recall`), baseline rouge, prompt de permission qui gèle un
workflow en arrière-plan. C'est l'équivalent du gate hygiene-pre (running/installed == committed HEAD).

**« Éléments nécessaires » = inventaire de complétude sur ces axes (liste NON exhaustive — voir critique de
complétude ci-dessous)** :
- **OUTILS** : CLIs, libs, runtimes, frameworks test/mutation/property, MCP, harnesses, hooks, permissions.
- **MÉTHODES** : les *moves*/recettes que chaque agent doit POSSÉDER pour exécuter sa part (metamorphic-design,
  characterization, boundary-enumeration, contract-from-interface, concurrency-harness, numerical-battery,
  red-team adverse…). Une méthode absente = gap readiness → **alimente le backlog Track A**.
- **FONCTIONNALITÉS** : ce que la team sait faire de bout en bout (produire un structured-output, spawn worktree,
  lancer une mutation et en rapporter le score, tracer claim→test, draîner la sync queue…).
- **CONTRATS/ENV** : conventions cohérentes, baseline vert, sandbox déterministe.

Méthode d'audit (move Mendeleev) : dresser le TABLEAU complet `élément requis × {présent | absent + work-item}`
pour chaque axe ; **toute case absente est soit fermée, soit transformée en item de backlog daté** — rien ne
reste implicite. Clôturer par une **critique de complétude** (génie `borges`/`wu`) : « qu'est-ce qui manque
qu'on n'a PAS listé ? » (modalité non testée, méthode supposée mais jamais vérifiée, fonctionnalité jamais
exercée) — la liste étant non exhaustive, cette passe est obligatoire.

- **WF‑PRE.1 Intégrité de la flotte** : chaque agent du plan (test-engineer, code-reviewer, refactorer,
  devops-engineer, experiment-runner, orchestrator, génies popper/borges/lamport/liskov/wu/curie) charge ;
  frontmatter valide (name/description/tools/model) ; grants d'outils suffisants pour son rôle ; routing-table
  régénérée et en phase avec les frontmatters ; pas de doublon plugin/local non résolu (ex. memory-writer).
- **WF‑PRE.2 Outils & runtimes** : CLIs présents+versionnés (bash, git ; **grep BSD vs GNU — figer un sous-ensemble
  portable ou exiger ggrep** ; python3 + frameworks test/coverage/mutation/property [Hypothesis], node/ts +
  [fast-check/Stryker], rust/cargo + [proptest/cargo-mutants] selon les couches) ; **décider l'outil mutation &
  property PAR langage maintenant** (pas en plein workflow) ; checkers existants tournent sans erreur interne.
- **WF‑PRE.3 MCP & mémoire** : santé cortex MCP (recall/remember joignables, coldStart résolu, replica queue
  drainée) ; ai-architect-mcp-codebase MCP configuré OU dégradation gracieuse documentée ; memory-tool.sh OK.
- **WF‑PRE.4 Permissions & sandbox** : pré-autoriser (settings allowlist) les opérations des workflows (runs de
  test bash, écritures, `git worktree add/remove`) pour **zéro prompt en cours de workflow** (un prompt gèle un
  run en arrière-plan) ; isolation worktree fonctionnelle ; scratch dirs isolés.
- **WF‑PRE.5 Baseline VERT (hygiene-pre)** : toutes les suites existantes passent sur checkout propre
  (hook-layer, zetetic-checker, sqlite) ; on **ne mesure jamais mutation/régression contre un baseline rouge** ;
  hooks installés ET effectifs (le checkpoint notait un hook installé mais non effectif → défaut readiness à corriger).
- **WF‑PRE.6 Contrats & conventions cohérents** : coding-standards.md, vocabulaire de couches, contrat mémoire,
  worktree-protocol chargent sans se contredire ni contredire le code (détecter les docs périmées — la classe
  exacte qui fait errer les agents) ; mécanisme structured-output opérationnel ; "definition of done" partagée.

**Gate Phase −1** : un *readiness manifest* (1 doc) où CHAQUE ligne est verte, reproduit par re-run de l'audit.
Boucle : WF‑PRE (audit, lentilles read-only) → liste de gaps → fermeture des gaps (petits commits) → re-audit
jusqu'au vert total. **Aucune Phase 0 tant que le manifest n'est pas 100% vert.**

### Phase 0 — Instruments (l'étalon avant la mesure). Rien en aval n'est prouvable sans ça.
- **WF-0.1 Mutation runner (A3)** — implémenter sur les refs existantes ; preuve : tue ≥1 mutant injecté connu.
  Gate : mutant tué, reproductible. Revue.
- **WF-0.2 Workflow `adversarial-verify` réutilisable (A2)** + câblage code-reviewer. Preuve : rejoué sur le
  diff #3 UNSOURCED → reproduit la classe de findings (auto-régression du vérificateur). Gate. Revue.
- **WF-0.3 spec-coverage (A6) + test-suite-auditor (A4)** — preuve : rapporte mutants survivants + invariants
  non tracés sur 1 module échantillon. Gate. Revue.

### Phase 1 — Capacités d'écriture (vérifiées AVEC l'infra Phase 0).
- **WF-1.1 Moves test-engineer (A1)** — recettes + scaffolds (metamorphic/property/characterization/boundary/
  contract/concurrency/numerical/differential). Gate : chaque move a un scaffold runnable qui attrape un bug semé.
- **WF-1.2 Pont génie→test (A5) + fixture-mining (A7)** — Gate : 1 artefact de test issu d'1 génie ; 1 jeu de
  fixtures miné du corpus réel.

### Phases 2→6 — Track B, UNE mini-chaîne Feathers PAR couche (Store → fusion → cycle mémoire → sync → profils).
Pour chaque couche L, workflows successifs avec gate entre chacun :
- **WF-L.a Characterization** — épingler le comportement actuel (golden-master sur corpus réel). Gate : snapshots
  commités, reproductibles.
- **WF-L.b Property/Contract** — encoder les invariants. Gate : N cas exécutés, 0 falsification sur le code actuel.
- **WF-L.c Mutation + red-team adverse** de la suite de L. Gate : score mutation ≥ seuil, 0 blocker survivant.
- **WF-L.d (si refactor) Abstraction sémantique sous le filet** — préservation de comportement ; re-run a→c verts.

Une couche n'est déclarée "ouverte aux contributeurs" qu'après WF-L.c vert (la suite-contrat = la doc d'onboarding).

### Cadence
~3 workflows (Phase 0) + 2 (Phase 1) + 3–4 par couche × 5 couches ≈ **20–25 workflows successifs**, chacun
gated. Volontairement lent et vérifié à chaque pas — c'est le prix de la confiance grand public.
