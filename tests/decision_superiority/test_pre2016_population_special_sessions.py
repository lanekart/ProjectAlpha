from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from alpha.decision_superiority import pre2016_population
from alpha.decision_superiority.pre2016_population import (
    Pre2016PopulationError,
    populate_pre2016_historical_truth,
)
from alpha.historical_truth.models import ArchiveRequest
from alpha.historical_truth.population import PopulationRecord


def test_population_includes_governed_weekend_special_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[date] = []
    _patch_population(monkeypatch, captured)

    result = populate_pre2016_historical_truth(
        root=tmp_path / "alpha_data",
        output_dir=tmp_path / "artifacts",
        start=date(2013, 1, 1),
        end=date(2013, 12, 31),
        special_session_dates=(date(2013, 11, 3),),
    )

    assert date(2013, 11, 3) in captured
    assert captured.count(date(2013, 11, 3)) == 1
    assert result.planned_requests == len(captured)


def test_population_deduplicates_weekday_special_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[date] = []
    _patch_population(monkeypatch, captured)

    populate_pre2016_historical_truth(
        root=tmp_path / "alpha_data",
        output_dir=tmp_path / "artifacts",
        start=date(2011, 10, 26),
        end=date(2011, 10, 26),
        special_session_dates=(date(2011, 10, 26),),
    )

    assert captured == [date(2011, 10, 26)]


def test_population_rejects_special_session_outside_requested_range(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        Pre2016PopulationError,
        match="PRE2016_POPULATION_SPECIAL_SESSION_OUTSIDE_RANGE",
    ):
        populate_pre2016_historical_truth(
            root=tmp_path / "alpha_data",
            output_dir=tmp_path / "artifacts",
            start=date(2013, 1, 1),
            end=date(2013, 12, 31),
            special_session_dates=(date(2014, 1, 1),),
        )


def _patch_population(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[date],
) -> None:
    monkeypatch.setattr(
        "alpha.decision_superiority.pre2016_population.shutil.disk_usage",
        lambda _: SimpleNamespace(free=20 * 1024**3),
    )

    def populate(
        self: object,
        requests: tuple[ArchiveRequest, ...],
        *,
        retry_failed: bool,
    ) -> tuple[PopulationRecord, ...]:
        del self, retry_failed
        captured.extend(request.trading_date for request in requests)
        return ()

    monkeypatch.setattr(
        pre2016_population.HistoricalPopulationEngine,
        "populate",
        populate,
    )
    monkeypatch.setattr(
        pre2016_population.HistoricalPopulationEngine,
        "export",
        lambda self, records, output_dir: (),
    )
