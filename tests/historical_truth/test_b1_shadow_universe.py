from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from alpha.historical_truth.b1_shadow_universe import (
    B1UniverseFilteredPriceRepository,
    load_b1_shadow_admission,
)


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    universe = ["nse:isin:INE1", "nse:isin:INE2"]
    contract = {
        "contract_version": "HTR-010B1H-v1.0.0",
        "replay_start": "2026-01-01",
        "replay_end": "2026-07-20",
        "dependency_start": "2025-01-01",
        "dependency_end": "2026-09-30",
        "admitted_identity_count": 2,
        "admitted_unresolved_action_count": 0,
        "raw_adjusted_universe_difference_count": 0,
        "raw_adjusted_session_difference_count": 0,
        "contract_contradiction_count": 0,
        "implementation_defect_count": 0,
        "shadow_replay_ready": True,
        "raw_universe_sha256": _digest(universe),
        "adjusted_universe_sha256": _digest(universe),
        "production_influence": False,
    }
    contract["report_sha256"] = _digest(contract)
    admissions = [
        {
            "security_id": "nse:isin:INE1",
            "symbol": "AAA",
            "raw_admitted": True,
            "adjusted_admitted": True,
        },
        {
            "security_id": "nse:isin:INE2",
            "symbol": "BBB",
            "raw_admitted": True,
            "adjusted_admitted": True,
        },
        {
            "security_id": "nse:isin:INE3",
            "symbol": "CCC",
            "raw_admitted": False,
            "adjusted_admitted": False,
        },
    ]
    return (
        _write(tmp_path / "contract.json", contract),
        _write(tmp_path / "admissions.json", admissions),
        _write(tmp_path / "raw.json", universe),
        _write(tmp_path / "adjusted.json", universe),
    )


def test_loads_verified_b1h_admission(tmp_path: Path) -> None:
    contract, admissions, raw, adjusted = _artifacts(tmp_path)

    result = load_b1_shadow_admission(
        contract_path=contract,
        identity_admission_path=admissions,
        raw_universe_path=raw,
        adjusted_universe_path=adjusted,
    )

    assert result.admitted_security_ids == ("nse:isin:INE1", "nse:isin:INE2")
    assert result.admitted_symbols == ("AAA", "BBB")
    assert result.replay_start == date(2026, 1, 1)
    assert result.replay_end == date(2026, 7, 20)
    assert result.dependency_start == date(2025, 1, 1)
    assert result.dependency_end == date(2026, 9, 30)


def test_rejects_tampered_universe(tmp_path: Path) -> None:
    contract, admissions, raw, adjusted = _artifacts(tmp_path)
    adjusted.write_text(json.dumps(["nse:isin:INE1"]), encoding="utf-8")

    with pytest.raises(ValueError, match="universes differ"):
        load_b1_shadow_admission(
            contract_path=contract,
            identity_admission_path=admissions,
            raw_universe_path=raw,
            adjusted_universe_path=adjusted,
        )


def test_rejects_dependency_window_that_does_not_cover_replay(
    tmp_path: Path,
) -> None:
    contract, admissions, raw, adjusted = _artifacts(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["dependency_start"] = "2026-02-01"
    payload["report_sha256"] = _digest(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not cover replay window"):
        load_b1_shadow_admission(
            contract_path=contract,
            identity_admission_path=admissions,
            raw_universe_path=raw,
            adjusted_universe_path=adjusted,
        )


class _Repository:
    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "trade_date": trade_date,
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                },
                {
                    "symbol": "CCC",
                    "trade_date": trade_date,
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                },
            ]
        )

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        del end_date, limit
        return pd.DataFrame({"symbol": list(symbols)})


def test_price_repository_cannot_leak_excluded_symbols() -> None:
    repository = B1UniverseFilteredPriceRepository(_Repository(), ("AAA", "BBB"))

    daily = repository.find_by_trade_date(date(2026, 1, 2))
    history = repository.find_history_by_symbols(
        symbols=("AAA", "CCC"),
        end_date=date(2026, 1, 2),
        limit=10,
    )

    assert daily["symbol"].tolist() == ["AAA"]
    assert history["symbol"].tolist() == ["AAA"]
