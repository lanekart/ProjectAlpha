from __future__ import annotations

from datetime import date, timedelta

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import (
    HistoricalReplaySampler,
    ReplaySampleFrequency,
    render_replay_sample_plan,
)


class FakeReplayDateRepository:
    def __init__(self, dates: tuple[date, ...]) -> None:
        self.dates = dates

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        return tuple(item for item in self.dates if start <= item <= end)


def test_monthly_sample_plan_selects_first_trade_date_per_month() -> None:
    dates = (
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 2, 2),
        date(2026, 2, 3),
        date(2026, 3, 2),
    )

    plan = HistoricalReplaySampler(
        repository=FakeReplayDateRepository(dates),
    ).plan(
        start=date(2026, 1, 1),
        end=date(2026, 3, 31),
        frequency=ReplaySampleFrequency.MONTHLY,
    )

    assert plan.selected_dates == (
        date(2026, 1, 2),
        date(2026, 2, 2),
        date(2026, 3, 2),
    )


def test_quarterly_sample_plan_respects_max_dates() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(180))

    plan = HistoricalReplaySampler(
        repository=FakeReplayDateRepository(dates),
    ).plan(
        start=date(2026, 1, 1),
        end=date(2026, 6, 30),
        frequency=ReplaySampleFrequency.QUARTERLY,
        max_dates=1,
    )

    assert plan.selected_dates == (date(2026, 1, 1),)


def test_sample_plan_rendering_includes_preview() -> None:
    plan = HistoricalReplaySampler(
        repository=FakeReplayDateRepository(
            (date(2026, 1, 2), date(2026, 2, 2)),
        ),
    ).plan(
        start=date(2026, 1, 1),
        end=date(2026, 2, 28),
    )

    output = "\n".join(render_replay_sample_plan(plan))

    assert "Historical Replay Sample Plan" in output
    assert "Selected Replay Dates: 2" in output
    assert "Preview: 2026-01-02, 2026-02-02" in output


def test_replay_sample_plan_cli_output(monkeypatch) -> None:
    class FakePrices:
        def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
            del start, end
            return (date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 2))

    monkeypatch.setattr("alpha.cli.MarketTruthPriceRepository", FakePrices)

    result = CliRunner().invoke(
        app,
        [
            "replay",
            "sample-plan",
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2026-02-28",
        ],
    )

    assert result.exit_code == 0
    assert "Historical Replay Sample Plan" in result.stdout
    assert "Selected Replay Dates: 2" in result.stdout
