"""CLI for HTR-010B1H window-scoped governed action admission."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.b1_window_action_admission import (
    B1WindowActionAdmissionEngine,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--rejected-actions", type=Path, required=True)
    parser.add_argument("--bridge-exclusions", type=Path)
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--warmup-calendar-days", type=int, default=300)
    parser.add_argument("--outcome-calendar-days", type=int, default=90)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    arguments.output.mkdir(parents=True, exist_ok=True)
    enriched_rejected = arguments.output / "htr010b1h_enriched_rejected_actions.json"
    orphan_count = _enrich_rejected_actions(
        identities_path=arguments.identities,
        rejected_path=arguments.rejected_actions,
        output_path=enriched_rejected,
    )

    report = B1WindowActionAdmissionEngine().run(
        identities_path=arguments.identities,
        actions_path=arguments.actions,
        rejected_actions_path=enriched_rejected,
        bridge_exclusions_path=arguments.bridge_exclusions,
        replay_start=arguments.start,
        replay_end=arguments.end,
        warmup_calendar_days=arguments.warmup_calendar_days,
        outcome_calendar_days=arguments.outcome_calendar_days,
        output=arguments.output,
    )
    print("HTR-010B1H Window-Scoped Action Admission")
    print(f"Identity population: {report['identity_population_count']}")
    print(f"Admitted identities: {report['admitted_identity_count']}")
    print(f"Excluded identities: {report['excluded_identity_count']}")
    print(f"Orphan material actions: {orphan_count}")
    print(
        "Admitted unresolved actions: "
        f"{report['admitted_unresolved_action_count']}"
    )
    print(
        "Universe differences: "
        f"{report['raw_adjusted_universe_difference_count']}"
    )
    print(f"Shadow replay ready: {report['shadow_replay_ready']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


def _enrich_rejected_actions(
    *,
    identities_path: Path,
    rejected_path: Path,
    output_path: Path,
) -> int:
    identities = _rows(identities_path)
    rejected = _rows(rejected_path)
    by_symbol: dict[str, set[str]] = defaultdict(set)
    for row in identities:
        symbol = str(row.get("symbol") or "").strip().upper()
        security_id = str(row.get("security_id") or "").strip()
        if symbol and security_id:
            by_symbol[symbol].add(security_id)

    enriched: list[dict[str, Any]] = []
    ambiguous: list[str] = []
    orphan_count = 0
    for row in rejected:
        material = bool(row.get("price_adjustment_required"))
        current = str(
            row.get("security_id")
            or row.get("governed_identity_id")
            or row.get("identity_key")
            or ""
        ).strip()
        if not current and material:
            symbol = str(row.get("symbol") or "").strip().upper()
            candidates = by_symbol.get(symbol, set())
            if len(candidates) > 1:
                ambiguous.append(
                    f"{row.get('action_id')}:{symbol}:{','.join(sorted(candidates))}"
                )
            elif len(candidates) == 1:
                row = {**row, "security_id": next(iter(candidates))}
            else:
                orphan_count += 1
                row = {
                    **row,
                    "security_id": f"orphan:symbol:{symbol}",
                    "identity_resolution_state": "NO_CANONICAL_IDENTITY_MATCH",
                }
        enriched.append(row)
    if ambiguous:
        raise ValueError(
            "material rejected actions require unique identity resolution: "
            + ";".join(ambiguous[:20])
        )
    output_path.write_text(
        json.dumps(enriched, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return orphan_count


def _rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        nested = next(
            (
                payload.get(key)
                for key in ("records", "data", "timeline", "rows")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        payload = nested if nested is not None else [payload]
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"artifact must contain record mappings: {path}")
    return [dict(row) for row in payload]


if __name__ == "__main__":
    raise SystemExit(main())
