"""Tests pytest pour scripts/build_reference_set.py (échantillonnage stratifié)."""

from __future__ import annotations

import pandas as pd
import pytest

import build_reference_set as brs


def _make_holdout(path, n_paid: int = 80, n_charged_off: int = 20) -> None:
    rows = [{"loan_amnt": 1000 + i, "loan_status": "Fully Paid"} for i in range(n_paid)]
    rows += [
        {"loan_amnt": 1000 + n_paid + i, "loan_status": "Charged Off"} for i in range(n_charged_off)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def test_main_raises_when_holdout_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(brs, "HOLDOUT", tmp_path / "missing_holdout.csv")
    monkeypatch.setattr(brs, "REFERENCE_SET", tmp_path / "reference_set.csv")

    with pytest.raises(SystemExit, match="absent"):
        brs.main()


def test_main_writes_stratified_sample_preserving_ratio(tmp_path, monkeypatch):
    holdout_path = tmp_path / "holdout.csv"
    reference_path = tmp_path / "reference_set.csv"
    _make_holdout(holdout_path, n_paid=80, n_charged_off=20)

    monkeypatch.setattr(brs, "HOLDOUT", holdout_path)
    monkeypatch.setattr(brs, "REFERENCE_SET", reference_path)
    monkeypatch.setattr(brs, "N_SAMPLE", 50)

    brs.main()

    assert reference_path.exists()
    sample = pd.read_csv(reference_path)
    ratio = sample["loan_status"].value_counts(normalize=True)
    # Ratio du holdout (80/20) préservé à quelques points près malgré l'arrondi par groupe.
    assert ratio["Fully Paid"] == pytest.approx(0.8, abs=0.1)
    assert ratio["Charged Off"] == pytest.approx(0.2, abs=0.1)
    assert 40 <= len(sample) <= 50


def test_main_is_reproducible_across_runs(tmp_path, monkeypatch):
    holdout_path = tmp_path / "holdout.csv"
    _make_holdout(holdout_path)
    monkeypatch.setattr(brs, "HOLDOUT", holdout_path)
    monkeypatch.setattr(brs, "N_SAMPLE", 30)

    monkeypatch.setattr(brs, "REFERENCE_SET", tmp_path / "reference_a.csv")
    brs.main()
    monkeypatch.setattr(brs, "REFERENCE_SET", tmp_path / "reference_b.csv")
    brs.main()

    sample_a = pd.read_csv(tmp_path / "reference_a.csv")
    sample_b = pd.read_csv(tmp_path / "reference_b.csv")
    pd.testing.assert_frame_equal(sample_a, sample_b)
