from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from alpha.decision_superiority import pre2016_emergency_calendar as emergency
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)


def test_build_emergency_holiday_source_is_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4 governed emergency fixture"
    source_document = tmp_path / "27072005.pdf"
    source_document.write_bytes(raw)
    text = (
        "Press Release Archives\n"
        "Jul 27, 2005\n"
        "Trading holiday and Postponement of July expiry\n"
        "NSE and BSE markets closed on Thursday, July 28, 2005"
    )
    rendered = text + "\n"
    monkeypatch.setattr(
        emergency,
        "EXPECTED_DOCUMENT_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(
        emergency,
        "EXPECTED_EXTRACTED_TEXT_SHA256",
        hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(emergency, "_extract_pdf_text", lambda _: text)

    output = emergency.build_2005_emergency_holiday_source(
        source_document=source_document,
        output_root=tmp_path / "output",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["covered_years"] == [2005]
    assert payload["segment_scope"] == "EXCHANGE_WIDE"
    assert payload["holidays"] == [
        {
            "description": (
                "Emergency exchange-wide market closure following an "
                "unscheduled consecutive banking holiday"
            ),
            "trading_date": "2005-07-28",
        }
    ]
    assert payload["special_sessions"] == []
    assert payload["source_document_sha256"] == hashlib.sha256(raw).hexdigest()
    assert payload["content_validation_passed"] is True
    assert payload["manual_review_completed"] is True
    assert payload["classification_inferred_from_archive_status"] is False
    assert payload["classification_inferred_from_observed_candles"] is False
    assert payload["production_influence"] is False


def test_build_emergency_holiday_source_rejects_hash_mismatch(
    tmp_path: Path,
) -> None:
    source_document = tmp_path / "27072005.pdf"
    source_document.write_bytes(b"%PDF-1.4 wrong source")

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_EMERGENCY_HOLIDAY_DOCUMENT_HASH_MISMATCH",
    ):
        emergency.build_2005_emergency_holiday_source(
            source_document=source_document,
            output_root=tmp_path / "output",
        )


def test_build_emergency_holiday_source_rejects_missing_closure_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"%PDF-1.4 governed emergency fixture"
    source_document = tmp_path / "27072005.pdf"
    source_document.write_bytes(raw)
    text = (
        "Press Release Archives\n"
        "Jul 27, 2005\n"
        "Trading holiday and Postponement of July expiry"
    )
    rendered = text + "\n"
    monkeypatch.setattr(
        emergency,
        "EXPECTED_DOCUMENT_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(
        emergency,
        "EXPECTED_EXTRACTED_TEXT_SHA256",
        hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(emergency, "_extract_pdf_text", lambda _: text)

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_EMERGENCY_HOLIDAY_CONTENT_INVALID",
    ):
        emergency.build_2005_emergency_holiday_source(
            source_document=source_document,
            output_root=tmp_path / "output",
        )
