"""Complete governed daily research-price materialization for DSI-011A."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

RESEARCH_PRICE_CONTRACT_VERSION = "DSI-011A-research-price-v1.0.0"
ELIGIBLE_EQUITY_SERIES = ("BE", "BZ", "EQ", "SM", "ST")
PRODUCTION_INFLUENCE = False


@dataclass(frozen=True, slots=True)
class ResearchPriceCertification:
    start_date: date
    end_date: date
    expected_sessions: int
    observed_sessions: int
    eligible_securities: int
    total_raw_rows: int
    eligible_raw_rows: int
    ineligible_non_equity_rows: int
    factor_one_rows: int
    adjusted_factor_rows: int
    non_multiplicative_transition_rows: int
    research_rows: int
    unresolved_identity_rows: int
    unresolved_factor_count: int
    duplicate_rows: int
    invalid_adjusted_ohlc_rows: int
    unexplained_missing_rows: int
    preserved_separate_identity_boundaries: int
    logical_sha256: str
    readiness_state: str
    contract_version: str = RESEARCH_PRICE_CONTRACT_VERSION
    production_influence: bool = PRODUCTION_INFLUENCE

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


class ResearchPriceTableBuilder:
    """Materialize one point-in-time row per governed equity security-session."""

    def build(
        self,
        database: Path,
        *,
        start_date: date,
        end_date: date,
    ) -> ResearchPriceCertification:
        if start_date < date(2016, 1, 1):
            raise ValueError("DSI-011A research prices cannot precede 2016-01-01")
        if end_date < start_date:
            raise ValueError("research-price end date precedes start date")
        with duckdb.connect(str(database)) as connection:
            unresolved_factors = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM corporate_action_adjustment_factor f
                JOIN corporate_action_event e USING (action_id)
                WHERE f.effective_date BETWEEN ? AND ?
                  AND e.price_adjustment_required
                  AND f.state IN ('UNKNOWN', 'AMBIGUOUS', 'INVALID', 'CONFLICTING')
                """,
                start_date,
                end_date,
            )
            if unresolved_factors:
                raise ValueError(
                    "cannot materialize research prices with unresolved "
                    f"multiplicative factors: {unresolved_factors}"
                )
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute("DROP TABLE IF EXISTS research_daily_candle")
                connection.execute(
                    """
                    CREATE TABLE research_daily_candle AS
                    SELECT
                        ? AS contract_version,
                        c.trading_date,
                        c.exchange,
                        'nse:isin:' || UPPER(TRIM(c.isin))
                            AS governed_identity_id,
                        UPPER(TRIM(c.isin)) AS isin,
                        UPPER(TRIM(c.symbol)) AS symbol,
                        UPPER(TRIM(c.series)) AS series,
                        c.open_price AS raw_open,
                        c.high_price AS raw_high,
                        c.low_price AS raw_low,
                        c.close_price AS raw_close,
                        c.volume AS raw_volume,
                        COALESCE(a.adjusted_open, c.open_price) AS adjusted_open,
                        COALESCE(a.adjusted_high, c.high_price) AS adjusted_high,
                        COALESCE(a.adjusted_low, c.low_price) AS adjusted_low,
                        COALESCE(a.adjusted_close, c.close_price) AS adjusted_close,
                        COALESCE(a.adjusted_volume, c.volume) AS adjusted_volume,
                        COALESCE(a.price_factor, 1.0)
                            AS cumulative_price_factor,
                        COALESCE(a.quantity_factor, 1.0)
                            AS cumulative_quantity_factor,
                        CASE
                            WHEN UPPER(TRIM(c.series))
                                     NOT IN ('BE', 'BZ', 'EQ', 'SM', 'ST')
                              OR NOT UPPER(TRIM(c.isin)) LIKE 'INE%'
                                THEN 'CERTIFIED_NON_MULTIPLICATIVE_TRANSITION'
                            WHEN a.trading_date IS NULL THEN 'CERTIFIED_FACTOR_ONE'
                            ELSE 'CERTIFIED_ADJUSTED'
                        END AS price_basis_state,
                        'EXACT_DAILY_CANDLE_ISIN' AS identity_source,
                        CASE
                            WHEN UPPER(TRIM(c.series))
                                     NOT IN ('BE', 'BZ', 'EQ', 'SM', 'ST')
                              OR NOT UPPER(TRIM(c.isin)) LIKE 'INE%'
                                THEN 'OFFICIAL_NON_EQUITY_CLASSIFICATION'
                            WHEN a.trading_date IS NULL
                                THEN 'NO_PRIOR_MULTIPLICATIVE_ACTION'
                            ELSE COALESCE(l.lineage_digest, a.calculation_version)
                        END AS factor_source,
                        c.source_sha256,
                        CASE
                            WHEN UPPER(TRIM(c.series))
                                     IN ('BE', 'BZ', 'EQ', 'SM', 'ST')
                             AND UPPER(TRIM(c.isin)) LIKE 'INE%'
                                THEN 'ELIGIBLE_EQUITY'
                            ELSE 'INELIGIBLE_NON_EQUITY'
                        END AS research_eligibility_state,
                        false AS production_influence
                    FROM daily_candle c
                    LEFT JOIN adjusted_daily_candle a
                      USING (trading_date, exchange, symbol, series)
                    LEFT JOIN adjusted_candle_lineage l
                      USING (trading_date, exchange, symbol, series)
                    WHERE c.trading_date BETWEEN ? AND ?
                      AND UPPER(c.exchange) = 'NSE'
                      AND c.isin IS NOT NULL
                      AND TRIM(c.isin) <> ''
                    """,
                    [RESEARCH_PRICE_CONTRACT_VERSION, start_date, end_date],
                )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX research_daily_candle_identity_session
                    ON research_daily_candle(
                        trading_date, governed_identity_id, series
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX research_daily_candle_session_symbol
                    ON research_daily_candle(trading_date, symbol)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX research_daily_candle_symbol_session
                    ON research_daily_candle(symbol, trading_date)
                    """
                )
                _materialize_identity_boundaries(connection)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            report = _certify(connection, start_date, end_date)
            _persist_certification(connection, report)
            return report


def export_research_price_certification(
    report: ResearchPriceCertification,
    output: Path,
) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "dsi011a_research_price_certificate.json"
    markdown_path = output / "dsi011a_research_price_certificate.md"
    payload = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    json_path.write_text(payload, encoding="utf-8")
    markdown_path.write_text(
        "\n".join(
            (
                "# DSI-011A Research Price Certification",
                "",
                f"- Range: {report.start_date} to {report.end_date}",
                f"- Sessions: {report.observed_sessions}",
                f"- Eligible securities: {report.eligible_securities}",
                f"- Total NSE rows: {report.total_raw_rows}",
                f"- Eligible raw rows: {report.eligible_raw_rows}",
                (
                    "- Governed ineligible non-equity rows: "
                    f"{report.ineligible_non_equity_rows}"
                ),
                f"- Factor-one rows: {report.factor_one_rows}",
                f"- Adjusted-factor rows: {report.adjusted_factor_rows}",
                (
                    "- Preserved separate identity boundaries: "
                    f"{report.preserved_separate_identity_boundaries}"
                ),
                f"- Research rows: {report.research_rows}",
                f"- Readiness: {report.readiness_state}",
                f"- Logical SHA-256: `{report.logical_sha256}`",
                "- PRODUCTION_INFLUENCE=false",
                "",
            )
        ),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _certify(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
) -> ResearchPriceCertification:
    total_raw = _scalar(
        connection,
        """
        SELECT COUNT(*) FROM daily_candle
        WHERE trading_date BETWEEN ? AND ?
          AND UPPER(exchange) = 'NSE'
          AND isin IS NOT NULL AND TRIM(isin) <> ''
        """,
        start_date,
        end_date,
    )
    eligible_raw = _scalar(
        connection,
        """
        SELECT COUNT(*) FROM daily_candle
        WHERE trading_date BETWEEN ? AND ?
          AND UPPER(exchange) = 'NSE'
          AND UPPER(TRIM(series)) IN ('BE', 'BZ', 'EQ', 'SM', 'ST')
          AND UPPER(TRIM(isin)) LIKE 'INE%'
          AND isin IS NOT NULL AND TRIM(isin) <> ''
        """,
        start_date,
        end_date,
    )
    expected_sessions = _scalar(
        connection,
        """
        SELECT COUNT(DISTINCT trading_date) FROM daily_candle
        WHERE trading_date BETWEEN ? AND ? AND UPPER(exchange) = 'NSE'
        """,
        start_date,
        end_date,
    )
    summary = connection.execute(
        """
        SELECT COUNT(DISTINCT trading_date),
               COUNT(DISTINCT governed_identity_id),
               COUNT(*),
               COUNT(*) FILTER (
                   WHERE price_basis_state = 'CERTIFIED_FACTOR_ONE'
               ),
               COUNT(*) FILTER (
                   WHERE price_basis_state = 'CERTIFIED_ADJUSTED'
               ),
               COUNT(*) FILTER (
                   WHERE governed_identity_id IS NULL OR isin IS NULL
               ),
               COUNT(*) FILTER (
                   WHERE adjusted_open <= 0 OR adjusted_high <= 0
                      OR adjusted_low <= 0 OR adjusted_close <= 0
                      OR adjusted_high < GREATEST(
                          adjusted_open, adjusted_low, adjusted_close
                      )
                      OR adjusted_low > LEAST(
                          adjusted_open, adjusted_high, adjusted_close
                      )
               )
        FROM research_daily_candle
        WHERE research_eligibility_state = 'ELIGIBLE_EQUITY'
        """
    ).fetchone()
    if summary is None:
        raise RuntimeError("research price certification query returned no row")
    duplicate_rows = _scalar(
        connection,
        """
        SELECT COUNT(*) FROM (
            SELECT trading_date, governed_identity_id, series, COUNT(*) AS n
            FROM research_daily_candle
            WHERE research_eligibility_state = 'ELIGIBLE_EQUITY'
            GROUP BY 1, 2, 3 HAVING COUNT(*) > 1
        )
        """,
    )
    research_rows = int(summary[2] or 0)
    missing = max(0, eligible_raw - research_rows)
    invalid = int(summary[6] or 0)
    observed_sessions = int(summary[0] or 0)
    ready = (
        expected_sessions == observed_sessions
        and missing == 0
        and duplicate_rows == 0
        and invalid == 0
        and int(summary[5] or 0) == 0
    )
    preserved_boundaries = _scalar(
        connection,
        "SELECT COUNT(*) FROM research_identity_boundary",
    )
    return ResearchPriceCertification(
        start_date=start_date,
        end_date=end_date,
        expected_sessions=expected_sessions,
        observed_sessions=observed_sessions,
        eligible_securities=int(summary[1] or 0),
        total_raw_rows=total_raw,
        eligible_raw_rows=eligible_raw,
        ineligible_non_equity_rows=total_raw - eligible_raw,
        factor_one_rows=int(summary[3] or 0),
        adjusted_factor_rows=int(summary[4] or 0),
        non_multiplicative_transition_rows=0,
        research_rows=research_rows,
        unresolved_identity_rows=int(summary[5] or 0),
        unresolved_factor_count=0,
        duplicate_rows=duplicate_rows,
        invalid_adjusted_ohlc_rows=invalid,
        unexplained_missing_rows=missing,
        preserved_separate_identity_boundaries=preserved_boundaries,
        logical_sha256=_logical_sha256(connection),
        readiness_state=(
            "POST2016_ADJUSTED_REPLAY_READY"
            if ready
            else "BLOCKED_BY_RESEARCH_PRICE_RECONCILIATION"
        ),
    )


def _materialize_identity_boundaries(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute("DROP TABLE IF EXISTS research_identity_boundary")
    has_source = bool(
        _scalar(
            connection,
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'price_basis_interval'
            """,
        )
    )
    if not has_source:
        connection.execute(
            """
            CREATE TABLE research_identity_boundary(
                source_contract_version VARCHAR,
                identity_key VARCHAR,
                valid_from DATE,
                valid_to DATE,
                action_ids VARCHAR,
                source_issue_codes VARCHAR,
                research_disposition VARCHAR,
                histories_linked BOOLEAN,
                blocks_research BOOLEAN,
                production_influence BOOLEAN
            )
            """
        )
        return
    connection.execute(
        """
        CREATE TABLE research_identity_boundary AS
        SELECT contract_version AS source_contract_version,
               identity_key, valid_from, valid_to, action_ids,
               issue_codes AS source_issue_codes,
               'PRESERVED_SEPARATE_EXACT_ISIN_IDENTITIES'
                   AS research_disposition,
               false AS histories_linked,
               false AS blocks_research,
               false AS production_influence
        FROM price_basis_interval
        WHERE state = 'IDENTITY_TRANSITION_UNRESOLVED'
          AND (valid_to IS NULL OR valid_to >= DATE '2016-01-01')
        ORDER BY identity_key, valid_from
        """
    )


def _logical_sha256(connection: duckdb.DuckDBPyConnection) -> str:
    digest = hashlib.sha256()
    cursor = connection.execute(
        """
        SELECT * FROM research_daily_candle
        ORDER BY trading_date, governed_identity_id, series
        """
    )
    while rows := cursor.fetchmany(20_000):
        for row in rows:
            digest.update(json.dumps(row, default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _persist_certification(
    connection: duckdb.DuckDBPyConnection,
    report: ResearchPriceCertification,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_price_certification(
            contract_version VARCHAR PRIMARY KEY,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            expected_sessions BIGINT NOT NULL,
            observed_sessions BIGINT NOT NULL,
            eligible_securities BIGINT NOT NULL,
            total_raw_rows BIGINT NOT NULL,
            eligible_raw_rows BIGINT NOT NULL,
            ineligible_non_equity_rows BIGINT NOT NULL,
            research_rows BIGINT NOT NULL,
            logical_sha256 VARCHAR NOT NULL,
            readiness_state VARCHAR NOT NULL,
            production_influence BOOLEAN NOT NULL
        )
        """
    )
    connection.execute(
        """
        ALTER TABLE research_price_certification
        ADD COLUMN IF NOT EXISTS total_raw_rows BIGINT DEFAULT 0
        """
    )
    connection.execute(
        """
        ALTER TABLE research_price_certification
        ADD COLUMN IF NOT EXISTS ineligible_non_equity_rows BIGINT DEFAULT 0
        """
    )
    connection.execute(
        "DELETE FROM research_price_certification WHERE contract_version = ?",
        [report.contract_version],
    )
    connection.execute(
        """
        INSERT INTO research_price_certification(
            contract_version, start_date, end_date, expected_sessions,
            observed_sessions, eligible_securities, total_raw_rows,
            eligible_raw_rows, ineligible_non_equity_rows, research_rows,
            logical_sha256, readiness_state, production_influence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            report.contract_version,
            report.start_date,
            report.end_date,
            report.expected_sessions,
            report.observed_sessions,
            report.eligible_securities,
            report.total_raw_rows,
            report.eligible_raw_rows,
            report.ineligible_non_equity_rows,
            report.research_rows,
            report.logical_sha256,
            report.readiness_state,
            report.production_influence,
        ],
    )


def _scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    *parameters: object,
) -> int:
    row = connection.execute(query, parameters).fetchone()
    return int(row[0] or 0) if row else 0


__all__ = [
    "ELIGIBLE_EQUITY_SERIES",
    "PRODUCTION_INFLUENCE",
    "RESEARCH_PRICE_CONTRACT_VERSION",
    "ResearchPriceCertification",
    "ResearchPriceTableBuilder",
    "export_research_price_certification",
]
