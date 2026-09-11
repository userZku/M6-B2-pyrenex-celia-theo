"""Tests pytest pour scripts/bootstrap_noise.py (bruit d'échantillonnage bootstrap)."""

from __future__ import annotations

import re

import pytest

import bootstrap_noise as bn


def test_main_prints_sigma_for_the_four_target_metrics(capsys):
    bn.main()

    captured = capsys.readouterr().out
    for metric in ("f1_macro", "f1_default", "roc_auc", "recall_default"):
        match = re.search(rf"{metric}: sigma=([0-9.]+)\s+2 sigma=([0-9.]+)", captured)
        assert match, f"missing sigma line for {metric} in output:\n{captured}"
        sigma = float(match.group(1))
        two_sigma = float(match.group(2))
        assert sigma >= 0
        assert two_sigma == pytest.approx(2 * sigma, abs=1e-3)

