"""Tests pytest complémentaires pour scripts/retrain.py (couverture au-delà de
`load_new_feedbacks`, déjà testée dans test_boucle.py).
"""

from __future__ import annotations

import json

import joblib
import pandas as pd
import pytest

import retrain


@pytest.fixture
def small_train_csv(tmp_path):
    path = tmp_path / "train.csv"
    pd.DataFrame(
        {
            "loan_amnt": [5000, 8000, 12000, 6000],
            "term": ["36 months", "60 months", "36 months", "36 months"],
            "int_rate": [10.0, 12.0, 9.0, 14.0],
            "installment": [200.0, 250.0, 300.0, 210.0],
            "grade": ["B", "C", "A", "B"],
            "emp_length": ["2 years", "5 years", "1 year", "3 years"],
            "home_ownership": ["RENT", "MORTGAGE", "OWN", "RENT"],
            "annual_inc": [40000, 55000, 60000, 42000],
            "verification_status": ["Verified", "Not Verified", "Verified", "Verified"],
            "purpose": ["debt_consolidation", "credit_card", "car", "debt_consolidation"],
            "dti": [15.0, 20.0, 10.0, 18.0],
            "delinq_2yrs": [0, 1, 0, 0],
            "fico_range_low": [700, 690, 720, 705],
            "revol_util": [40.0, 55.0, 30.0, 45.0],
            "loan_status": ["Fully Paid", "Charged Off", "Fully Paid", "Fully Paid"],
        }
    ).to_csv(path, index=False)
    return path


def test_build_training_data_concatenates_feedback(monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "TRAIN_PATH", small_train_csv)
    feedback = pd.DataFrame(
        {
            "loan_amnt": [7000],
            "term": ["36 months"],
            "int_rate": [11.0],
            "installment": [230.0],
            "grade": ["B"],
            "emp_length": ["4 years"],
            "home_ownership": ["RENT"],
            "annual_inc": [48000],
            "verification_status": ["Verified"],
            "purpose": ["debt_consolidation"],
            "dti": [16.0],
            "delinq_2yrs": [0],
            "fico_range_low": [710],
            "revol_util": [42.0],
            "true_label": [1],
        }
    )

    X_train, y_train = retrain.build_training_data(feedback)

    assert len(X_train) == 5
    assert len(y_train) == 5
    assert y_train.iloc[-1] == 1


def test_build_training_data_empty_feedback_returns_original(monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "TRAIN_PATH", small_train_csv)

    X_train, y_train = retrain.build_training_data(pd.DataFrame(columns=retrain.FEATURES + ["true_label"]))

    assert len(X_train) == 4
    assert len(y_train) == 4


def test_train_candidate_fits_and_persists_pipeline(tmp_path, monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "MODELS", tmp_path)
    monkeypatch.setattr(retrain, "CANDIDATE_PATH", tmp_path / "candidate.joblib")
    X_train, y_train = retrain.load_dataset(small_train_csv)

    pipeline = retrain.train_candidate(X_train, y_train)

    assert (tmp_path / "candidate.joblib").exists()
    predictions = pipeline.predict(X_train)
    assert len(predictions) == len(X_train)


def test_evaluate_model_returns_the_four_target_metrics(tmp_path, monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "REFERENCE_PATH", small_train_csv)
    monkeypatch.setattr(retrain, "MODELS", tmp_path)
    monkeypatch.setattr(retrain, "CANDIDATE_PATH", tmp_path / "candidate.joblib")
    X_train, y_train = retrain.load_dataset(small_train_csv)
    model = retrain.train_candidate(X_train, y_train)

    metrics = retrain.evaluate_model(model)

    assert set(metrics) == {"f1_macro", "f1_default", "roc_auc", "recall_default"}
    assert all(0.0 <= value <= 1.0 for value in metrics.values())


def test_validate_candidate_accepts_valid_probabilities(monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "REFERENCE_PATH", small_train_csv)
    X_train, y_train = retrain.load_dataset(small_train_csv)
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline(
        steps=[
            ("preprocessor", retrain.build_preprocessor()),
            ("classifier", RandomForestClassifier(**retrain.RF_PARAMS)),
        ]
    )
    pipeline.fit(X_train, y_train)

    retrain.validate_candidate(pipeline)  # does not raise


def test_validate_candidate_rejects_out_of_range_probabilities(monkeypatch, small_train_csv):
    monkeypatch.setattr(retrain, "REFERENCE_PATH", small_train_csv)

    class FakeModel:
        def predict_proba(self, X):
            import numpy as np

            return np.tile([1.5, -0.5], (len(X), 1))

    with pytest.raises(ValueError, match="outside"):
        retrain.validate_candidate(FakeModel())


def test_dataset_hash_is_deterministic_and_sensitive_to_content(small_train_csv):
    X_train, y_train = retrain.load_dataset(small_train_csv)

    hash_a = retrain.dataset_hash(X_train, y_train)
    hash_b = retrain.dataset_hash(X_train, y_train)
    hash_c = retrain.dataset_hash(X_train.iloc[:-1], y_train.iloc[:-1])

    assert hash_a == hash_b
    assert hash_a != hash_c


def test_write_decision_appends_jsonl_record(tmp_path, monkeypatch):
    monkeypatch.setattr(retrain, "DECISION_LOG", tmp_path / "decisions_log.jsonl")
    decision = retrain.decide_promotion(
        {"f1_macro": 0.62, "f1_default": 0.43, "roc_auc": 0.73, "recall_default": 0.67},
        {"f1_macro": 0.60, "f1_default": 0.42, "roc_auc": 0.72, "recall_default": 0.66},
    )

    retrain.write_decision(decision, {"f1_macro": 0.62}, {"f1_macro": 0.60}, feedback_count=5)

    lines = (tmp_path / "decisions_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["promote"] is True
    assert record["feedback_count"] == 5


def test_write_promoted_metadata_bumps_version_and_hash(tmp_path, monkeypatch, small_train_csv):
    production_meta = tmp_path / "production.json"
    promoted_meta = tmp_path / "promoted.json"
    production_meta.write_text(
        json.dumps({"model_version": "v2.0.0", "feature_columns_numeric": []}), encoding="utf-8"
    )
    monkeypatch.setattr(retrain, "PRODUCTION_META_PATH", production_meta)
    monkeypatch.setattr(retrain, "PROMOTED_META_PATH", promoted_meta)
    X_train, y_train = retrain.load_dataset(small_train_csv)

    retrain.write_promoted_metadata(X_train, y_train, {"f1_macro": 0.62})

    written = json.loads(promoted_meta.read_text(encoding="utf-8"))
    assert written["model_version"] == "v2.1.0"
    assert written["metrics_reference"] == {"f1_macro": 0.62}
    assert "dataset_sha256" in written
