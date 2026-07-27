from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.pre2016_calendar_api_probe import (
    export_pre2016_holiday_api_probe,
    probe_pre2016_holiday_api,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: object,
        content_type: str = "application/json",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.headers: Mapping[str, str] = {"Content-Type": content_type}

    def json(self) -> object:
        return self._payload


class _FakeSession:
    def __init__(self, payload_by_year: dict[int, object]) -> None:
        self.payload_by_year = payload_by_year
        self.calls: list[tuple[str, Mapping[str, str] | None]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        del headers, timeout
        self.calls.append((url, params))
        if params is None:
            return _FakeResponse(status_code=200, payload={})
        year = int(params["year"])
        return _FakeResponse(
            status_code=200,
            payload=self.payload_by_year[year],
        )


def test_probe_rejects_current_year_payload_returned_for_historical_request(
    tmp_path: Path,
) -> None:
    current_payload = {
        "CM": [
            {
                "tradingDate": "26-Jan-2026",
                "description": "Republic Day",
            }
        ]
    }
    session = _FakeSession({2005: current_payload, 2006: current_payload})

    result = probe_pre2016_holiday_api(
        output=tmp_path,
        years=(2005, 2006),
        session=session,
    )

    assert result.accepted_years == ()
    assert result.missing_years == (2005, 2006)
    assert len(result.attempts) == 4
    assert all(not item.accepted_as_official_year_source for item in result.attempts)
    assert all(item.covered_years == (2026,) for item in result.attempts)
    assert all(item.out_of_year_row_count == 1 for item in result.attempts)
    assert all(item.raw_path is not None for item in result.attempts)
    assert all(Path(str(item.raw_path)).is_file() for item in result.attempts)


def test_probe_accepts_payload_only_when_all_cm_rows_cover_requested_year(
    tmp_path: Path,
) -> None:
    historical_payload = {
        "CM": [
            {
                "tradingDate": "26-Jan-2005",
                "description": "Republic Day",
            },
            {
                "tradingDate": "15-Aug-2005",
                "description": "Independence Day",
            },
        ]
    }
    session = _FakeSession({2005: historical_payload})

    result = probe_pre2016_holiday_api(
        output=tmp_path,
        years=(2005,),
        session=session,
    )

    assert result.accepted_years == (2005,)
    assert result.missing_years == ()
    assert len(result.attempts) == 2
    assert all(item.accepted_as_official_year_source for item in result.attempts)
    assert all(item.covered_years == (2005,) for item in result.attempts)
    assert all(item.in_year_row_count == 2 for item in result.attempts)
    assert all(item.out_of_year_row_count == 0 for item in result.attempts)


def test_probe_export_keeps_unsupported_payloads_explicit(tmp_path: Path) -> None:
    session = _FakeSession(
        {
            2005: {
                "CM": [
                    {
                        "tradingDate": "26-Jan-2026",
                        "description": "Republic Day",
                    }
                ]
            }
        }
    )
    result = probe_pre2016_holiday_api(
        output=tmp_path,
        years=(2005,),
        session=session,
    )

    attempts_path, summary_path = export_pre2016_holiday_api_probe(
        result,
        tmp_path,
    )

    assert attempts_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["historical_year_api_support"] is False
    assert summary["accepted_years"] == []
    assert summary["missing_years"] == [2005]
    assert summary["unsupported_or_current_year_payloads_rejected"] is True
    assert summary["classification_inferred_from_http_404"] is False


def test_probe_rejects_years_outside_frozen_external_era(tmp_path: Path) -> None:
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_API_PROBE_YEAR_INVALID",
    ):
        probe_pre2016_holiday_api(
            output=tmp_path,
            years=(2016,),
            session=_FakeSession({}),
        )


def test_historical_holiday_api_probe_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-calendar-api-probe" in result.stdout
