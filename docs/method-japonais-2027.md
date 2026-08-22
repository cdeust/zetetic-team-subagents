# Comment japonais-2027 a été conduit

Note de méthode pour l'étude de cas ai-architect.tools. Comment une application
d'apprentissage du japonais (PWA d'un seul fichier, hors ligne, cible JLPT N3)
a été produite en conduite zététique, sur un dépôt privé, entre un propriétaire
sur iPad et une session agent. Aucun contenu Irodori dans cette note.

## 1. La boucle de conduite réellement utilisée

Le propriétaire ne rédige pas de spécifications. Il pilote par **signalements
d'usage**, au niveau du symptôme vécu : « les kana ne dépassent jamais guru »,
« la leçon ne me propose que la bonne réponse », « bouche + I donne naka,
c'est incompréhensible ». Chaque signalement déclenche la même boucle :

1. **Mesurer avant de croire.** Le symptôme est reproduit contre les données
   réelles (comptages dans les JSON, comparaison à la référence EDRDG, audit
   du journal). Quand la mesure contredit le signalement, on le dit, et on
   cherche ce qui a produit la perception : il y a presque toujours un défaut
   réel derrière, ailleurs que là où il était annoncé.
2. **Corriger au minimum**, avec la métrique nommée. Règle debout imposée par
   le propriétaire : un changement qui ne peut pas nommer la métrique qu'il
   améliore n'a pas le droit d'exister.
3. **Verrouiller par un invariant exécutable** qui rejoue le signalement
   d'origine, avec ses valeurs (« la fiche de 中 doit dire au milieu, jamais
   naka »).
4. **Livrer observable** : bump de version affiché à l'écran de l'appareil,
   verrouillé par un invariant BUILD == VERSION. « C'est déployé » n'est pas
   une phrase, c'est une ligne lisible sur l'iPad.

Étiquette git tenue : une préoccupation par commit, staging fichier par
fichier, messages conventionnels qui racontent le défaut mesuré et le
correctif, jamais la chronologie.

Quand un désaccord factuel a persisté (« j'ai plusieurs sessions à 100 %, ils
devraient être ancrés »), la réponse n'a pas été un argument mais un
instrument : un écran d'audit croisant deux mesures indépendantes du même
travail (réponses justes au journal contre rappels comptés par
l'ordonnanceur) a été construit, livré, et a tranché en une capture d'écran.

## 2. Ce qui a porté, et les garde-fous qui ont mordu

Le cadre zététique (rules `model-behavior` et `coding-standards`, contrat
`engineering-loop`) pose trois refus : « pre-existing », un skip, une PR
rouge. Appliqué à ce projet, le principe « les hooks sont l'enforcement, les
instructions sont consultatives » a pris la forme de **portes d'acceptation
embarquées dans le dépôt de l'app** : 9 invariants statiques
(`tools/verifier.py`) et un démarrage réel dans Chromium
(`tools/demarrage.js`, une trentaine de blocs nommés qui rejouent les
signalements). La sortie rouge dit « Ne pas livrer », et rien ne part tant
qu'elle le dit.

Deux morsures réelles, tirées de l'historique :

- L'ajout du cliquet d'ouverture des niveaux a fait échouer le bloc `import`
  (« niveaux = 0, attendu 1 ») : le test a forcé à distinguer un niveau
  ouvert automatiquement d'un niveau importé, au lieu de laisser passer une
  ambiguïté silencieuse.
- La sortie des cartes sonores des sections kana a fait échouer le bloc
  `bascules`, qui exigeait des cartes « en pause » sur un niveau de kana. Le
  test a été re-ciblé en conscience sur la dictée de mots, dans le même
  commit que le changement de comportement, jamais contourné.

Règle debout du propriétaire, appliquée sans exception : **rien n'est rédigé
de mémoire**. Sens des kanji : KANJIDIC2 (EDRDG). Décompositions : base IDS
du projet CJKVI. Étymologies : makemeahanzi (dérivé de Wiktionary), hints
traduits fidèlement, hints vides écartés. Lectures furigana : Janome/IPAdic,
un mot que le dictionnaire ne sait pas lire reste sans interligne plutôt que
faux. Chaque mécanisme d'apprentissage est adossé à une source vérifiée
(tableau « Fondements » du README : Cepeda, Karpicke, Dumay et Gaskell,
Pashler), et les extrapolations sont marquées comme telles.

## 3. Ce que les standards ont imposé qu'un build naïf aurait sauté

- **RLS sur chaque table Supabase**, chaque ligne liée à `auth.uid()`. C'est
  ce qui rend la clé publiable réellement publiable.
- **Aucune donnée sous droits dans le dépôt** : le `.gitignore` bloque les
  fichiers de programme extraits ; le contenu du manuel commercial vit
  uniquement chez l'utilisateur, l'app renvoie au manuel officiel gratuit au
  lieu de le recopier.
- **La synchronisation ne fait jamais autorité en silence** : trois modes
  nommés (fusionner, cet appareil, la base), la fusion garde la carte la plus
  avancée, et l'écran nomme le côté qui disparaît avant d'écraser.
- **Le silence est étiqueté** : son coupé, l'interface le dit sur la carte
  plutôt que de ressembler à une panne. Un item est jugé sur ce qu'on peut
  travailler, jamais sur ce qui attend.
- **Attribution des sources de données** dans le README : EDRDG (CC BY-SA
  4.0), CJKVI IDS (GPLv2), makemeahanzi, Janome/IPAdic.

## 4. Phrases prêtes pour l'étude de cas

« J'ai construit l'application par signalements d'usage. Je décrivais le
symptôme, l'agent mesurait, corrigeait, puis verrouillait le correctif par un
test qui rejoue exactement mon signalement. »

« Aucun contenu n'a été inventé. Chaque sens de kanji, chaque étymologie,
chaque lecture vient d'une source citée, et un trou dans la source reste un
trou visible plutôt qu'une invention. »

« Quand je n'étais pas d'accord avec l'application, on n'a pas débattu. On a
construit l'écran qui affiche les deux mesures, et les chiffres ont tranché. »

« Dix invariants exécutables gardent la porte. Si l'un échoue, la sortie dit
ne pas livrer, et ça ne part pas. »

## 5. À ne pas publier

- **Tout contenu Irodori** (© The Japan Foundation) : textes de cartes,
  listes de vocabulaire, objectifs Can-do, phrases extraites, fichiers de
  programme JSON, et toute capture d'écran montrant le cursus installé. Les
  captures propres sont dans `japonais-2027/docs/captures/` (dépôt seul,
  aucun cursus).
- **Les exports de progression et le journal** : données personnelles.
- Si des données dérivées (composants, étymologies, lectures) sont un jour
  redistribuées hors de l'app, les licences amont s'appliquent et se citent :
  CC BY-SA 4.0 pour KANJIDIC2, GPLv2 pour CJKVI IDS, licences makemeahanzi.
