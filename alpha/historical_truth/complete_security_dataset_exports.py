"""Deterministic JSON, CSV, and Markdown artifacts for HTR-010A."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, fields, is_dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from alpha.historical_truth.complete_security_dataset_models import (
    CompleteSecurityDatasetReport,
)


class CompleteSecurityDatasetArtifactExporter:
    """Export the complete-dataset contract using stable names and ordering."""

    def export(
        self,
        report: CompleteSecurityDatasetReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        collections = (
            ("source_inventory", report.source_inventory),
            ("security_census", report.census),
            ("security_identities", report.identities),
            ("identity_intervals", report.identity_intervals),
            ("symbol_intervals", report.symbol_intervals),
            ("series_intervals", report.series_intervals),
            ("membership_intervals", report.membership_intervals),
            ("tradability_intervals", report.tradability_intervals),
            ("suspensions", report.suspensions),
            ("terminations", report.terminations),
            ("symbol_reuse", report.symbol_reuse),
            ("identity_transitions", report.transitions),
            ("candle_reconciliation", report.candle_reconciliation),
            ("security_session_gaps", report.security_session_gaps),
            ("certification_matrix", report.certification_matrix),
            ("rejected_evidence", report.rejected_evidence),
        )
        for stem, records in collections:
            paths.extend(self._collection(output, stem, records))
        executive = output / "htr010a_executive_report.json"
        executive.write_text(
            json.dumps(_executive_payload(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths.append(executive)
        executive_md = output / "htr010a_executive_report.md"
        executive_md.write_text(_executive_markdown(report), encoding="utf-8")
        paths.append(executive_md)
        ytd = output / "htr010a_2026_ytd_report.json"
        ytd.write_text(
            json.dumps(_jsonable(asdict(report.ytd_summary)), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        paths.append(ytd)
        ytd_md = output / "htr010a_2026_ytd_report.md"
        ytd_md.write_text(_ytd_markdown(report), encoding="utf-8")
        paths.append(ytd_md)
        certification = output / "htr010a_certification.json"
        certification.write_text(
            json.dumps(
                {
                    "contract_version": report.contract_version,
                    "production_influence": report.production_influence,
                    "start_date": report.start_date.isoformat(),
                    "end_date": report.end_date.isoformat(),
                    "certification": _jsonable(asdict(report.certification)),
                    "report_sha256": report.report_sha256,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(certification)
        certification_md = output / "htr010a_certification.md"
        certification_md.write_text(_certification_markdown(report), encoding="utf-8")
        paths.append(certification_md)
        return tuple(sorted(paths))

    @staticmethod
    def _collection(
        output: Path,
        stem: str,
        records: Iterable[Any],
    ) -> tuple[Path, Path]:
        values = tuple(records)
        json_path = output / f"htr010a_{stem}.json"
        json_path.write_text(
            json.dumps(
                {"records": [_jsonable(asdict(item)) for item in values]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        csv_path = output / f"htr010a_{stem}.csv"
        field_names = [item.name for item in fields(values[0])] if values else []
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            if field_names:
                writer.writeheader()
                for item in values:
                    writer.writerow(
                        {key: _csv_value(value) for key, value in asdict(item).items()}
                    )
        return csv_path, json_path


def _executive_payload(report: CompleteSecurityDatasetReport) -> dict[str, Any]:
    return {
        "contract_version": report.contract_version,
        "production_influence": report.production_influence,
        "analysis_window": {
            "start": report.start_date.isoformat(),
            "end": report.end_date.isoformat(),
        },
        "population": _jsonable(asdict(report.population_summary)),
        "evidence": _jsonable(asdict(report.evidence_summary)),
        "membership": _jsonable(asdict(report.membership_summary)),
        "candle_reconciliation": _jsonable(asdict(report.candle_summary)),
        "security_session_continuity": _jsonable(asdict(report.continuity_summary)),
        "ytd_2026": _jsonable(asdict(report.ytd_summary)),
        "certification": _jsonable(asdict(report.certification)),
        "candidate_independent": True,
        "full_benchmark_replays_run": 0,
        "report_sha256": report.report_sha256,
    }


def _executive_markdown(report: CompleteSecurityDatasetReport) -> str:
    p = report.population_summary
    e = report.evidence_summary
    m = report.membership_summary
    c = report.candle_summary
    return f"""# HTR-010A Complete Historical Security Dataset

## Governing Result

- Certification: `{report.certification.primary_state.value}`
- Analysis window: `{report.start_date}` through `{report.end_date}`
- Candidate-independent census: `true`
- Full benchmark replays run: `0`
- Production influence: `false`

## Full-Market Population

- Raw symbols: {p.raw_symbols:,}
- Symbol-series pairs: {p.symbol_series_pairs:,}
- Valid ISINs: {p.isins:,}
- Governed identities: {p.governed_identities:,}
- Provisional identities: {p.provisional_identities:,}
- Unresolved identities: {p.unresolved_identities:,}
- Unsupported security types: {p.unsupported_security_types:,}

## Evidence

- Source families attempted: {e.source_families_attempted:,}
- Sources attempted: {e.sources_attempted:,}
- Acquired: {e.sources_acquired:,}
- Reused: {e.sources_reused:,}
- Failed: {e.sources_failed:,}

## Membership And Tradability

- Membership intervals: {m.membership_intervals:,}
- Tradability intervals: {m.tradability_intervals:,}
- Listing boundaries: {m.listing_boundaries:,}
- Termination boundaries: {m.termination_boundaries:,}
- Suspension intervals: {m.suspension_intervals:,}
- Certified identity-days: {m.certified_identity_days:,}
- Provisional identity-days: {m.provisional_identity_days:,}
- Unresolved identity-days: {m.unresolved_identity_days:,}

## Canonical Candle Reconciliation

- Total rows: {c.total_rows:,}
- Certified rows: {c.certified_rows:,}
- Provisional rows: {c.provisional_rows:,}
- Unresolved rows: {c.unresolved_rows:,}
- Unsupported-series rows: {c.unsupported_series_rows:,}

## Fail-Closed Blockers

{_bullet(item.value for item in report.certification.secondary_blockers)}

The dataset does not use candidate, verdict, setup, gate, or outcome fields for
source acquisition or certification. Unknown official evidence remains unknown.
"""


def _ytd_markdown(report: CompleteSecurityDatasetReport) -> str:
    item = report.ytd_summary
    return f"""# HTR-010A 2026 YTD Treatment

- Calendar state: `{item.calendar_state}`
- Calendar cutoff: `{item.calendar_cutoff or "unavailable"}`
- Canonical cutoff: `{item.canonical_cutoff or "unavailable"}`
- Identity evidence cutoff: `{item.identity_evidence_cutoff or "unavailable"}`
- Final common date: `{item.final_common_date or "unavailable"}`
- Universe size: {item.universe_size:,}
- Governed identities: {item.governed_identities:,}
- Unresolved identities: {item.unresolved_identities:,}
- Final state: `{item.final_state}`
- Blocker: {item.blocker or "None"}
"""


def _certification_markdown(report: CompleteSecurityDatasetReport) -> str:
    item = report.certification
    return f"""# HTR-010A Certification

- Primary state: `{item.primary_state.value}`
- Tier A identities: {item.tier_a_count:,}
- Tier A coverage: {item.tier_a_coverage:.2%}
- Production influence: `false`
- Report SHA-256: `{report.report_sha256}`

## Tier A Requirements

{_bullet(item.tier_a_thresholds)}

## Secondary Blockers

{_bullet(value.value for value in item.secondary_blockers)}

{item.rationale}
"""


def _bullet(values: Iterable[str]) -> str:
    items = tuple(values)
    return "\n".join(f"- `{item}`" for item in items) if items else "- None"


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, (date, StrEnum)):
        return value.isoformat() if isinstance(value, date) else value.value
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


__all__ = ["CompleteSecurityDatasetArtifactExporter"]
