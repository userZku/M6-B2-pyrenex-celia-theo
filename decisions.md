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
Retrain    : python scripts/retrain.py --min-feedback N → exit 0
Promotion  : decide_promotion(candidate: dict, production: dict)
             → PromotionDecision(promote: bool, reason: str)
```

Modifications apportées à ces contrats en cours de route : _…_

## Trigger de réentraînement

**Seuil retenu : 200** — justification : _On déclenche périodiquement et sous condition si toutes les 6 h,  au moins 200 nouveaux feedbacks_

**On compte** : _les feedbacks non consommés (`used_for_training = 0`)_ —
pourquoi pas le total ? _pour ne pas réutiliser des feedbacks plusieurs fois_

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
| `request_id` inconnu | _…_ | _…_ |
| Même `request_id`, même label | _…_ | _…_ |
| Même `request_id`, label différent | _…_ | _…_ |

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

_… les feedbacks contiennent-ils de la PII ? …_

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
