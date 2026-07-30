from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pytest

from alpha.decision_superiority import pre2016_2008_emergency_closure as closure
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse

_CM_HTML = b"""
<html><body>
NATIONAL SECURITIES CLEARING CORPORATION LIMITED
Download ref no: NSE/CMPT/11689
November 27, 2008
Sub: Change in settlement schedule on account of postponement of settlement
on November 27, 2008
SETTLEMENT CALENDAR NORMAL SEGMENT (ROLLING T+2)
N 2008224 26-Nov-08 26-Nov-08 28-Nov-08 01-Dec-08
N 2008225 28-Nov-08 28-Nov-08 01-Dec-08 02-Dec-08
</body></html>
"""
_FO_HTML = b"""
<html><body>
NATIONAL STOCK EXCHANGE OF INDIA LIMITED
FUTURES & OPTIONS SEGMENT
Download No: NSE/FAOP/11688
November 27, 2008
Trading holiday & change of Expiry date for Derivatives contracts
Pursuant to November 27, 2008 being declared as a trading holiday,
members are requested to note the revised expiry date.
</body></html>
"""
_API_PAYLOAD = {
    "data": [
        {
            "cirDate": "20081127",
            "cirDisplayDate": "November 27, 2008",
            "circCategory": "Clearing",
            "circCompany": "NSE",
            "circDepartment": "NSE Clearing - Capital Market",
            "circDisplayNo": "NSE/cmpt/11689",
            "circFilelink": closure.CAPITAL_MARKET_URL,
            "circFilename": "cmpt11689.htm",
            "circNumber": "11689",
            "fileDept": "cmpt",
            "fileExt": "htm",
            "sub": (
                "Change in settlement schedule on account of postponement "
                "of settlement on November 27, 2008."
            ),
        },
        {
            "cirDate": "20081127",
            "cirDisplayDate": "November 27, 2008",
            "circCategory": "Trading",
            "circCompany": "NSE",
            "circDepartment": "Futures & Options",
            "circDisplayNo": "NSE/faop/11688",
            "circFilelink": closure.FUTURES_OPTIONS_URL,
            "circFilename": "faop11688.htm",
            "circNumber": "11688",
            "fileDept": "faop",
            "fileExt": "htm",
            "sub": "Trading holiday & change of Expiry date for Derivatives contracts",
        },
    ]
}


@dataclass
class _Response:
    status_code: int
    content: bytes
    url: str
    headers: dict[str, str]


class _Session:
    def __init__(self, *, include_fo_api_row: bool = True) -> None:
        api_payload = json.loads(json.dumps(_API_PAYLOAD))
        if not include_fo_api_row:
            api_payload["data"] = [api_payload["data"][0]]
        self._responses = {
            "https://www.nseindia.com/": _Response(
                200,
                b"ok",
                "https://www.nseindia.com/",
                {"Content-Type": "text/html"},
            ),
            closure.CAPITAL_MARKET_URL: _Response(
                200,
                _CM_HTML,
                closure.CAPITAL_MARKET_URL,
                {"Content-Type": "text/html"},
            ),
            closure.FUTURES_OPTIONS_URL: _Response(
                200,
                _FO_HTML,
                closure.FUTURES_OPTIONS_URL,
                {"Content-Type": "text/html"},
            ),
            closure.CIRCULAR_API_URL: _Response(
                200,
                json.dumps(api_payload).encode("utf-8"),
                closure.CIRCULAR_API_URL,
                {"Content-Type": "application/json"},
            ),
        }

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        del headers, timeout
        return self._responses[url]


def _database(path: Path, *, with_emergency_candle: bool = False) -> Path:
    CanonicalPointInTimeWarehouse(path).initialise()
    if with_emergency_candle:
        with duckdb.connect(str(path)) as connection:
            connection.execute(
                """
                INSERT INTO daily_candle VALUES (
                    DATE '2008-11-27', 'nse', 'TEST', 'EQ', NULL,
                    1.0, 1.0, 1.0, 1.0, 1, 'test-source'
                )
                """
            )
    return path


def _patch_expected_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        closure,
        "CAPITAL_MARKET_EXPECTED_SHA256",
        hashlib.sha256(_CM_HTML).hexdigest(),
    )
    monkeypatch.setattr(
        closure,
        "FUTURES_OPTIONS_EXPECTED_SHA256",
        hashlib.sha256(_FO_HTML).hexdigest(),
    )


def test_composite_emergency_source_is_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_hashes(monkeypatch)
    database = _database(tmp_path / "historical_truth.duckdb")

    result = closure.build_2008_emergency_closure_source(
        database=database,
        output_root=tmp_path / "source",
        session=_Session(),
    )
    payload = closure.validate_2008_emergency_closure_source(
        result.source_path,
        database=database,
    )

    assert payload["source_id"] == closure.SOURCE_ID
    assert payload["segment_scope"] == "CAPITAL_MARKET"
    assert payload["holidays"] == [
        {
            "description": (
                "Emergency trading holiday - Mumbai attacks; "
                "CM clearing calendar and F&O holiday corroboration"
            ),
            "trading_date": "2008-11-27",
        }
    ]
    assert payload["cross_segment_evidence_rule_satisfied"] is True
    assert payload["classification_inferred_from_observed_candles"] is False
    assert result.capital_market_candle_count == 0


def test_composite_bundle_tampering_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_hashes(monkeypatch)
    database = _database(tmp_path / "historical_truth.duckdb")
    result = closure.build_2008_emergency_closure_source(
        database=database,
        output_root=tmp_path / "source",
        session=_Session(),
    )
    payload = json.loads(result.source_path.read_text(encoding="utf-8"))
    bundle_path = Path(payload["source_document_path"])
    with zipfile.ZipFile(bundle_path) as bundle:
        members = {name: bundle.read(name) for name in bundle.namelist()}
    members["capital_market_clearing.html"] = b"tampered"
    closure._write_deterministic_bundle(bundle_path, members)
    payload["source_document_sha256"] = hashlib.sha256(
        bundle_path.read_bytes()
    ).hexdigest()
    result.source_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="DSI010_2008_EMERGENCY_BUNDLE_CM_HASH_MISMATCH",
    ):
        closure.validate_2008_emergency_closure_source(
            result.source_path,
            database=database,
        )


def test_emergency_source_rejects_present_capital_market_candles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_hashes(monkeypatch)
    database = _database(
        tmp_path / "historical_truth.duckdb",
        with_emergency_candle=True,
    )

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="DSI010_2008_EMERGENCY_CM_CANDLES_PRESENT",
    ):
        closure.build_2008_emergency_closure_source(
            database=database,
            output_root=tmp_path / "source",
            session=_Session(),
        )


def test_emergency_source_requires_both_official_api_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_hashes(monkeypatch)
    database = _database(tmp_path / "historical_truth.duckdb")

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="DSI010_2008_EMERGENCY_API_REQUIRED_ROWS_MISSING",
    ):
        closure.build_2008_emergency_closure_source(
            database=database,
            output_root=tmp_path / "source",
            session=_Session(include_fo_api_row=False),
        )
