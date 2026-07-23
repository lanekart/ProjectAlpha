from __future__ import annotations

import json

from alpha.historical_truth.official_bridge_action_evidence import (
    match_corporate_action_payload,
)


def test_action_match_accepts_exact_symbol_date_and_split_purpose() -> None:
    payload = json.dumps(
        [
            {
                "symbol": "AJMERA",
                "exDate": "14-Jan-2026",
                "recordDate": "14-Jan-2026",
                "purpose": "Face Value Split (Sub-Division)",
            }
        ]
    ).encode()

    match = match_corporate_action_payload(
        payload=payload,
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert match.proved is True
    assert match.state == "ACTION_ROW_VERIFIED"
    assert match.matched_row_count == 1


def test_action_match_handles_nested_api_data() -> None:
    payload = json.dumps(
        {
            "data": [
                {
                    "symbol": "KOTYARK",
                    "record_date": "24-06-2026",
                    "description": "Change in series from EQ to BE",
                }
            ]
        }
    ).encode()

    match = match_corporate_action_payload(
        payload=payload,
        symbol="KOTYARK",
        effective_date="2026-06-24",
    )

    assert match.proved is True
    assert match.state == "ACTION_ROW_VERIFIED"


def test_action_match_fails_closed_for_empty_response() -> None:
    match = match_corporate_action_payload(
        payload=b"[]",
        symbol="MCX",
        effective_date="2026-01-02",
    )

    assert match.proved is False
    assert match.state == "ACTION_API_RETURNED_NO_ROWS"


def test_action_match_distinguishes_symbol_date_and_purpose_failures() -> None:
    symbol_missing = match_corporate_action_payload(
        payload=json.dumps(
            [{"symbol": "OTHER", "exDate": "14-Jan-2026", "purpose": "Split"}]
        ).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )
    date_missing = match_corporate_action_payload(
        payload=json.dumps(
            [{"symbol": "AJMERA", "exDate": "15-Jan-2026", "purpose": "Split"}]
        ).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )
    purpose_missing = match_corporate_action_payload(
        payload=json.dumps(
            [{"symbol": "AJMERA", "exDate": "14-Jan-2026", "purpose": "Dividend"}]
        ).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert symbol_missing.state == "ACTION_SYMBOL_NOT_FOUND"
    assert date_missing.state == "ACTION_EFFECTIVE_DATE_NOT_FOUND"
    assert purpose_missing.state == "ACTION_PURPOSE_NOT_SUPPORTED"


def test_action_match_accepts_equivalent_duplicate_rows() -> None:
    row = {
        "symbol": "AJMERA",
        "exDate": "14-Jan-2026",
        "purpose": "Face Value Split",
    }
    match = match_corporate_action_payload(
        payload=json.dumps([row, row]).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert match.proved is True
    assert match.state == "ACTION_ROWS_EQUIVALENT_DUPLICATES"
    assert match.matched_row_count == 2


def test_action_match_accepts_metadata_only_duplicate_rows() -> None:
    rows = [
        {
            "symbol": "AJMERA",
            "exDate": "14-Jan-2026",
            "purpose": "Face Value Split",
            "companyName": "Ajmera Realty",
        },
        {
            "symbol": "AJMERA",
            "exDate": "14-Jan-2026",
            "purpose": "Face Value Split",
            "companyName": "AJMERA REALTY & INFRA INDIA LIMITED",
        },
    ]
    match = match_corporate_action_payload(
        payload=json.dumps(rows).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert match.proved is True
    assert match.state == "ACTION_ROWS_EQUIVALENT_DUPLICATES"


def test_action_match_rejects_materially_conflicting_rows() -> None:
    rows = [
        {
            "symbol": "AJMERA",
            "exDate": "14-Jan-2026",
            "purpose": "Face Value Split",
        },
        {
            "symbol": "AJMERA",
            "recordDate": "14-Jan-2026",
            "purpose": "Bonus 1:1",
        },
    ]
    match = match_corporate_action_payload(
        payload=json.dumps(rows).encode(),
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert match.proved is False
    assert match.state == "ACTION_ROWS_CONFLICTING"
    assert match.matched_row_count == 2


def test_action_match_rejects_non_json_payload() -> None:
    match = match_corporate_action_payload(
        payload=b"<html>not json</html>",
        symbol="AJMERA",
        effective_date="2026-01-14",
    )

    assert match.proved is False
    assert match.state == "ACTION_PAYLOAD_NOT_VALID_JSON"
