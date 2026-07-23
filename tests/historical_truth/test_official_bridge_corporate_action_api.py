from __future__ import annotations

from alpha.historical_truth.official_bridge_document_downloader import (
    _resolved_request_url,
    _suffix,
)
from alpha.historical_truth.official_bridge_source_role_validation import (
    validate_source_role_url,
)


def test_quote_action_source_resolves_to_exact_nse_api_window() -> None:
    row = {
        "evidence_role": "CORPORATE_ACTION",
        "post_symbol": "AJMERA",
        "effective_date": "2026-01-14",
    }

    resolved = _resolved_request_url(
        row,
        "https://www.nseindia.com/get-quotes/equity?symbol=AJMERA",
    )

    assert resolved.startswith(
        "https://www.nseindia.com/api/corporates-corporateActions?"
    )
    assert "index=equities" in resolved
    assert "symbol=AJMERA" in resolved
    assert "from_date=04-01-2026" in resolved
    assert "to_date=24-01-2026" in resolved


def test_existing_action_api_url_is_not_rewritten() -> None:
    source = (
        "https://www.nseindia.com/api/corporates-corporateActions?"
        "index=equities&symbol=MCX&from_date=01-01-2026&to_date=10-01-2026"
    )

    assert _resolved_request_url(
        {
            "evidence_role": "CORPORATE_ACTION",
            "post_symbol": "MCX",
            "effective_date": "2026-01-02",
        },
        source,
    ) == source


def test_action_api_is_structurally_valid_only_with_required_parameters() -> None:
    valid = (
        "https://www.nseindia.com/api/corporates-corporateActions?"
        "index=equities&symbol=MCX&from_date=01-01-2026&to_date=10-01-2026"
    )
    invalid = (
        "https://www.nseindia.com/api/corporates-corporateActions?"
        "index=equities&symbol=MCX"
    )

    assert validate_source_role_url("CORPORATE_ACTION", valid)[0] is True
    assert validate_source_role_url("CORPORATE_ACTION", invalid) == (
        False,
        "ACTION_SOURCE_PATTERN_NOT_APPROVED",
    )


def test_json_content_type_uses_json_suffix() -> None:
    assert _suffix("application/json", "https://www.nseindia.com/api/test") == ".json"
