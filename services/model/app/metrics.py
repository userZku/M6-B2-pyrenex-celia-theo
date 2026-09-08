"""Métriques métier Prometheus — service model (fourni — votre exemple de référence).

En plus des métriques HTTP standard exposées par
``prometheus-fastapi-instrumentator`` (latence, RPS, codes retour), on
expose des métriques **métier** qui répondent à la 3ᵉ question de Sophie
Léger : *« le modèle prédit-il toujours bien ? »*

- ``pyrenex_predictions_total`` : compteur des prédictions, labellé par
  classe prédite (0 = remboursé, 1 = défaut). La dérive de la répartition
  0/1 dans le temps est un signal d'alerte (data drift / concept drift).
- ``pyrenex_prediction_proba`` : histogramme des probabilités de défaut
  renvoyées. Un modèle sain produit une distribution étalée ; un pic à
  0.5 ou aux bornes signale un problème.
- ``pyrenex_prediction_psi`` : dérive de la distribution des probabilités
    prédites par rapport à la référence gelée du modèle.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from threading import Lock

from prometheus_client import Counter, Gauge, Histogram

BASELINE_PATH = Path(__file__).parent.parent / "models" / "pyrenex_proba_psi_baseline.json"
PSI_EPSILON = 1e-6

_baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
PSI_BINS = tuple(_baseline["bins"])
PSI_REFERENCE = tuple(float(value) for value in _baseline["proportions"])
if len(PSI_BINS) != len(PSI_REFERENCE) or not abs(sum(PSI_REFERENCE) - 1.0) < 1e-9:
    raise ValueError(f"Invalid PSI baseline in {BASELINE_PATH}")

_psi_counts = [0] * len(PSI_BINS)
_psi_lock = Lock()

PREDICTIONS_TOTAL = Counter(
    "pyrenex_predictions_total",
    "Nombre de prédictions servies, par classe prédite.",
    labelnames=("predicted_class",),
)

PREDICTION_PROBA = Histogram(
    "pyrenex_prediction_proba",
    "Distribution des probabilités de défaut prédites.",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
PREDICTION_PSI = Gauge(
    "pyrenex_prediction_psi",
    "Population Stability Index des probabilites predites vs la reference.",
)
PREDICTION_PSI_BIN = Gauge(
    "pyrenex_prediction_psi_bin",
    "Contribution au PSI par tranche de probabilite.",
    labelnames=("bin",),
)
PREDICTION_PSI_OBSERVATIONS = Gauge(
    "pyrenex_prediction_psi_observations",
    "Nombre de probabilites predites utilisees pour calculer le PSI.",
)

PREDICTION_PSI.set(0)
PREDICTION_PSI_OBSERVATIONS.set(0)


def _update_psi(proba_default: float) -> None:
    bin_index = min(int(proba_default * len(PSI_BINS)), len(PSI_BINS) - 1)
    with _psi_lock:
        _psi_counts[bin_index] += 1
        total = sum(_psi_counts)
        actual = [count / total for count in _psi_counts]
        contributions = [
                        (observed - expected)
                        * math.log(
                                (observed + PSI_EPSILON) / (expected + PSI_EPSILON)
                        )
                        for observed, expected in zip(actual, PSI_REFERENCE)
        ]

    PREDICTION_PSI.set(sum(contributions))
    PREDICTION_PSI_OBSERVATIONS.set(total)
    for bin_name, contribution in zip(PSI_BINS, contributions):
                PREDICTION_PSI_BIN.labels(bin=bin_name).set(contribution)


def observe_prediction(predicted_class: int, proba_default: float) -> None:
    """Enregistre une prédiction dans les métriques métier.

    Args:
        predicted_class: Classe prédite (0 = remboursé, 1 = défaut).
        proba_default: Probabilité de défaut renvoyée par le modèle.
    """
    PREDICTIONS_TOTAL.labels(predicted_class=str(predicted_class)).inc()
    PREDICTION_PROBA.observe(proba_default)
    _update_psi(proba_default)
