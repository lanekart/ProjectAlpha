"""Governed retrospective execution of the frozen current Alpha pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import cast

import duckdb
import pandas as pd

from alpha.canonical_universe_audit.canonical_runner import CanonicalAlphaRunner
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.recommendation_intelligence import RecommendationReport
from alpha.research.lab_models import AlphaSignalSource

FROZEN_ALPHA_REPLAY_VERSION = "DSI-011A-frozen-alpha-replay-v1.0.0"
FEATURE_VERSION = "CANONICAL_ALPHA_FEATURES_AT_SOURCE_COMMIT"
PRODUCTION_INFLUENCE = False

_PRICE_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sector",
    "exchange",
)


@dataclass(frozen=True, slots=True)
class FrozenAlphaReplayReport:
    run_id: str
    start_date: date
    end_date: date
    sessions_requested: int
    sessions_completed: int
    sessions_failed: int
    recommendation_count: int
    buy_count: int
    strong_buy_count: int
    earliest_signal_date: date | None
    data_logical_sha256: str
    ledger_logical_sha256: str
    readiness_state: str
    engine_version: str = FROZEN_ALPHA_REPLAY_VERSION
    feature_version: str = FEATURE_VERSION
    signal_source_state: str = AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY.value
    production_influence: bool = PRODUCTION_INFLUENCE

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["earliest_signal_date"] = (
            None
            if self.earliest_signal_date is None
            else self.earliest_signal_date.isoformat()
        )
        return payload


class ResearchMarketDataStore:
    """Read-only canonical-runner adapter over governed research prices."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"Historical Truth database not found: {self.path}")
        self.connection = duckdb.connect(str(self.path), read_only=True)
        self._history_cache: dict[str, pd.DataFrame] = {}

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ResearchMarketDataStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self.connection.execute(
            """
            SELECT symbol, trading_date AS trade_date,
                   adjusted_open AS open, adjusted_high AS high,
                   adjusted_low AS low, adjusted_close AS close,
                   adjusted_volume AS volume, 'UNKNOWN' AS sector, exchange
            FROM research_daily_candle
            WHERE trading_date = ?
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
              AND adjusted_open > 0 AND adjusted_high > 0
              AND adjusted_low > 0 AND adjusted_close > 0
              AND adjusted_volume >= 0
            ORDER BY symbol
            """,
            [trade_date],
        ).fetchdf()

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not normalized:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        if limit < 1:
            raise ValueError("history limit must be positive")
        placeholders = ", ".join("?" for _ in normalized)
        current = self.connection.execute(
            f"""
            SELECT UPPER(symbol), governed_identity_id
            FROM research_daily_candle
            WHERE trading_date = ?
              AND UPPER(symbol) IN ({placeholders})
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
            ORDER BY symbol
            """,
            [end_date, *normalized],
        ).fetchall()
        frames: list[pd.DataFrame] = []
        for requested_symbol, identity_id in current:
            identity = str(identity_id)
            history = self._history_cache.get(identity)
            if history is None:
                history = self.connection.execute(
                    """
                    SELECT trading_date AS trade_date,
                           adjusted_open AS open, adjusted_high AS high,
                           adjusted_low AS low, adjusted_close AS close,
                           adjusted_volume AS volume, 'UNKNOWN' AS sector,
                           exchange
                    FROM research_daily_candle
                    WHERE governed_identity_id = ?
                      AND research_eligibility_state = 'ELIGIBLE_EQUITY'
                      AND adjusted_open > 0 AND adjusted_high > 0
                      AND adjusted_low > 0 AND adjusted_close > 0
                      AND adjusted_volume >= 0
                    ORDER BY trading_date
                    """,
                    [identity],
                ).fetchdf()
                self._history_cache[identity] = history
            eligible = history.loc[history["trade_date"].dt.date <= end_date].tail(
                limit
            )
            selected = eligible.copy()
            selected.insert(0, "symbol", str(requested_symbol))
            frames.append(selected)
        if not frames:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        return pd.concat(frames, ignore_index=True)[list(_PRICE_COLUMNS)]

    def identity_for(
        self,
        *,
        observed_on: date,
        symbol: str,
    ) -> tuple[str, str, str, str]:
        rows = self.connection.execute(
            """
            SELECT governed_identity_id, isin, symbol, series
            FROM research_daily_candle
            WHERE trading_date = ? AND UPPER(symbol) = ?
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
            ORDER BY governed_identity_id, series
            """,
            [observed_on, symbol.strip().upper()],
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                "recommendation identity is not unique for "
                f"{symbol} on {observed_on}: {len(rows)} rows"
            )
        return cast(tuple[str, str, str, str], tuple(str(item) for item in rows[0]))

    def trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        rows = self.connection.execute(
            """
            SELECT DISTINCT trading_date
            FROM research_daily_candle
            WHERE trading_date BETWEEN ? AND ?
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
            ORDER BY trading_date
            """,
            [start, end],
        ).fetchall()
        return tuple(cast(date, row[0]) for row in rows)


class FrozenAlphaReplayEngine:
    """Persist a versioned, clearly retrospective Alpha recommendation ledger."""

    def run(
        self,
        database: Path,
        *,
        start_date: date,
        end_date: date,
        source_commit: str,
    ) -> FrozenAlphaReplayReport:
        if start_date < date(2016, 1, 1):
            raise ValueError("retrospective Alpha replay cannot precede 2016-01-01")
        if end_date < start_date:
            raise ValueError("replay end date precedes start date")
        data_hash = _certified_data_hash(database, start_date, end_date)
        run_id = _run_id(
            start_date=start_date,
            end_date=end_date,
            source_commit=source_commit,
            data_hash=data_hash,
        )
        with ResearchMarketDataStore(database) as store:
            dates = store.trade_dates(start=start_date, end=end_date)
            runner = CanonicalAlphaRunner(
                store=cast(LegacyMarketDataStore, store),
                adaptive_metadata_publication_enabled=False,
            )
            records: list[tuple[object, ...]] = []
            failures: list[tuple[object, ...]] = []
            for observed_on in dates:
                try:
                    result = runner.run_day(observed_on)
                    for recommendation in result.intelligence.recommendations:
                        identity = store.identity_for(
                            observed_on=observed_on,
                            symbol=recommendation.symbol,
                        )
                        records.append(
                            _recommendation_record(
                                run_id=run_id,
                                source_commit=source_commit,
                                data_hash=data_hash,
                                identity=identity,
                                recommendation=recommendation,
                                regime=result.intelligence.market_report.bias.value,
                            )
                        )
                except Exception as exc:
                    failures.append(
                        (
                            run_id,
                            observed_on,
                            type(exc).__name__,
                            str(exc)[:1000],
                        )
                    )
        report = _persist_replay(
            database=database,
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            source_commit=source_commit,
            data_hash=data_hash,
            sessions_requested=len(dates),
            records=records,
            failures=failures,
        )
        return report


def _recommendation_record(
    *,
    run_id: str,
    source_commit: str,
    data_hash: str,
    identity: tuple[str, str, str, str],
    recommendation: RecommendationReport,
    regime: str,
) -> tuple[object, ...]:
    identity_id, isin, symbol, series = identity
    return (
        run_id,
        recommendation.observed_on,
        identity_id,
        isin,
        symbol,
        series,
        recommendation.decision.value,
        str(recommendation.score),
        recommendation.trade_setup.setup_name,
        (
            recommendation.actionable_trade_strategy.strategy_type.value
            if recommendation.actionable_trade_strategy is not None
            else recommendation.trade_setup.setup_category
        ),
        regime,
        "UNKNOWN",
        _stable_json(recommendation.score_breakdown),
        _stable_json(recommendation.supporting_evidence),
        _stable_json(recommendation.opposing_evidence),
        _stable_json(recommendation.trade_plan),
        FROZEN_ALPHA_REPLAY_VERSION,
        FEATURE_VERSION,
        data_hash,
        source_commit,
        AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY.value,
        False,
    )


def _persist_replay(
    *,
    database: Path,
    run_id: str,
    start_date: date,
    end_date: date,
    source_commit: str,
    data_hash: str,
    sessions_requested: int,
    records: list[tuple[object, ...]],
    failures: list[tuple[object, ...]],
) -> FrozenAlphaReplayReport:
    with duckdb.connect(str(database)) as connection:
        _ensure_tables(connection)
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                "DELETE FROM frozen_recommendation WHERE run_id = ?", [run_id]
            )
            connection.execute(
                "DELETE FROM frozen_recommendation_replay_failure WHERE run_id = ?",
                [run_id],
            )
            if records:
                connection.executemany(
                    "INSERT INTO frozen_recommendation VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    records,
                )
            if failures:
                connection.executemany(
                    "INSERT INTO frozen_recommendation_replay_failure VALUES (?,?,?,?)",
                    failures,
                )
            ledger_hash = _ledger_hash(connection, run_id)
            summary = connection.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE final_verdict = 'BUY'),
                       COUNT(*) FILTER (WHERE final_verdict = 'STRONG_BUY'),
                       MIN(generated_at)
                FROM frozen_recommendation WHERE run_id = ?
                """,
                [run_id],
            ).fetchone()
            recommendation_count = int(summary[0] or 0) if summary else 0
            buy_count = int(summary[1] or 0) if summary else 0
            strong_buy_count = int(summary[2] or 0) if summary else 0
            earliest = cast(date | None, summary[3] if summary else None)
            completed = sessions_requested - len(failures)
            state = (
                "RETROSPECTIVE_ALPHA_REPLAY_READY"
                if completed == sessions_requested and recommendation_count > 0
                else "BLOCKED_BY_RETROSPECTIVE_ALPHA_REPLAY_FAILURE"
            )
            connection.execute(
                "DELETE FROM frozen_recommendation_replay_run WHERE run_id = ?",
                [run_id],
            )
            connection.execute(
                """
                INSERT INTO frozen_recommendation_replay_run
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, false)
                """,
                [
                    run_id,
                    start_date,
                    end_date,
                    sessions_requested,
                    completed,
                    len(failures),
                    recommendation_count,
                    buy_count,
                    strong_buy_count,
                    earliest,
                    data_hash,
                    ledger_hash,
                    source_commit,
                    FROZEN_ALPHA_REPLAY_VERSION,
                    state,
                ],
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return FrozenAlphaReplayReport(
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        sessions_requested=sessions_requested,
        sessions_completed=completed,
        sessions_failed=len(failures),
        recommendation_count=recommendation_count,
        buy_count=buy_count,
        strong_buy_count=strong_buy_count,
        earliest_signal_date=earliest,
        data_logical_sha256=data_hash,
        ledger_logical_sha256=ledger_hash,
        readiness_state=state,
    )


def _ensure_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS frozen_recommendation(
            run_id VARCHAR NOT NULL,
            generated_at DATE NOT NULL,
            governed_identity_id VARCHAR NOT NULL,
            isin VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            series VARCHAR NOT NULL,
            final_verdict VARCHAR NOT NULL,
            recommendation_score VARCHAR NOT NULL,
            setup VARCHAR NOT NULL,
            strategy VARCHAR NOT NULL,
            regime VARCHAR NOT NULL,
            sector VARCHAR NOT NULL,
            component_scores_json VARCHAR NOT NULL,
            entry_evidence_json VARCHAR NOT NULL,
            invalidation_evidence_json VARCHAR NOT NULL,
            trade_plan_json VARCHAR NOT NULL,
            engine_version VARCHAR NOT NULL,
            feature_version VARCHAR NOT NULL,
            source_data_hash VARCHAR NOT NULL,
            source_commit VARCHAR NOT NULL,
            signal_source_state VARCHAR NOT NULL,
            production_influence BOOLEAN NOT NULL,
            PRIMARY KEY(run_id, generated_at, governed_identity_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS frozen_recommendation_replay_failure(
            run_id VARCHAR NOT NULL,
            trading_date DATE NOT NULL,
            error_type VARCHAR NOT NULL,
            sanitized_message VARCHAR NOT NULL,
            PRIMARY KEY(run_id, trading_date)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS frozen_recommendation_replay_run(
            run_id VARCHAR PRIMARY KEY,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            sessions_requested BIGINT NOT NULL,
            sessions_completed BIGINT NOT NULL,
            sessions_failed BIGINT NOT NULL,
            recommendation_count BIGINT NOT NULL,
            buy_count BIGINT NOT NULL,
            strong_buy_count BIGINT NOT NULL,
            earliest_signal_date DATE,
            data_logical_sha256 VARCHAR NOT NULL,
            ledger_logical_sha256 VARCHAR NOT NULL,
            source_commit VARCHAR NOT NULL,
            engine_version VARCHAR NOT NULL,
            readiness_state VARCHAR NOT NULL,
            production_influence BOOLEAN NOT NULL
        )
        """
    )


def _certified_data_hash(database: Path, start_date: date, end_date: date) -> str:
    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            """
            SELECT logical_sha256, readiness_state
            FROM research_price_certification
            WHERE start_date <= ? AND end_date >= ?
            ORDER BY start_date DESC, end_date ASC, contract_version DESC
            LIMIT 1
            """,
            [start_date, end_date],
        ).fetchone()
    if row is None or str(row[1]) != "POST2016_ADJUSTED_REPLAY_READY":
        raise ValueError("certified research-price contract is unavailable")
    return str(row[0])


def _run_id(
    *,
    start_date: date,
    end_date: date,
    source_commit: str,
    data_hash: str,
) -> str:
    payload = "|".join(
        (
            FROZEN_ALPHA_REPLAY_VERSION,
            start_date.isoformat(),
            end_date.isoformat(),
            source_commit,
            data_hash,
        )
    )
    return f"FAR-{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def _ledger_hash(connection: duckdb.DuckDBPyConnection, run_id: str) -> str:
    digest = hashlib.sha256()
    cursor = connection.execute(
        """
        SELECT * FROM frozen_recommendation
        WHERE run_id = ?
        ORDER BY generated_at, governed_identity_id
        """,
        [run_id],
    )
    while rows := cursor.fetchmany(10_000):
        for row in rows:
            digest.update(json.dumps(row, default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def export_frozen_alpha_replay(
    report: FrozenAlphaReplayReport,
    output: Path,
) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "dsi011a_frozen_alpha_replay.json"
    markdown_path = output / "dsi011a_frozen_alpha_replay.md"
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join(
            (
                "# DSI-011A Retrospective Frozen Alpha Replay",
                "",
                f"- Run: `{report.run_id}`",
                f"- Range: {report.start_date} to {report.end_date}",
                f"- Sessions completed: {report.sessions_completed}",
                f"- Recommendations: {report.recommendation_count}",
                f"- BUY: {report.buy_count}",
                f"- STRONG_BUY: {report.strong_buy_count}",
                f"- Readiness: {report.readiness_state}",
                "- Signal source: RETROSPECTIVE_FROZEN_ALPHA_REPLAY",
                "- These recommendations were not issued historically.",
                "- PRODUCTION_INFLUENCE=false",
                "",
            )
        ),
        encoding="utf-8",
    )
    return json_path, markdown_path


__all__ = [
    "FEATURE_VERSION",
    "FROZEN_ALPHA_REPLAY_VERSION",
    "PRODUCTION_INFLUENCE",
    "FrozenAlphaReplayEngine",
    "FrozenAlphaReplayReport",
    "ResearchMarketDataStore",
    "export_frozen_alpha_replay",
]
