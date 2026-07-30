"""Hash-bound exchange-wide emergency calendar evidence for DSI-010."""

from __future__ import annotations

import csv
import hashlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from .pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    validate_hash_bound_official_calendar_source,
)
from .pre2016_external_validation_models import Pre2016ExternalValidationError

SOURCE_ID = "NSE_PRESS_27072005_EXCHANGE_WIDE_CLOSURE"
SOURCE_URL = "https://nsearchives.nseindia.com/content/press/27072005.pdf"
EXPECTED_DOCUMENT_SHA256 = (
    "1d8fed637e788f3eb75840d04704f67652468c7f3b53d4a4c9dce95000a30264"
)
EXPECTED_EXTRACTED_TEXT_SHA256 = (
    "4e236a0f41454e2a6a76464db4e22d87d7d34d4c125b6044a781b433eb474c9f"
)
_REQUIRED_TEXT = (
    "Press Release Archives",
    "Jul 27, 2005",
    "Trading holiday and Postponement of July expiry",
    "NSE and BSE markets closed on Thursday, July 28, 2005",
)


def build_2005_emergency_holiday_source(
    *,
    source_document: Path,
    output_root: Path,
) -> Path:
    """Validate and bind the official July 28, 2005 emergency closure."""

    if not source_document.is_file():
        raise Pre2016ExternalValidationError(
            "PRE2016_EMERGENCY_HOLIDAY_DOCUMENT_MISSING"
        )
    raw = source_document.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise Pre2016ExternalValidationError(
            "PRE2016_EMERGENCY_HOLIDAY_PDF_SIGNATURE_INVALID"
        )
    observed_hash = hashlib.sha256(raw).hexdigest()
    if observed_hash != EXPECTED_DOCUMENT_SHA256:
        raise Pre2016ExternalValidationError(
            "PRE2016_EMERGENCY_HOLIDAY_DOCUMENT_HASH_MISMATCH"
        )

    text = _extract_pdf_text(raw)
    rendered = text.rstrip() + "\n"
    text_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if text_hash != EXPECTED_EXTRACTED_TEXT_SHA256:
        raise Pre2016ExternalValidationError(
            "PRE2016_EMERGENCY_HOLIDAY_TEXT_HASH_MISMATCH"
        )
    normalized = " ".join(text.split())
    missing = tuple(token for token in _REQUIRED_TEXT if token not in normalized)
    if missing:
        raise Pre2016ExternalValidationError(
            "PRE2016_EMERGENCY_HOLIDAY_CONTENT_INVALID:" + ";".join(missing)
        )

    output_root.mkdir(parents=True, exist_ok=True)
    extracted_text = output_root / "extracted_text.txt"
    extracted_text.write_text(rendered, encoding="utf-8")
    validation = output_root / "content_validation.txt"
    validation.write_text(
        "\n".join(
            (
                "official_nse_domain: MATCHED",
                "press_release_date: MATCHED",
                "subject: MATCHED",
                "exchange_wide_closure_statement: MATCHED",
                f"source_document_sha256: {observed_hash}",
                f"extracted_text_sha256: {text_hash}",
                "OFFICIAL_PRESS_RELEASE_CONTENT_VALID=true",
                "CLASSIFICATION_INFERRED_FROM_ARCHIVE_STATUS=false",
                "CLASSIFICATION_INFERRED_FROM_OBSERVED_CANDLES=false",
                "PRODUCTION_INFLUENCE=false",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    review_csv = output_root / "reviewed_calendar.csv"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "trading_date",
                "classification",
                "description",
                "review_state",
                "segment_scope",
                "source_id",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "trading_date": "2005-07-28",
                "classification": "HOLIDAY",
                "description": (
                    "Emergency exchange-wide market closure following an "
                    "unscheduled consecutive banking holiday"
                ),
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
                "segment_scope": "EXCHANGE_WIDE",
                "source_id": SOURCE_ID,
            }
        )

    output = output_root / "nse_2005_emergency_holiday.json"
    build_reviewed_official_calendar_source(
        review_csv=review_csv,
        source_document=source_document,
        source_url=SOURCE_URL,
        source_id=SOURCE_ID,
        covered_years=(2005,),
        output=output,
        segment_scope="EXCHANGE_WIDE",
        extracted_text=extracted_text,
        content_validation=validation,
    )
    validate_hash_bound_official_calendar_source(
        output,
        require_capital_market_scope=True,
    )
    return output


def _extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw))
    pages = tuple(
        text for page in reader.pages if (text := (page.extract_text() or "").strip())
    )
    rendered = "\n".join(pages)
    if not rendered:
        raise Pre2016ExternalValidationError("PRE2016_EMERGENCY_HOLIDAY_TEXT_EMPTY")
    return rendered


__all__ = [
    "EXPECTED_DOCUMENT_SHA256",
    "EXPECTED_EXTRACTED_TEXT_SHA256",
    "SOURCE_ID",
    "SOURCE_URL",
    "build_2005_emergency_holiday_source",
]
