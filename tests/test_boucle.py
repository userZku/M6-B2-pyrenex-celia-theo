"""Tests de la boucle — verts sur le squelette, plus exigeants ensuite.

Lancez `pytest` dès le clone : tout doit passer. Les tests marqués
"débloqué par TODO n" sautent tant que le TODO n'est pas complété, puis
deviennent de vrais garde-fous. Ajoutez ensuite VOS tests : la politique
de promotion que vous défendrez doit être couverte par des cas à vous.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "feedback"))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(monkeypatch):
    """TestClient du service feedback, sur une base SQLite temporaire."""
    tmpdb = Path(tempfile.mkdtemp()) / "fb.db"
    monkeypatch.setenv("FEEDBACK_DB", str(tmpdb))
    import importlib

    from fastapi.testclient import TestClient

    import app.main as m

    importlib.reload(m)
    with TestClient(m.app) as c:
        yield c


def test_health(client):
    """Le service démarre et répond — sinon relisez le README (démarrage)."""
    r = client.get("/health")
    assert r.status_code == 200


def test_unknown_request_id_rejected(client):
    """Un feedback sur un dossier jamais scoré est refusé (404)."""
    r = client.post("/feedback", json={"request_id": "REQ-INEXISTANT", "true_label": 1})
    assert r.status_code == 404


def test_invalid_label_rejected(client):
    """Un label hors {0, 1} est refusé par la validation Pydantic (422)."""
    r = client.post("/feedback", json={"request_id": "REQ-00000", "true_label": 3})
    assert r.status_code == 422


def test_post_valid_feedback_counted(client):
    """Un feedback valide est stocké et compté."""
    r = client.post("/feedback", json={"request_id": "REQ-00000", "true_label": 0})
    assert r.status_code == 201
    assert client.get("/feedback/count").json()["count"] == 1


def test_same_feedback_twice_is_idempotent(client):
    """Débloqué par TODO 3 (main.py) : le rejeu réseau ne crée pas de doublon."""
    payload = {"request_id": "REQ-00001", "true_label": 1}
    client.post("/feedback", json=payload)
    try:
        r = client.post("/feedback", json=payload)
    except sqlite3.IntegrityError:
        pytest.skip("TODO 3 de main.py à compléter (gestion du rejeu)")
    assert r.status_code == 201
    assert client.get("/feedback/count").json()["count"] == 1


def test_contradictory_feedback_returns_409(client):
    """Débloqué par TODO 3 (main.py) : deux vérités opposées → arbitrage humain."""
    client.post("/feedback", json={"request_id": "REQ-00002", "true_label": 0})
    try:
        r = client.post("/feedback", json={"request_id": "REQ-00002", "true_label": 1})
    except sqlite3.IntegrityError:
        pytest.skip("TODO 3 de main.py à compléter (conflit de labels)")
    assert r.status_code == 409


def test_count_exposes_new(client):
    """Débloqué par TODO 2 (main.py) : le trigger lit les feedbacks NON consommés."""
    client.post("/feedback", json={"request_id": "REQ-00003", "true_label": 0})
    body = client.get("/feedback/count").json()
    if "new" not in body:
        pytest.skip("TODO 2 de main.py à compléter (clé `new`)")
    assert body["new"] <= body["count"]


def test_mock_feedback_injects_incrementally(client):
    """`/mock-feedback` simule le cron : incrémental, reprend après le dernier injecté."""
    first = client.get("/mock-feedback", params={"feedNumber": 2})
    assert first.status_code == 200
    assert first.json()["inserted"] == 2
    first_ids = first.json()["request_ids"]

    second = client.get("/mock-feedback", params={"feedNumber": 3})
    assert second.status_code == 200
    second_ids = second.json()["request_ids"]

    assert set(first_ids).isdisjoint(second_ids)
    assert client.get("/feedback/count").json()["count"] == 5


def test_mock_feedback_rejects_non_positive_feed_number(client):
    r = client.get("/mock-feedback", params={"feedNumber": 0})
    assert r.status_code == 422


def test_mock_feedback_rejects_when_exceeding_available_rows(client):
    r = client.get("/mock-feedback", params={"feedNumber": 10_000})
    assert r.status_code == 400


def test_promotion_refused_on_critical_regression():
    """Débloqué par TODO 4 (promotion) : une régression critique bloque la promo.

    Copiez d'abord `scripts/promotion_TEMPLATE.py` → `scripts/promotion.py`.
    """
    try:
        from scripts.promotion import decide_promotion
    except ImportError:
        pytest.skip("scripts/promotion.py à créer depuis promotion_TEMPLATE.py")
    prod = {"f1_macro": 0.61, "recall_default": 0.64}
    cand = {"f1_macro": 0.63, "recall_default": 0.20}
    try:
        decision = decide_promotion(cand, prod)
    except NotImplementedError:
        pytest.skip("TODO 4 de promotion.py à compléter")
    assert decision.promote is False
    assert decision.reason


def test_promotion_accepts_candidate_with_meaningful_gain():
    from scripts.promotion import decide_promotion

    production = {
        "f1_macro": 0.60,
        "f1_default": 0.42,
        "roc_auc": 0.72,
        "recall_default": 0.66,
    }
    candidate = {
        "f1_macro": 0.62,
        "f1_default": 0.43,
        "roc_auc": 0.73,
        "recall_default": 0.67,
    }

    decision = decide_promotion(candidate, production)

    assert decision.promote is True
    assert "f1_macro" in decision.reason


def test_promotion_rejects_candidate_without_meaningful_gain():
    from scripts.promotion import decide_promotion

    production = {
        "f1_macro": 0.60,
        "f1_default": 0.42,
        "roc_auc": 0.72,
        "recall_default": 0.66,
    }
    candidate = {
        "f1_macro": 0.605,
        "f1_default": 0.425,
        "roc_auc": 0.725,
        "recall_default": 0.665,
    }

    decision = decide_promotion(candidate, production)

    assert decision.promote is False
    assert "gain" in decision.reason


def test_promotion_rejects_candidate_below_quality_floor():
    from scripts.promotion import decide_promotion

    production = {
        "f1_macro": 0.60,
        "f1_default": 0.42,
        "roc_auc": 0.72,
        "recall_default": 0.66,
    }
    candidate = {
        "f1_macro": 0.54,
        "f1_default": 0.50,
        "roc_auc": 0.80,
        "recall_default": 0.70,
    }

    decision = decide_promotion(candidate, production)

    assert decision.promote is False
    assert "plancher" in decision.reason


def test_retrain_reads_unconsumed_feedbacks_from_sqlite(tmp_path, monkeypatch):
    """The retrain trigger uses SQLite, not the legacy feedback CSV."""
    db_path = tmp_path / "feedbacks.db"
    prod_path = tmp_path / "prod_scored.csv"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE feedbacks ("
            "request_id TEXT PRIMARY KEY, true_label INTEGER NOT NULL, "
            "comments TEXT, created_at TEXT NOT NULL, "
            "used_for_training INTEGER NOT NULL DEFAULT 0)"
        )
        con.executemany(
            "INSERT INTO feedbacks VALUES (?, ?, NULL, '2026-01-01', ?)",
            [("REQ-00000", 0, 0), ("REQ-00001", 1, 1)],
        )
    import pandas as pd

    pd.DataFrame(
        {
            "request_id": ["REQ-00000", "REQ-00001"],
            "loan_amnt": [2900, 11900],
            "true_feature": [1, 2],
        }
    ).to_csv(prod_path, index=False)

    import scripts.retrain as retrain

    monkeypatch.setattr(retrain, "FEEDBACK_DB", db_path)
    monkeypatch.setattr(retrain, "PROD_SCORED_PATH", prod_path)

    feedbacks = retrain.load_new_feedbacks()

    assert list(feedbacks["request_id"]) == ["REQ-00000"]
    assert feedbacks.iloc[0]["true_label"] == 0
