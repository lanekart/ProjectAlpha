from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import duckdb

from alpha.benchmark_replay.signal_audit import (
    export_diagnostic_signal_audit,
    run_diagnostic_signal_audit,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


def test_signal_audit_observes_and_censors_without_fabrication(tmp_path: Path) -> None:
    database = tmp_path / "prices.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR,
            trade_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            sector VARCHAR,
            exchange VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ("TEST", date(2026, 1, 1), 100, 101, 99, 100, 1000, None, "NSE"),
            ("TEST", date(2026, 1, 2), 100, 112, 98, 110, 1000, None, "NSE"),
            ("TEST", date(2026, 1, 5), 110, 116, 109, 115, 1000, None, "NSE"),
        ),
    )
    connection.close()
    approvals = tmp_path / "approval_statistics.csv"
    with approvals.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "observed_on",
                "symbol",
                "final_signal",
                "opportunity_score",
                "primary_reason_code",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "observed_on": "2026-01-01",
                "symbol": "TEST",
                "final_signal": "BUY",
                "opportunity_score": "74.00",
                "primary_reason_code": "INSUFFICIENT_EVIDENCE",
            }
        )
        writer.writerow(
            {
                "observed_on": "2026-01-02",
                "symbol": "TEST",
                "final_signal": "HOLD",
                "opportunity_score": "50.00",
                "primary_reason_code": "WEAK_VERDICT",
            }
        )

    with LegacyMarketDataStore(database) as store:
        audit = run_diagnostic_signal_audit(
            store=store,
            approval_statistics=approvals,
            horizons=(1, 5),
        )

    assert audit.summary["raw_buy_or_strong_buy_signals"] == 1
    assert len(audit.outcomes) == 2
    assert audit.outcomes[0].status == "OBSERVED"
    assert audit.outcomes[0].forward_return_percent == 10
    assert audit.outcomes[0].maximum_favorable_excursion_percent == 12
    assert audit.outcomes[0].maximum_adverse_excursion_percent == -2
    assert audit.outcomes[1].status == "CENSORED_RIGHT_BOUNDARY"
    assert audit.outcomes[1].forward_return_percent is None


def test_signal_audit_export_is_deterministic_and_governed(tmp_path: Path) -> None:
    database = tmp_path / "prices.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
            low DOUBLE, close DOUBLE, volume DOUBLE, sector VARCHAR,
            exchange VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ("TEST", date(2026, 1, 1), 100, 100, 100, 100, 1, None, "NSE"),
            ("TEST", date(2026, 1, 2), 101, 101, 101, 101, 1, None, "NSE"),
        ),
    )
    connection.close()
    approvals = tmp_path / "approval_statistics.csv"
    approvals.write_text(
        "observed_on,symbol,final_signal,opportunity_score,primary_reason_code\n"
        "2026-01-01,TEST,STRONG_BUY,80.00,INSUFFICIENT_EVIDENCE\n",
        encoding="utf-8",
    )
    with LegacyMarketDataStore(database) as store:
        audit = run_diagnostic_signal_audit(
            store=store,
            approval_statistics=approvals,
            horizons=(1,),
        )
    output = tmp_path / "audit"
    first = export_diagnostic_signal_audit(audit, output_directory=output)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = export_diagnostic_signal_audit(audit, output_directory=output)

    assert first_bytes == {path.name: path.read_bytes() for path in second}
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["diagnostic_only"] is True
    assert manifest["production_influence"] is False
    assert len(manifest["artifact_hashes"]) == 3
    assert "never fabricated" in (output / "report.md").read_text(encoding="utf-8")
