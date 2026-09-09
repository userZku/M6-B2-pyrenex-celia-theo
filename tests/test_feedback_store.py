"""Tests de la jointure feedbacks ⋈ prod_scored (brique B).

Mini-cours : `02_Stockage_feedback_versionne_essentiel.md`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from feedback_store import (
    inject_mock_feedback,
    load_labeled_feedback,
    mark_used_for_training,
)


@pytest.fixture
def feedback_db(tmp_path):
    db_path = tmp_path / "fb.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE feedbacks (
                request_id TEXT PRIMARY KEY,
                true_label INTEGER NOT NULL,
                comments   TEXT,
                created_at TEXT NOT NULL,
                used_for_training INTEGER NOT NULL DEFAULT 0
            )"""
        )
    return db_path


@pytest.fixture
def prod_scored(tmp_path):
    path = tmp_path / "prod_scored.csv"
    pd.DataFrame(
        {
            "request_id": ["REQ-00000", "REQ-00001", "REQ-00002"],
            "loan_amnt": [2900, 11900, 7600],
            "grade": ["B", "F", "C"],
            "loan_status": ["Fully Paid", "Charged Off", "Fully Paid"],
        }
    ).to_csv(path, index=False)
    return path


def _insert(db_path: Path, request_id: str, true_label: int, used_for_training: int = 0) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO feedbacks (request_id, true_label, comments, created_at, "
            "used_for_training) VALUES (?, ?, NULL, '2026-01-01T00:00:00Z', ?)",
            (request_id, true_label, used_for_training),
        )


def test_load_labeled_feedback_joins_features_and_label(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-00000", 0)
    _insert(feedback_db, "REQ-00001", 1)

    joined = load_labeled_feedback(feedback_db, prod_scored)

    assert set(joined["request_id"]) == {"REQ-00000", "REQ-00001"}
    assert set(joined.columns) >= {"request_id", "true_label", "loan_amnt", "grade"}
    row = joined.set_index("request_id").loc["REQ-00001"]
    assert row["true_label"] == 1
    assert row["grade"] == "F"


def test_load_labeled_feedback_only_new_excludes_consumed(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-00000", 0, used_for_training=1)
    _insert(feedback_db, "REQ-00001", 1, used_for_training=0)

    joined = load_labeled_feedback(feedback_db, prod_scored, only_new=True)

    assert list(joined["request_id"]) == ["REQ-00001"]


def test_load_labeled_feedback_only_new_false_includes_everything(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-00000", 0, used_for_training=1)
    _insert(feedback_db, "REQ-00001", 1, used_for_training=0)

    joined = load_labeled_feedback(feedback_db, prod_scored, only_new=False)

    assert set(joined["request_id"]) == {"REQ-00000", "REQ-00001"}


def test_load_labeled_feedback_empty_when_no_feedback(feedback_db, prod_scored):
    joined = load_labeled_feedback(feedback_db, prod_scored)

    assert joined.empty


def test_load_labeled_feedback_raises_on_broken_join(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-INCONNU", 1)

    with pytest.raises(ValueError, match="jointure cassée"):
        load_labeled_feedback(feedback_db, prod_scored)


def test_mark_used_for_training_updates_flag(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-00000", 0)
    _insert(feedback_db, "REQ-00001", 1)

    mark_used_for_training(feedback_db, ["REQ-00000"])

    joined = load_labeled_feedback(feedback_db, prod_scored, only_new=True)
    assert list(joined["request_id"]) == ["REQ-00001"]


def test_mark_used_for_training_noop_on_empty_list(feedback_db, prod_scored):
    _insert(feedback_db, "REQ-00000", 0)

    mark_used_for_training(feedback_db, [])

    joined = load_labeled_feedback(feedback_db, prod_scored, only_new=True)
    assert list(joined["request_id"]) == ["REQ-00000"]


def test_inject_mock_feedback_first_batch_starts_at_zero(feedback_db, prod_scored):
    inserted = inject_mock_feedback(feedback_db, prod_scored, 2)

    assert inserted == ["REQ-00000", "REQ-00001"]
    joined = load_labeled_feedback(feedback_db, prod_scored, only_new=False)
    row = joined.set_index("request_id").loc["REQ-00001"]
    assert row["true_label"] == 1  # Charged Off


def test_inject_mock_feedback_resumes_after_last_injected(feedback_db, prod_scored):
    inject_mock_feedback(feedback_db, prod_scored, 2)

    inserted = inject_mock_feedback(feedback_db, prod_scored, 1)

    assert inserted == ["REQ-00002"]


def test_inject_mock_feedback_raises_when_exceeding_remaining_rows(feedback_db, prod_scored):
    inject_mock_feedback(feedback_db, prod_scored, 2)

    with pytest.raises(ValueError, match="ne contient que"):
        inject_mock_feedback(feedback_db, prod_scored, 5)


def test_inject_mock_feedback_raises_on_non_positive_count(feedback_db, prod_scored):
    with pytest.raises(ValueError, match="positif"):
        inject_mock_feedback(feedback_db, prod_scored, 0)
