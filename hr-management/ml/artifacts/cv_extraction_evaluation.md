# Évaluation de l'extraction de CV par l'assistant IA

Jeu de test : 16 CV synthétiques mais réalistes (`ml/fixtures/cv_eval_set.json`),
avec vérité terrain annotée à la main pour six champs. Contrairement à la
suite `pytest` (qui n'utilise qu'un client IA factice — voir
`tests/test_ai.py`), cette évaluation appelle **réellement** l'API IA
(`ml/evaluate_cv_extraction.py`), pour mesurer une exactitude réelle plutôt
que de supposer qu'un essai manuel isolé est représentatif.

## Méthodologie

L'évaluation a été exécutée plusieurs fois de suite (même jeu de CV, mêmes
appels API), afin de distinguer une erreur ponctuelle d'une limite
systématique du modèle — une extraction en apparence fiable sur un seul
passage peut masquer une instabilité réelle.

## Un bug réel trouvé, corrigé, puis vérifié

Le premier passage (12 CV, avant l'ajout de cas plus difficiles) donnait
100 % d'exactitude — un résultat trop parfait pour être représentatif. En
ajoutant des cas plus exigeants (numéro de téléphone au format
« 06.12.34.56.78 », en-tête décoratif, CV bilingue, signal de type de
contrat volontairement contradictoire), un vrai défaut est apparu : le
téléphone extrait pour le format à points était systématiquement rejeté
(`None`) alors qu'il était bien présent dans le texte.

**Cause :** la consigne donnée au modèle précisait le format attendu pour
`birth_date` (AAAA-MM-JJ) mais ne précisait rien pour `phone` — le modèle
renvoyait donc le numéro tel quel, avec les points d'origine, qui ne
correspondait plus à l'expression régulière de validation de l'application
(chiffres uniquement). Le champ était alors correctement rejeté par cette
validation (le même mécanisme qui rejetterait un CIN mal formé saisi au
clavier) — mais silencieusement, sans qu'on sache pourquoi.

**Correction :** la consigne précise désormais explicitement le format de
sortie attendu pour le téléphone (chiffres uniquement, préfixe +212
optionnel). Deux exécutions complètes après correction confirment que ce
cas précis est désormais traité correctement à chaque fois (voir
`ml/artifacts/cv_extraction_runs/`).

## Résultat agrégé (2 exécutions après correction)

| Champ | Exact (sur 32) | Exactitude |
|---|---|---|
| first_name | 31 | 96,9 % |
| last_name | 31 | 96,9 % |
| professional_email | 31 | 96,9 % |
| phone | 32 | **100 %** |
| birth_date | 31 | 96,9 % |
| suggested_contract_type | 28 | 87,5 % |
| **Global** | 184 / 192 | **95,8 %** |

## Deux limites réelles, non corrigées, documentées honnêtement

1. **`suggested_contract_type` est le champ le moins stable.** Sur le cas
   volontairement contradictoire (« actuellement en CDI, mais ouvert à une
   mission CDD ponctuelle »), le modèle a proposé un type de contrat aux
   deux exécutions alors que la vérité terrain attendue est « aucune
   suggestion » — l'entrée est authentiquement ambiguë, et le modèle ne
   s'abstient pas de façon fiable dans ce cas. C'est cohérent avec le
   choix de conception existant : cette suggestion reste une proposition
   affichée avec un badge « IA », jamais une valeur imposée, précisément
   parce qu'elle est moins fiable que l'extraction de champs factuels.
   Piste d'amélioration : demander explicitement au modèle un niveau de
   confiance, ou renforcer la consigne pour qu'il s'abstienne plus
   agressivement en cas de signaux contradictoires.

2. **Un échec d'extraction complet a été observé une fois** (tous les
   champs revenus à `None` pour un seul CV, sur un total de 32 appels
   répartis sur deux exécutions), sans lien évident avec le contenu du CV
   concerné. Hypothèse la plus probable : les 16 appels d'une exécution
   sont envoyés à la suite sans délai, ce qui peut occasionnellement
   heurter une limite de débit ou un incident transitoire côté
   fournisseur. `app/services/ai_service.py` traite déjà toute erreur du
   fournisseur comme un 503 avec repli sur la saisie manuelle — jamais un
   plantage — mais une politique de nouvelle tentative (retry avec
   backoff) sur un échec isolé serait une amélioration naturelle,
   documentée ici comme perspective plutôt qu'implémentée dans le cadre
   de ce projet.

## Constat global

Les champs strictement factuels (nom, email, téléphone, date de naissance)
sont extraits de manière fiable (~97–100 %) une fois le format de sortie
explicitement spécifié. Le champ inférentiel (type de contrat suggéré) est
nettement moins stable — un résultat cohérent avec la nature même de la
tâche : extraire un fait présent dans le texte est plus fiable qu'inférer
une intention à partir d'un signal parfois contradictoire.
