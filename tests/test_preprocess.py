"""Tests pytest pour scripts/preprocess.py (pipeline de préparation des features)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from preprocess import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessor,
    load_dataset,
)


def _make_raw_csv(path: Path, *, drop_column: str | None = None, target_values=None) -> None:
    row = {
        "loan_amnt": 10000,
        "int_rate": 12.5,
        "installment": 300.0,
        "annual_inc": 45000,
        "dti": 18.0,
        "delinq_2yrs": 0,
        "fico_range_low": 700,
        "revol_util": 40.0,
        "term": "36 months",
        "grade": "B",
        "home_ownership": "RENT",
        "verification_status": "Verified",
        "purpose": "debt_consolidation",
        "emp_length": "2 years",
        "loan_status": "Fully Paid",
        "extra_column_not_used": "ignored",
    }
    rows = []
    values = target_values or ["Fully Paid", "Charged Off"]
    for value in values:
        r = dict(row)
        r["loan_status"] = value
        rows.append(r)
    df = pd.DataFrame(rows)
    if drop_column:
        df = df.drop(columns=[drop_column])
    df.to_csv(path, index=False)


def test_load_dataset_returns_features_and_mapped_target(tmp_path):
    csv_path = tmp_path / "raw.csv"
    _make_raw_csv(csv_path)

    X, y = load_dataset(csv_path)

    assert list(X.columns) == NUMERIC_FEATURES + CATEGORICAL_FEATURES
    assert "extra_column_not_used" not in X.columns
    assert list(y) == [0, 1]


def test_load_dataset_raises_on_missing_columns(tmp_path):
    csv_path = tmp_path / "raw.csv"
    _make_raw_csv(csv_path, drop_column="fico_range_low")

    with pytest.raises(KeyError, match="fico_range_low"):
        load_dataset(csv_path)


def test_load_dataset_raises_on_unmapped_target(tmp_path):
    csv_path = tmp_path / "raw.csv"
    _make_raw_csv(csv_path, target_values=["Fully Paid", "In Grace Period"])

    with pytest.raises(ValueError, match="In Grace Period"):
        load_dataset(csv_path)


def test_build_preprocessor_transforms_without_nan_and_handles_unknown_category(tmp_path):
    csv_path = tmp_path / "raw.csv"
    _make_raw_csv(csv_path)
    X, _ = load_dataset(csv_path)
    # Introduit un NaN numérique et une catégorie jamais vue à l'entraînement.
    X.loc[0, "dti"] = np.nan
    X_unseen = X.copy()
    X_unseen.loc[0, "grade"] = "ZZZ-inconnu"

    preprocessor = build_preprocessor()
    transformed = preprocessor.fit_transform(X, pd.Series([0, 1]))
    transformed_unseen = preprocessor.transform(X_unseen)

    assert not np.isnan(transformed).any()
    assert transformed.shape[0] == len(X)
    assert transformed_unseen.shape == transformed.shape
