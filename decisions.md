# Décisions binôme — M6-B2 (À COMPLÉTER)

> **À remplir avant de coder.** Les briques forment une chaîne (feedback →
> stockage → jointure → réentraînement → promotion) : figer les contrats est ce
> qui vous permet d'avancer à deux en parallèle sans vous bloquer.

## Contrats d'interface 

```text
Feedback   : {request_id: str, true_label: 0|1, comments: str|None}
Stockage   : table feedbacks(request_id PK, true_label, comments,
             created_at, used_for_training=0)
Comptage   : GET /feedback/count → {"count": int, "new": int}
Mock       : GET /mock-feedback?feedNumber=N → {"inserted": int, "request_ids": [str]}
Retrain    : python scripts/retrain.py --min-feedback N → exit 0
Promotion  : decide_promotion(candidate: dict, production: dict)
             → PromotionDecision(promote: bool, reason: str)
```

Modifications apportées à ces contrats en cours de route : _`GET /mock-feedback`
ajouté (hors périmètre initial des briques A/B) : endpoint de démo/test qui
simule l'arrivée de N feedbacks comme si le cron/le trigger les avait générés,
sans passer par de vraies annotations conseiller. Utile pour tester le seuil
du trigger (200) sans attendre de vrais feedbacks. Incrémental : reprend
toujours après le dernier `request_id` de `prod_scored.csv` déjà injecté (le
`true_label` est dérivé du `loan_status` déjà connu dans ce fichier — en
production cette vérité terrain viendrait de `POST /feedback`, jamais de ce
raccourci). Erreurs : 422 si `feedNumber` non positif, 400 si la demande
dépasse les lignes restantes de `prod_scored.csv`. Implémenté dans
`scripts/feedback_store.inject_mock_feedback`, exposé par
`services/feedback/app/main.py`._

## Trigger de réentraînement

**Seuil retenu : 200** — justification : _On déclenche périodiquement et sous condition si toutes les 6 h,  au moins 200 nouveaux feedbacks_

**On compte** : _les feedbacks non consommés (`used_for_training = 0`)_ —
pourquoi pas le total ? _pour ne pas réutiliser des feedbacks plusieurs fois_

**Implémentation** : `crontab.txt` (`0 */6 * * *`, toutes les 6h), qui appelle
`scripts/retrain.py --min-feedback 200` avec chemins absolus + venv du serveur
de déploiement. Le garde-seuil (compter les non-consommés, sortir en succès
sous le seuil) est à la charge de `retrain.py` (brique C), pas du cron
lui-même. Déclenchement manuel possible via `workflow_dispatch` (CI).

⭐ Second déclencheur « ou dérive confirmée » (bonus) : _non traité_ —
si traité, quelle fonction de M6-B1 est appelée ? _…_

## Jeu de référence retenu 

**Jeu adopté** : _reference_set.csv de M5-B2 de ____ (500 lignes, composition ____)_

**Pourquoi** : _solution plus rapide pour se concentrer sur l'essentiel du brief._

Les seuils M5-B2 s'appliquent tels quels.

> ⚠️ Le plancher de qualité de la politique de promotion vient de vos **seuils
> M5-B2**, calibrés sur **votre** jeu. Mesurer les métriques sur un autre jeu
> revient à comparer deux populations : sur un modèle **inchangé**, l'écart va
> de 0.01 à 0.23 selon la composition. Un seul jeu, du début à la fin.

## Stockage

**Solution de stockage**: SQLite

**Pourquoi** : Permet de lire et d'écrire sans conflit, une historisation d'un volume de données plus important qu'en CSV, et des requetes de consultations plus performantes.

**Localisation du fichier** :
- En local : `data/feedbacks.db` (racine du repo), calculé par `main.py`
  sauf si la variable d'env `FEEDBACK_DB` la surcharge.
- En Docker : `/data/feedbacks.db` — le service `feedback` (`docker-compose.yml`)
  monte le volume `./data:/data` et fixe `FEEDBACK_DB=/data/feedbacks.db`.
- Un seul fichier, partagé (pas de service DB séparé) : le service `feedback`
  y **écrit** (`POST /feedback`) et y lit son compteur (`GET /feedback/count`) ; 
  `scripts/feedback_store.py` appelé depuis `retrain.py`, y **lit** 
  (jointure avec `prod_scored.csv`) et **marque** `used_for_training`. 
  `retrain.py` doit pointer vers le même
  chemin que le service `feedback` (même volume monté).

**Schéma** : table `feedbacks(request_id PK, true_label, comments, created_at,
used_for_training=0)` — cf. section « Contrats d'interface ».

**Cycle de vie de `used_for_training`** :
- Valeur par défaut à l'insertion (`POST /feedback`) : **0** — le feedback vient
  d'arriver, il n'a encore servi à aucun entraînement.
- Passage à **1** : uniquement par `retrain.py`, et uniquement si le candidat
  est **promu**. Un rejet ne marque rien : les feedbacks restent non consommés
  et sont repris au prochain réentraînement, avec les nouveaux qui se seront
  ajoutés d'ici là — un rejet ne doit pas faire perdre des annotations. Un
  échec technique avant la décision ne doit pas non plus marquer de lignes.
- Pourquoi c'est nécessaire : sans ce marquage, le trigger recompterait le
  total à chaque passage du cron et redéclencherait un réentraînement en boucle
  sur les mêmes 200 feedbacks déjà exploités.


## Politique de promotion

| Paramètre | Valeur retenue | Justification |
|---|---|---|
| Métriques critiques | _…_ | _…_ |
| Plancher de qualité | _…_ | _…_ |
| Tolérance de régression | _…_ | _…_ |
| Gain minimum exigé | _…_ | _…_ |

**Pourquoi le recall de la classe défaut est-il contraignant ?**
_(que coûte à Pyrenex un dossier en défaut prédit comme remboursé ?)_ — _…_

**Pourquoi F1 macro plutôt que l'accuracy ?**
_(quel est le taux de défauts dans les données ?)_ — _…_

## Politique de doublon sur les feedbacks

| Cas | Réponse retenue | Justification |
|---|---|---|
| `request_id` inconnu | **404** | On ne stocke que des feedbacks rattachables à un dossier réellement scoré (jointure avec `prod_scored.csv`), sinon ils sont inutilisables au réentraînement. |
| Même `request_id`, même label | **201, sans doublon** | Rejeu réseau (timeout, retry client) : idempotent, ne doit rien casser. On lit avant d'écrire (`SELECT` puis comparaison) plutôt qu'un `INSERT OR REPLACE`. |
| Même `request_id`, label différent | **409** | Deux vérités terrain opposées sur le même dossier : ce n'est pas un rejeu, c'est une contradiction. Un écrasement silencieux enverrait une annotation potentiellement fausse dans le jeu d'entraînement — un humain arbitre. |

## Résultat de notre exécution

**Décision obtenue** : _PROMOTE / REJECT_

| Métrique | Production | Candidat | Écart |
|---|---|---|---|
| f1_macro | _…_ | _…_ | _…_ |
| recall_default | _…_ | _…_ | _…_ |
| roc_auc | _…_ | _…_ | _…_ |

**Ce qu'on en conclut, en une phrase défendable devant Sophie Léger** : _…_

**Chemin de rejet démontré ?** _oui / non_ — comment : _…_

## RGPD

Non : la table `feedbacks` ne stocke que `request_id` (identifiant technique
interne, pas une donnée personnelle en soi), `true_label` (0/1) et un commentaire
libre facultatif. Aucune donnée du dossier (revenu, nom, etc.) n'y est dupliquée
— elle reste dans `prod_scored.csv` et n'est récupérée que par jointure au
moment du réentraînement. Attention au champ `comments` en usage réel : à ne
jamais laisser un conseiller y saisir du nominatif.

## Point de mi-parcours (jeudi 17h)

- État des briques : _…_
- **Switch des rôles** :
    - Figer le jeu de réference, completer ce fichier : ensemble
    - schema mermaid : ensemble
    - brique A et B : Célia
    - brique D : Théo
    - brique C : Théo
    - tests sur A, B, C : Célia
    - verdiction et documentation : ensemble
