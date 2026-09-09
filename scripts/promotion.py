"""Decision policy for promoting a retrained Pyrenex model."""

from __future__ import annotations

from dataclasses import dataclass

# These floors are inherited from the M5-B2 evaluation policy.
THRESHOLDS: dict[str, float] = {
    "f1_macro": 0.55,
    "f1_default": 0.35,
    "roc_auc": 0.65,
    "recall_default": 0.50,
}

# A missed default has a direct credit risk cost. F1 macro is also critical
# because accuracy can hide a collapse on the minority default class.
CRITICAL_METRICS: tuple[str, ...] = ("f1_macro", "recall_default")

TOLERANCE = 0.01
MIN_GAIN = 0.01


@dataclass(frozen=True)
class PromotionDecision:
    """Result of evaluating a candidate against production metrics."""

    promote: bool
    reason: str


def _missing_metrics(metrics: dict[str, float]) -> list[str]:
    return [name for name in THRESHOLDS if name not in metrics]


def decide_promotion(
    candidate: dict[str, float],
    production: dict[str, float],
) -> PromotionDecision:
    """Apply the promotion policy to metrics measured on the same reference set.

    The candidate must pass every absolute floor, must not regress on a
    critical metric by more than ``TOLERANCE``, and must improve at least one
    tracked metric by ``MIN_GAIN``.
    """
    missing_candidate = _missing_metrics(candidate)
    missing_production = _missing_metrics(production)
    if missing_candidate or missing_production:
        missing = sorted(set(missing_candidate + missing_production))
        return PromotionDecision(
            False,
            "Métriques manquantes pour comparer les modèles: "
            + ", ".join(missing),
        )

    floor_violations = [
        f"{metric}={candidate[metric]:.4f} sous le plancher {floor:.2f}"
        for metric, floor in THRESHOLDS.items()
        if candidate[metric] < floor
    ]
    if floor_violations:
        return PromotionDecision(
            False,
            "Plancher de qualité non respecté: " + "; ".join(floor_violations),
        )

    critical_regressions = []
    for metric in CRITICAL_METRICS:
        delta = candidate[metric] - production[metric]
        if delta < -TOLERANCE:
            critical_regressions.append(
                f"{metric} recule de {abs(delta):.4f} "
                f"(tolérance {TOLERANCE:.2f})"
            )
    if critical_regressions:
        return PromotionDecision(
            False,
            "Régression critique: " + "; ".join(critical_regressions),
        )

    gains = {
        metric: candidate[metric] - production[metric]
        for metric in THRESHOLDS
    }
    best_metric, best_gain = max(gains.items(), key=lambda item: item[1])
    if best_gain < MIN_GAIN:
        return PromotionDecision(
            False,
            f"Aucun gain d'au moins {MIN_GAIN:.2f}; "
            f"meilleur gain: {best_metric} ({best_gain:+.4f})",
        )

    return PromotionDecision(
        True,
        f"Promotion acceptée: {best_metric} progresse de {best_gain:+.4f}; "
        "planchers respectés et métriques critiques protégées.",
    )