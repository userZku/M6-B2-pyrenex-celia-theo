"""Retrain a candidate model from labelled production feedbacks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).parent))
from preprocess import (  # noqa: E402
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessor,
    load_dataset,
)
from promotion import decide_promotion  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "services" / "model" / "models"
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

FEEDBACKS_PATH = DATA / "feedbacks_simules.csv"
PROD_SCORED_PATH = DATA / "prod_scored.csv"
TRAIN_PATH = DATA / "lending_club_train.csv"
REFERENCE_PATH = DATA / "reference_set.csv"
PRODUCTION_PATH = MODELS / "pyrenex_risk_v2.joblib"
PRODUCTION_META_PATH = MODELS / "pyrenex_risk_v2.json"
CANDIDATE_PATH = MODELS / "pyrenex_risk_candidate.joblib"
PROMOTED_PATH = MODELS / "pyrenex_risk_v2_1.joblib"
PROMOTED_META_PATH = MODELS / "pyrenex_risk_v2_1.json"
DECISION_LOG = ROOT / "decisions_log.jsonl"

RF_PARAMS = dict(
    n_estimators=200,
    max_depth=10,
    min_samples_leaf=10,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)


def load_feedbacks() -> pd.DataFrame:
    feedbacks = pd.read_csv(FEEDBACKS_PATH)
    required = {"request_id", "true_label"}
    missing = required - set(feedbacks.columns)
    if missing:
        raise ValueError(f"Feedback columns missing: {sorted(missing)}")
    if "used_for_training" not in feedbacks.columns:
        feedbacks["used_for_training"] = 0
    feedbacks["used_for_training"] = feedbacks["used_for_training"].fillna(0).astype(int)
    if not feedbacks["true_label"].isin([0, 1]).all():
        raise ValueError("true_label must contain only 0 or 1")
    return feedbacks


def build_training_data(feedbacks: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Combine the original train set with corrected production examples."""
    X_train, y_train = load_dataset(TRAIN_PATH)
    production = pd.read_csv(PROD_SCORED_PATH)
    unused = feedbacks[feedbacks["used_for_training"] == 0]
    corrected = production.merge(unused[["request_id", "true_label"]], on="request_id")
    if not corrected.empty:
        X_feedback = corrected[FEATURES].copy()
        y_feedback = corrected["true_label"].astype(int)
        X_train = pd.concat([X_train, X_feedback], ignore_index=True)
        y_train = pd.concat([y_train, y_feedback], ignore_index=True)
    return X_train, y_train


def train_candidate(X_train: pd.DataFrame, y_train: pd.Series):
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", RandomForestClassifier(**RF_PARAMS)),
        ]
    )
    pipeline.fit(X_train, y_train)
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, CANDIDATE_PATH)
    return pipeline


def evaluate_model(model) -> dict[str, float]:
    reference = pd.read_csv(REFERENCE_PATH)
    X_reference = reference[FEATURES]
    y_reference = reference[TARGET_COLUMN].map({"Fully Paid": 0, "Charged Off": 1})
    predictions = model.predict(X_reference)
    probabilities = model.predict_proba(X_reference)[:, 1]
    return {
        "f1_macro": float(f1_score(y_reference, predictions, average="macro")),
        "f1_default": float(f1_score(y_reference, predictions, pos_label=1)),
        "roc_auc": float(roc_auc_score(y_reference, probabilities)),
        "recall_default": float(recall_score(y_reference, predictions, pos_label=1)),
    }


def validate_candidate(model) -> None:
    reference = pd.read_csv(REFERENCE_PATH)
    probabilities = model.predict_proba(reference[FEATURES])[:, 1]
    if not ((probabilities >= 0).all() and (probabilities <= 1).all()):
        raise ValueError("Candidate probabilities are outside [0, 1]")


def dataset_hash(X_train: pd.DataFrame, y_train: pd.Series) -> str:
    payload = pd.concat([X_train, y_train.rename(TARGET_COLUMN)], axis=1)
    return hashlib.sha256(payload.to_csv(index=False).encode("utf-8")).hexdigest()


def write_decision(decision, candidate_metrics, production_metrics, feedback_count):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feedback_count": feedback_count,
        "candidate_metrics": candidate_metrics,
        "production_metrics": production_metrics,
        "promote": decision.promote,
        "reason": decision.reason,
    }
    with DECISION_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


def mark_feedbacks_consumed(feedbacks: pd.DataFrame) -> None:
    feedbacks = feedbacks.copy()
    feedbacks.loc[feedbacks["used_for_training"] == 0, "used_for_training"] = 1
    temporary_path = FEEDBACKS_PATH.with_suffix(".tmp.csv")
    feedbacks.to_csv(temporary_path, index=False)
    temporary_path.replace(FEEDBACKS_PATH)


def write_promoted_metadata(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    candidate_metrics: dict[str, float],
) -> None:
    metadata = json.loads(PRODUCTION_META_PATH.read_text(encoding="utf-8"))
    metadata["model_version"] = "v2.1.0"
    metadata["created_at"] = datetime.now(timezone.utc).isoformat()
    metadata["dataset_sha256"] = dataset_hash(X_train, y_train)
    metadata["metrics_reference"] = candidate_metrics
    PROMOTED_META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-feedback", type=int, default=200)
    args = parser.parse_args()

    feedbacks = load_feedbacks()
    unused_count = int((feedbacks["used_for_training"] == 0).sum())
    if unused_count < args.min_feedback:
        print(f"Skip: {unused_count} new feedback(s), threshold is {args.min_feedback}")
        return 0

    X_train, y_train = build_training_data(feedbacks)
    candidate = train_candidate(X_train, y_train)
    validate_candidate(candidate)
    production = joblib.load(PRODUCTION_PATH)
    candidate_metrics = evaluate_model(candidate)
    production_metrics = evaluate_model(production)
    decision = decide_promotion(candidate_metrics, production_metrics)
    write_decision(decision, candidate_metrics, production_metrics, unused_count)

    if not decision.promote:
        print(json.dumps({"promote": False, "reason": decision.reason}))
        return 0

    joblib.dump(candidate, PROMOTED_PATH)
    write_promoted_metadata(X_train, y_train, candidate_metrics)
    mark_feedbacks_consumed(feedbacks)
    print(json.dumps({"promote": True, "reason": decision.reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())