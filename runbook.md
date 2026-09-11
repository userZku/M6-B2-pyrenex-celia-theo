# Runbook d'astreinte — Pyrenex Prod

Objectif: permettre a une astreinte SRE non data de restaurer le service vite
et sans aggraver l'incident.

## 1. Service KO (un conteneur down)

**Declenchement**
- Panel Grafana "Vie - Service up (1=up, 0=down)" a 0 pour `model` ou `backend` pendant plus de 1 minute.
- Ou `docker compose ps` montre un service `Exit`/`Restarting`.

**Actions**
1. Identifier le service impacte: `docker compose ps`.
2. Lire la cause immediate: `docker compose logs --tail=200 model` ou `docker compose logs --tail=200 backend`.
3. Redemarrer uniquement le service KO: `docker compose restart model` ou `docker compose restart backend`.
4. Verifier le retour a la normale: `/health` repond 200 et panel "up" revient a 1.
5. Si toujours KO apres 2 redemarrages en 10 min, escalader.

**Qui appeler**
- T+0: SRE on-call (prise en charge).
- T+10 min: engineer backend/model on-call.
- T+20 min: incident manager si indisponibilite client.

**On NE fait PAS**
- Ne pas executer `docker compose down -v`.
- Ne pas redemarrer toute la stack sans diagnostic minimal.

## 2. Latence p95 degradee

**Declenchement**
- Panel "Vitesse - Latence model p50 p95 p99": p95 > 0.35 s pendant 5 minutes.
- Ou p99 > 0.80 s pendant 5 minutes.

**Actions**
1. Confirmer la charge: regarder "Vie - RPS par service".
2. Verifier saturation machine: `docker stats --no-stream`.
3. Verifier si erreurs en hausse: panel "Vie - Erreurs 5xx par service".
4. Si CPU/memoire saturee, redemarrer `model` en premier puis re-mesurer 5 min.
5. Si latence reste elevee sans saturation, preparer rollback (procedure 4).

**Qui appeler**
- T+0: SRE on-call.
- T+15 min: engineer model on-call.
- T+30 min: incident manager si SLO impacte.

**On NE fait PAS**
- Ne pas deployer un hotfix non teste en production.
- Ne pas modifier les seuils d'alerte pendant l'incident.

## 3. Comportement prediction anormal

**Declenchement**
- Panel "Comportement - Repartition des classes predites": la classe `1` double ou est divisee par 2 vs niveau habituel pendant 15 min.
- Ou panel "Comportement - Proba defaut p50 p95": p95 > 0.90 pendant 15 min.

**Actions**
1. Verifier d'abord la sante technique: panels "up", "RPS", "5xx".
2. Verifier les erreurs upstream backend: `pyrenex_backend_upstream_errors_total` doit rester stable.
3. Si technique saine, classer en suspicion de drift data (incident non bloquant infra).
4. Ouvrir ticket "Data/Model" avec heure de debut, captures dashboard, impact metier observe.
5. Renforcer surveillance (fenetre 1h) et preparer rollback uniquement si metier le demande.

**Qui appeler**
- T+0: SRE on-call.
- T+15 min: data scientist/model owner.
- T+30 min: product owner si decision metier requise.

**On NE fait PAS**
- Ne pas conclure "le modele est faux" sans verite terrain.
- Ne pas re-entrainer en urgence depuis la prod.

## 4. Rollback de release

**Declenchement**
- Incident post-release confirme: KO service > 10 min, ou latence/5xx hors seuil > 15 min apres tentative de remediation.
- Ou gate qualite rouge en CI sur la release candidate.

**Actions**
1. Identifier la derniere version stable (tag precedent `vX.Y.Z`).
2. Re-deployer l'image stable depuis GHCR.
3. Redemarrer uniquement les services impactes (`model`, puis `backend`).
4. Verifier retour vert: `/health`, panel up=1, p95 revenu sous seuil, 5xx proche de 0.
5. Consigner l'incident: heure, cause probable, action, resultat.

**Qui appeler**
- T+0: SRE on-call + release manager.
- T+15 min: engineer responsable du dernier changement.
- T+30 min: incident manager si impact client continue.

**On NE fait PAS**
- Ne pas supprimer les images/tags precedents pendant l'incident.
- Ne pas faire de rollback partiel non documente.

## Boucle de feedback et reentrainement

Rappel du cycle : `POST /feedback` (service `feedback`, table SQLite
`feedbacks.db`) -> cron toutes les 6h (`crontab.txt`) declenche
`scripts/retrain.py` si au moins 200 feedbacks non consommes
(`used_for_training = 0`) -> reentrainement sur donnees d'origine + feedbacks
-> evaluation du candidat et de la prod sur le meme `data/reference_set.csv`
(jeu de reference fige) -> `decide_promotion` (`scripts/promotion.py`) ->
promotion vers `v2.1.0` ou rejet, decision tracee dans `decisions_log.jsonl`.
Rappel de la politique de promotion : planchers `f1_macro` >= 0.55,
`f1_default` >= 0.35, `roc_auc` >= 0.65, `recall_default` >= 0.50 ; metriques
critiques `f1_macro` et `recall_default` (un faux negatif = defaut de credit
non detecte, cout metier direct ; jeu desequilibre donc l'accuracy seule peut
masquer un effondrement sur la classe minoritaire) ; rejet si regression > 0.01
(`TOLERANCE`) sur une metrique critique ; promotion seulement si en plus un
gain >= 0.01 (`MIN_GAIN`) sur au moins une metrique.

## 5. Job de reentrainement en echec ou silencieux

**Declenchement**
- `logs/retrain.log` absent de mise a jour depuis > 6h (le cron n'a pas
  tourne), ou derniere execution en erreur (stack trace, code retour != 0).
- Alerte manuelle : un feedback recent existe mais aucune nouvelle ligne
  n'apparait dans `decisions_log.jsonl` depuis plusieurs cycles de 6h.

**Actions**
1. Verifier que le cron est installe et actif : `crontab -l` sur l'hote de
   deploiement.
2. Lire les dernieres lignes de `logs/retrain.log` pour identifier l'erreur
   (dependances manquantes, chemin de fichier introuvable, erreur SQLite,
   erreur d'entrainement).
3. Verifier l'acces aux fichiers requis : `data/lending_club_train.csv`,
   `data/reference_set.csv`, `data/feedbacks.db`,
   `services/model/models/pyrenex_risk_v2.joblib`/`.json`.
4. Rejouer manuellement en local pour reproduire :
   `python scripts/retrain.py --min-feedback 200`.
5. Si l'erreur vient d'une donnee corrompue (feedback invalide, colonne
   manquante), ne pas corriger les donnees a la main en prod : escalader vers
   le data scientist/model owner.

**Qui appeler**
- T+0: SRE on-call (verification technique du job/cron).
- T+15 min: data scientist/model owner si l'erreur vient du pipeline
  d'entrainement ou des donnees.
- T+30 min: engineer backend si le probleme vient de l'infra (hote, permissions,
  disque plein).

**On NE fait PAS**
- Ne pas relancer le cron en boucle sans lire la log d'erreur.
- Ne pas modifier `data/lending_club_train.csv` ou `data/reference_set.csv`
  pour "faire passer" un run en echec.

## 6. Backlog de feedbacks qui ne se vide pas

**Declenchement**
- Panel Grafana / requete SQLite montrant que le nombre de feedbacks avec
  `used_for_training = 0` augmente sans jamais redescendre malgre les
  executions du cron.
- `GET /feedback/count` renvoie un `new` qui ne diminue jamais apres un
  cycle de retrain reussi.

**Actions**
1. Confirmer que `retrain.py` s'execute bien (voir procedure 5) et se termine
   sans erreur.
2. Verifier si le seuil `--min-feedback` (200 par defaut) n'est simplement
   jamais atteint : comparer au volume reel de feedbacks recus recemment.
3. Si le seuil est atteint mais le backlog ne bouge pas, verifier que
   `mark_used_for_training` est bien appele : cela n'arrive que si la
   promotion a lieu ET que le run se termine sans exception avant cette etape
   (voir `scripts/retrain.py`) — un rejet de promotion (procedure 7) laisse
   normalement les feedbacks marques consommes malgre tout ; verifier la
   logique dans `decisions_log.jsonl` (champ `feedback_count` par run).
4. Verifier l'integrite du join feedback <-> `prod_scored.csv` :
   `scripts/feedback_store.load_labeled_feedback` leve une erreur si des
   `request_id` de feedback n'ont pas de correspondance dans `prod_scored.csv`
   (donnees de scoring manquantes ou tronquees).

**Qui appeler**
- T+0: SRE on-call (verification technique et volume).
- T+15 min: data scientist/model owner si le join feedback/scoring est cassé
  ou si le seuil de declenchement doit etre revu.

**On NE fait PAS**
- Ne pas marquer manuellement des feedbacks comme consommes en base pour
  "vider" le backlog sans comprendre la cause.
- Ne pas baisser `--min-feedback` en prod sans validation (ca change la
  frequence de reentrainement et la taille des lots de feedback integres).

## 7. Rejet de promotion inattendu ou repete

**Declenchement**
- Plusieurs executions consecutives de `retrain.py` aboutissent a
  `promote: false` dans `decisions_log.jsonl`, alors que des feedbacks
  continuent d'etre collectes (le modele en prod ne s'ameliore jamais).

**Actions**
1. Lire la `reason` de la derniere decision dans `decisions_log.jsonl` :
   plancher de qualite non atteint, regression sur une metrique critique, ou
   absence de gain suffisant.
2. Comparer les metriques candidat vs production de plusieurs runs recents
   pour voir si le candidat stagne ou regresse systematiquement.
3. Si regression sur une metrique critique (`f1_macro`, `recall_default`) :
   suspecter un probleme de qualite des feedbacks recents (labels bruites,
   deséquilibre accentue) plutot qu'un probleme de code.
4. Si le candidat est "juste" en dessous du gain minimum (`MIN_GAIN`) de facon
   repetee, c'est un comportement attendu de la politique (pas de promotion
   sans amelioration reelle) : ne pas forcer une promotion sans revue.
5. Documenter le constat dans `decisions.md` / ticket "Data/Model" pour suivi.

**Qui appeler**
- T+0: SRE on-call (constat, pas d'action technique correctrice attendue).
- T+15 min: data scientist/model owner pour analyser la qualite des feedbacks
  et la pertinence des seuils.

**On NE fait PAS**
- Ne pas modifier les seuils (`THRESHOLDS`, `TOLERANCE`, `MIN_GAIN`) dans
  `scripts/promotion.py` en reaction a un rejet, sans revue.
- Ne pas forcer une promotion manuelle en copiant le `.joblib` candidat en
  production sans passer par `decide_promotion`.

## 8. Promotion effectuee mais tag/deploiement incoherent

**Declenchement**
- `decisions_log.jsonl` indique `promote: true` et
  `services/model/models/pyrenex_risk_v2_1.joblib`/`.json` existent, mais le
  modele servi en prod (`/health`, metadonnees exposees par l'API) reste en
  `v2.0.x`, ou le tag git `v2.1.0` correspondant est absent/non pousse.

**Actions**
1. Verifier la presence du tag : `git tag --list` (doit contenir `v2.1.0`
   apres une promotion). La creation/push du tag est une etape manuelle/CI,
   non automatisee par `retrain.py`.
2. Verifier que le pipeline CI/CD a bien recupere le tag et redeploye le
   service `model` avec le nouveau fichier `.joblib`.
3. Si le tag est manquant, le creer et le pousser suivant la procedure prevue
   (cf. README_M6.md), puis surveiller le redeploiement.
4. Une fois deploye, verifier `/health` et le panel Grafana version modele en
   prod, puis suivre les metriques de comportement (procedure 3) pendant les
   premieres heures.

**Qui appeler**
- T+0: SRE on-call + release manager.
- T+15 min: data scientist/model owner pour confirmer la version attendue.

**On NE fait PAS**
- Ne pas remplacer le modele en prod a la main sans passer par le tag/CI.
- Ne pas supprimer le fichier `pyrenex_risk_candidate.joblib` avant d'avoir
  confirme la promotion (utile pour rejouer/diagnostiquer).
