# Refonte « graph of agents » — banque de génies + skills comme topologies

**Objectif** : faire converger l'architecture vers ce que la littérature 2026 valide —
la banque de génies devient un *pool échantillonnable par carte*, et les skills
problem-shaped deviennent des *patterns de réflexion exécutables* (topologie de
collaboration) au lieu d'annuaires d'agents.

**Statut** : Phase 2 livrée (2026-08-04). Phases 0, 1, 3, 4 à faire.

**Écart d'ordre assumé** : l'utilisateur a arbitré le 2026-08-04 de livrer la Phase 2
(les 4 shapes manquants) **avant** la Phase 0, en ayant le coût affiché — la baseline
ne mesurera donc pas l'état à 11 skills. Le point de comparaison n'est pas perdu pour
autant : l'état pré-Phase-2 est le commit `456908c`, et le harnais Phase 0, une fois
construit, se rejoue dessus sans rien réécrire :

```bash
git worktree add /tmp/goa-baseline-11 456908c   # état à 11 skills
# exécuter le harnais Phase 0 contre ce worktree, puis contre HEAD
```

C'est une récupération, pas une équivalence : la baseline à 11 skills sera mesurée
*après* que les 4 shapes ont été écrits, donc par un harnais dont la conception les
connaît déjà. Ce biais de conception est réel et doit être déclaré dans `docs/SCORECARD.md`.

---

## Sources (lues, pas citées de seconde main)

| Source | Ce qu'elle établit | Transférabilité ici |
|---|---|---|
| Graph-of-Agents, ICLR 2026, [arXiv:2604.17148](https://arxiv.org/abs/2604.17148), code [UNITES-Lab/GoA](https://github.com/UNITES-Lab/GoA) | Node sampling par *model cards* → 3 agents sélectionnés battent 6 agents utilisés en bloc. Arêtes par évaluation croisée des réponses, message passing dirigé **puis inverse**, agrégation par pooling. | Mécanisme transférable. **Chiffres non transférables** : le pool GoA est un zoo de 6 LLM hétérogènes, le gain vient en partie de la diversité des poids. Voir Phase 4. |
| SIGMA, [arXiv:2606.19758](https://arxiv.org/abs/2606.19758) | Agents = *bundles de skills réutilisables conditionnés à la tâche* ; matrice d'incidence skill↔agent ; topologie décodée ; mailboxes par skill. +2,06/+2,36/+1,75 pts vs CARD sur 6 benchmarks × 3 base LLM ; **−0,96 pt seulement sur skill libraries inédites**. | Source la plus transférable : spécialisation par composition, pas par poids. C'est l'inversion skills↔agents visée ici. |
| MetaGen, [arXiv:2601.19290](https://arxiv.org/abs/2601.19290) | Role space **et** topologie adaptés à l'inference time, sans mise à jour des poids ; backbone minimal ; ajustement par feedback léger. | Justifie que la topologie soit choisie au runtime, pas figée dans le `.md`. |

---

## État mesuré (2026-08-04, commit `456908c`)

| Ce que la littérature suppose | État du repo | Preuve |
|---|---|---|
| Banque + carte par agent | ✅ acquis | `shapes:` en frontmatter des 97 génies (`agents/genius/curie.md:10`) |
| Sélection dynamique parcimonieuse | ❌ lookup statique **recopié 3×** | `agents/genius/INDEX.md`, `rules/agent-routing-table.md`, tables « Relevant geniuses » des 15 `SKILL.md` |
| Skills = capacités composables | ❌ inversé : annuaires d'agents | `skills/measurement-discipline/SKILL.md:20-30` (« Pick the best-fit agent above ») |
| Topologie : arêtes, passe inverse, pooling | ❌ absente | `genius-invoker.sh compose a b` = chaîne linéaire, sans évaluation croisée ni agrégation |
| Pool hétérogène (condition GoA) | ⚠️ amorcé à 1/15 | `plugins/zetetic-reasoning/` porte **une seule** skill (evidence-synthesis) + 8 références vers Codex / Gemini CLI |
| Couverture de la banque | ✅ 97/97 depuis Phase 2 | était 82/97 au commit `456908c` |

**Correction de comptage** — historique, gardée parce qu'elle explique la gate ajoutée :
au commit `456908c` il y avait 11 skills problem-shaped, pas 15, et `skills/_index.md:3`
annonçait « 75 skills » quand l'arbre en portait 76. Les 4 manquantes étaient dérivées de la
couverture, pas inventées. Depuis la Phase 2 : 15 problem-shaped, 80 au total, et les trois
compteurs de `skills/_index.md` comme ceux de `docs/COUNTING.md` sont désormais gatés par
`tools/doc-count-check.sh` — la dérive qui a rendu cette note nécessaire ne peut plus se reformer
silencieusement sur ces deux fichiers.

---

## Invariants zététiques — non négociables, priment sur les papiers

Adoption pleine du mécanisme, **pas** de sa métaphysique. Les papiers optimisent une
exactitude moyenne sur benchmark ; ce projet optimise une conclusion défendable. Là où
les deux divergent, c'est le standard zététique qui gagne, et la divergence est documentée.

1. **L'agrégation n'est pas un vote.** Le pooling max/mean de GoA est une moyenne d'opinions —
   antithétique au standard : une majorité n'est pas une preuve. L'agrégation retient ici ce qui
   **survit à la réfutation**, pas ce qui recueille le plus de voix. Un désaccord non résolu se
   **rapporte comme désaccord**, jamais ne se moyenne.
2. **Les génies ne sont pas des nœuds interchangeables.** La valeur d'un génie est son
   `<workflow>` et son `<output-format>`, pas sa position dans le graphe. La topologie **ordonne**
   les génies ; elle ne les remplace pas. Un génie dont le workflow est court-circuité par le
   message passing est un génie perdu — c'est un échec de la refonte, pas une optimisation.
3. **Les conditions de refus survivent à la topologie.** Le bloc `Refuse when` de chaque skill
   est terminal : aucune agrégation ne peut produire une conclusion quand un nœud a refusé faute
   de données ou de source. Le refus se propage, il ne se dilue pas.
4. **k ≥ 2 avec indépendance réelle.** GoA réduit `k` pour le coût ; le standard zététique exige
   deux méthodes indépendantes (`curie: two-independent-methods`). La parcimonie ne peut donc
   jamais descendre à un seul nœud, et deux nœuds qui partagent la même méthode ne comptent que
   pour un.
5. **Traçabilité de bout en bout.** Toute sortie agrégée nomme quel génie a produit quelle
   affirmation et sur quelle source. Un pooling qui efface l'attribution est refusé.

## Phase 0 — Mesurer avant de toucher

Sans instrument, la refonte est une opinion. Règle bench-before-release.

- [ ] Construire un jeu de problèmes étiquetés par shape (≥ 40 cas, **minés des transcripts de
      sessions réelles**, pas imaginés — cf. A7 fixture-mining de `tasks/agent-coverage-roadmap.md`).
- [ ] Mesurer la baseline sur trois axes séparés :
      **(a) routage** — le shape attendu est-il sélectionné ? (top-1, recall@k ; déterministe, sans LLM juge)
      **(b) sortie** — les éléments exigés par l'`<output-format>` du génie sont-ils présents ?
      (assertion structurelle mécanique : `fermi` doit rendre deux bornes, `curie` une seconde
      méthode indépendante, etc. — signal externe faible mais **jamais auto-évalué**, cf. arXiv:2310.01798)
      **(c) préservation zététique** — taux de refus correctement propagés, taux d'affirmations
      attribuées à une source. C'est l'axe qui protège les invariants ci-dessus ; **une refonte qui
      gagne sur (a) et (b) en perdant sur (c) est rejetée.**
- [ ] Publier la baseline dans `docs/SCORECARD.md`. Aucune phase suivante n'est mergée sans delta
      mesuré contre elle, sur les **trois** axes.

## Phase 1 — La banque devient source unique (GoA : node sampling)

- [ ] Faire du frontmatter `shapes:` la **seule** source de vérité du routage.
- [ ] Étendre `scripts/generate-routing-table.py` pour générer aussi `agents/genius/INDEX.md`
      et les tables « Relevant geniuses » des `SKILL.md`.
- [ ] Gate CI : toute dérive entre source et vues générées = build rouge.
- [ ] Vérifier la pression sur le cap de 15k tokens des descriptions cumulées
      (cf. bloc `<routing>` de `curie.md`, qui documente déjà ce déplacement).

## Phase 2 — 11 → 15 skills, couverture complète de la banque ✅ LIVRÉE 2026-08-04

Les 15 génies orphelins, regroupés par shape (arbitré et écrit) :

- [x] **`normative-design`** — règles, équité, précédent, responsabilité diffuse.
      `rawls` (veil-of-ignorance, fairness-as-procedure), `hart` (open-texture, precedent, proportionality),
      `arendt` (thoughtlessness-audit, cog-in-machine), `foucault` (genealogy, archaeology-of-assumptions).
- [x] **`narrative-sensemaking`** — récit, plausibilité structurelle, morphologie.
      `bruner` (narrative-vs-paradigmatic, canonical-breach), `propp` (function-extraction, gap-detection-via-grammar),
      `ibnkhaldun` (structural-plausibility-filter, confirmation-bias-detection).
- [x] **`representation-and-possibility`** — la notation empêche de voir ; quel est l'espace complet ?
      `euler` (notation-as-infrastructure, abstraction-by-deletion), `borges` (exhaustive-space-audit, map-territory),
      `lem` (possibility-space, push-to-logical-extreme), `archimedes` (cross-domain-discovery, heuristic-then-proof).
- [x] **`experience-and-transmission`** — l'artefact est correct mais personne ne l'adopte ni ne le comprend.
      `vygotsky` (ZPD, scaffolding-and-fading), `jobs` (integrated-experience-as-spec, no-seams),
      `varela` (observer-inside-system, first-person-as-data), `knuth` (literate-programming, build-the-tool-use-the-tool).
- [x] Mettre à jour `tools/doc-count-check.sh` (le compte 11 est gaté) et `skills/_index.md`.
      Fait au-delà du strict nécessaire : `skills/_index.md` et `docs/COUNTING.md` n'étaient
      gatés par **rien** — d'où la dérive 75/76 trouvée en passant. Six claims ajoutés au
      registre, chacun vérifié par test négatif. `docs/COUNTING.md` portait aussi deux
      valeurs fausses antérieures (`tools` 43→46, `suites` 27→28), corrigées.
      Reste hors rayon : les 9 autres lignes du tableau de `COUNTING.md` (agents, hooks,
      commands, tools, suites, memory_suites) restent non gatées et redériveront.

## Phase 3 — Skills = topologies exécutables (SIGMA + GoA)

- [ ] Nouveau bloc dans chaque `SKILL.md` : **rôles requis par shape** (jamais par nom d'agent),
      `k` (2–3, parcimonie GoA), arêtes de critique (qui évalue qui), passe inverse, règle d'agrégation.
- [ ] `tools/genius-invoker.sh` gagne un verbe `topology` : échantillonne k rôles depuis la banque,
      exécute la topologie déclarée, agrège. `compose` reste pour les chaînes linéaires explicites.
- [ ] La passe inverse et l'agrégation sont le **gain principal attendu** — c'est le seul mécanisme
      totalement absent aujourd'hui. Le mesurer isolément contre la baseline Phase 0.
- [ ] Refuser toute topologie qui n'a pas de critère d'arrêt écrit.

## Phase 4 — Rendre le pool réellement hétérogène (condition expérimentale de GoA)

C'est ici que le gain GoA devient légitimement invocable, et pas avant.

- [ ] Étendre `tools/sync-portable-references.py` au-delà d'`evidence-synthesis` :
      porter les shapes de la banque vers Codex et Gemini CLI.
- [ ] Mesurer le delta homogène (Claude seul) vs hétérogène (Claude + Codex + Gemini) sur le harnais Phase 0.
      **Si le delta n'est pas positif, la refonte s'arrête à la Phase 3 et on le documente.**

---

## Gates à repasser à chaque phase

`craftsmanship-checker.sh`, `agent-definition-auditor.sh`, `zetetic-checker.sh`,
`doc-count-check.sh`, `doc-command-check.sh`, suite pytest (gate dur, plancher 80 %),
`mutation_check.sh` sur les lignes changées.

## Ce que ce plan ne promet pas

- Aucun gain chiffré repris de GoA tant que la Phase 4 n'a pas mesuré le pool hétérogène.
- Aucune matrice d'incidence apprise (SIGMA prédit la sienne par un modèle entraîné ;
  ici la sélection reste par appariement de shapes — c'est une simplification assumée, pas une reproduction).
