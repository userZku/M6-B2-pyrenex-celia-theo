"""Tests pytest pour scripts/generate_traffic.py (générateur de trafic de scoring)."""

from __future__ import annotations

import random
import sys
from urllib.error import HTTPError, URLError

import pytest

import generate_traffic as gt


def test_build_payload_has_all_expected_keys():
    payload = gt.build_payload(random.Random(42))

    assert set(payload) == {
        "loan_amnt",
        "int_rate",
        "installment",
        "annual_inc",
        "dti",
        "delinq_2yrs",
        "fico_range_low",
        "revol_util",
        "term",
        "grade",
        "home_ownership",
        "verification_status",
        "purpose",
        "emp_length",
    }
    assert payload["term"] in {"36 months", "60 months"}


def test_parse_args_uses_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["generate_traffic.py"])

    args = gt.parse_args()

    assert args.requests == 100
    assert args.concurrency == 10
    assert args.timeout == 10.0


def test_parse_args_rejects_non_positive_requests(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["generate_traffic.py", "--requests", "0"])

    with pytest.raises(SystemExit):
        gt.parse_args()


def test_send_request_success(monkeypatch):
    class FakeResponse:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(gt, "urlopen", lambda request, timeout: FakeResponse())

    result = gt.send_request("http://localhost:8001/score", {"a": 1}, timeout=1.0)

    assert result.status == 200
    assert result.error is None


def test_send_request_http_error(monkeypatch):
    def raise_http_error(request, timeout):
        raise HTTPError(url="http://x", code=422, msg="invalid", hdrs=None, fp=None)

    monkeypatch.setattr(gt, "urlopen", raise_http_error)

    result = gt.send_request("http://localhost:8001/score", {"a": 1}, timeout=1.0)

    assert result.status == 422
    assert result.error is not None


def test_send_request_connection_error(monkeypatch):
    def raise_url_error(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(gt, "urlopen", raise_url_error)

    result = gt.send_request("http://localhost:8001/score", {"a": 1}, timeout=1.0)

    assert result.status is None
    assert result.error is not None
