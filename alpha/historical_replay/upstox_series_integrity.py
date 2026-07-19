from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UpstoxCoverageClassification,
    UpstoxHistoricalCandidateEvidence,
    UpstoxSeriesDefect,
)

UPSTOX_SERIES_INTEGRITY_VERSION = "upstox-series-integrity-v1"

_PARTIAL_STATUSES = {
    UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE,
    UpstoxCoverageClassification.INSUFFICIENT_LOOKBACK,
}
_NO_HISTORY_STATUSES = {
    UpstoxCoverageClassification.CANDIDATE_WINDOW_MISSING,
    UpstoxCoverageClassification.HISTORICAL_SYMBOL_UNAVAILABLE,
    UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND,
    UpstoxCoverageClassification.IDENTITY_UNRESOLVED,
}


@dataclass(frozen=True, slots=True)
class UpstoxInvalidSeriesAttribution:
    candidate_id: str
    historical_symbol: str
    candidate_date: date
    raw_row_count: int
    pre_cutoff_row_count: int
    normalized_row_count: int
    valid_row_count: int
    required_valid_bars: int
    rejected_row_count: int
    primary_defect: UpstoxSeriesDefect
    secondary_defects: tuple[UpstoxSeriesDefect, ...]
    final_coverage_status: UpstoxCoverageClassification
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class UpstoxSeriesIntegrityReport:
    report_version: str
    observed_candidates: int
    series_observed: int
    candidates_without_series: int
    valid_series: int
    invalid_series: int
    required_valid_bars: int
    candidates_with_required_raw_bars: int
    candidates_with_required_pre_cutoff_bars: int
    candidates_with_required_normalized_bars: int
    candidates_with_required_integrity_valid_bars: int
    full_price_coverage_candidates: int
    partial_history_candidates: int
    no_history_candidates: int
    observed_price_coverage_rate: Decimal | None
    terminal_status_total: int
    terminal_status_distribution: tuple[tuple[str, int], ...]
    defect_distribution: tuple[tuple[str, int], ...]
    year_full_price_coverage: tuple[tuple[int, int, int], ...]
    invalid_attributions: tuple[UpstoxInvalidSeriesAttribution, ...]
    metric_reconciliation_result: str
    definitions: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


class UpstoxSeriesIntegrityEngine:
    def build(
        self,
        records: Sequence[UpstoxHistoricalCandidateEvidence],
    ) -> UpstoxSeriesIntegrityReport:
        observed = tuple(
            sorted(records, key=lambda item: (item.candidate_date, item.candidate_id))
        )
        invalid = tuple(
            item
            for item in observed
            if item.coverage_classification
            is UpstoxCoverageClassification.INVALID_SERIES
        )
        with_series = tuple(item for item in observed if item.raw_bars_returned > 0)
        valid_series = tuple(
            item
            for item in with_series
            if item.coverage_classification
            is not UpstoxCoverageClassification.INVALID_SERIES
        )
        full = tuple(
            item
            for item in observed
            if item.coverage_classification
            is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
        )
        terminal = Counter(item.coverage_classification.value for item in observed)
        attributions = tuple(_invalid_attribution(item) for item in invalid)
        defect_distribution = Counter(
            item.primary_defect.value for item in attributions
        )
        years = tuple(
            (
                year,
                sum(
                    item.coverage_classification
                    is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                    for item in observed
                    if item.replay_year == year
                ),
                sum(item.replay_year == year for item in observed),
            )
            for year in sorted({item.replay_year for item in observed})
        )
        required = max((item.required_valid_bars for item in observed), default=121)
        partial = sum(
            item.coverage_classification in _PARTIAL_STATUSES for item in observed
        )
        no_history = sum(
            item.coverage_classification in _NO_HISTORY_STATUSES for item in observed
        )
        terminal_total = sum(terminal.values())
        reconciled = all(
            (
                terminal_total == len(observed),
                len(full) == sum(item.full_price_coverage for item in observed),
                sum(total for _, _, total in years) == len(observed),
                len(invalid) == len(attributions),
                partial
                == sum(
                    item.coverage_classification in _PARTIAL_STATUSES
                    for item in observed
                ),
                no_history
                == sum(
                    item.coverage_classification in _NO_HISTORY_STATUSES
                    for item in observed
                ),
            )
        )
        return UpstoxSeriesIntegrityReport(
            report_version=UPSTOX_SERIES_INTEGRITY_VERSION,
            observed_candidates=len(observed),
            series_observed=len(with_series),
            candidates_without_series=len(observed) - len(with_series),
            valid_series=len(valid_series),
            invalid_series=len(invalid),
            required_valid_bars=required,
            candidates_with_required_raw_bars=sum(
                item.has_sufficient_raw_lookback for item in observed
            ),
            candidates_with_required_pre_cutoff_bars=sum(
                item.has_sufficient_pre_cutoff_lookback for item in observed
            ),
            candidates_with_required_normalized_bars=sum(
                item.normalized_bars >= item.required_valid_bars for item in observed
            ),
            candidates_with_required_integrity_valid_bars=sum(
                item.has_sufficient_valid_lookback for item in observed
            ),
            full_price_coverage_candidates=len(full),
            partial_history_candidates=partial,
            no_history_candidates=no_history,
            observed_price_coverage_rate=_ratio(len(full), len(observed)),
            terminal_status_total=terminal_total,
            terminal_status_distribution=tuple(sorted(terminal.items())),
            defect_distribution=tuple(sorted(defect_distribution.items())),
            year_full_price_coverage=years,
            invalid_attributions=attributions,
            metric_reconciliation_result=("RECONCILED" if reconciled else "MISMATCH"),
            definitions=(
                "Raw bars are all provider rows, including malformed rows.",
                "Pre-cutoff bars are parseable rows at or before the required "
                "end and strictly before the candidate date.",
                "Normalized bars are sorted pre-cutoff rows before integrity "
                "rejection and session de-duplication.",
                "Integrity-valid bars have valid positive OHLC, non-negative "
                "volume, India timezone, permitted session, and unique date.",
                "Full price coverage requires sufficient integrity-valid depth "
                "and no mandatory series defect.",
                "Partial history includes only PARTIAL_PRICE_COVERAGE and "
                "INSUFFICIENT_LOOKBACK; invalid series are excluded.",
                "No history includes identity/window statuses with no usable "
                "candidate history; invalid series are excluded.",
            ),
        )


def filter_upstox_series_records(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
    *,
    candidate_id: str | None = None,
    symbol: str | None = None,
    year: int | None = None,
    limit: int | None = None,
) -> tuple[UpstoxHistoricalCandidateEvidence, ...]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive")
    normalized_symbol = symbol.strip().upper() if symbol else None
    selected = tuple(
        item
        for item in sorted(
            records, key=lambda row: (row.candidate_date, row.candidate_id)
        )
        if candidate_id is None or item.candidate_id == candidate_id
        if normalized_symbol is None
        or item.requested_historical_symbol == normalized_symbol
        if year is None or item.replay_year == year
    )
    if candidate_id is not None and not selected:
        raise ValueError(f"candidate id not found: {candidate_id}")
    return selected[:limit] if limit is not None else selected


def render_upstox_series_integrity(
    report: UpstoxSeriesIntegrityReport,
) -> tuple[str, ...]:
    return (
        "Upstox Historical Series Integrity",
        f"Observed Candidates: {report.observed_candidates}",
        f"Series Observed: {report.series_observed}",
        f"Candidates Without Series: {report.candidates_without_series}",
        f"Valid Series: {report.valid_series}",
        f"Invalid Series: {report.invalid_series}",
        "Defect Distribution: " + _pairs(report.defect_distribution),
        "Bar-Count Reconciliation:",
        f"- Required Valid Bars: {report.required_valid_bars}",
        "- Candidates with Required Raw Bars: "
        f"{report.candidates_with_required_raw_bars}",
        "- Candidates with Required Pre-Cutoff Bars: "
        f"{report.candidates_with_required_pre_cutoff_bars}",
        "- Candidates with Required Normalized Bars: "
        f"{report.candidates_with_required_normalized_bars}",
        "- Candidates with Required Integrity-Valid Bars: "
        f"{report.candidates_with_required_integrity_valid_bars}",
        f"- Full Price Coverage Candidates: {report.full_price_coverage_candidates}",
        "- Observed Price-Coverage Rate: "
        f"{_percent(report.observed_price_coverage_rate)}",
        "Terminal Coverage Statuses: " + _pairs(report.terminal_status_distribution),
        "Partial / No History (invalid excluded): "
        f"{report.partial_history_candidates} / {report.no_history_candidates}",
        "Year Full Price Coverage: "
        + ", ".join(
            f"{year}={covered}/{total}"
            for year, covered, total in report.year_full_price_coverage
        ),
        "Invalid-Series Attribution:",
        *(_attribution_line(item) for item in report.invalid_attributions),
        "Metric Reconciliation Result: "
        f"{report.metric_reconciliation_result} "
        f"({report.terminal_status_total}/{report.observed_candidates} terminal)",
        "Definitions:",
        *(f"- {item}" for item in report.definitions),
        "PRODUCTION_INFLUENCE=false",
    )


def export_upstox_series_integrity_csv(
    report: UpstoxSeriesIntegrityReport,
    path: Path | str,
) -> None:
    fields = (
        "candidate_id",
        "historical_symbol",
        "candidate_date",
        "raw_row_count",
        "pre_cutoff_row_count",
        "normalized_row_count",
        "valid_row_count",
        "required_valid_bars",
        "rejected_row_count",
        "primary_defect",
        "secondary_defects",
        "final_coverage_status",
        "production_influence",
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in report.invalid_attributions:
            row = asdict(item)
            row["candidate_date"] = item.candidate_date.isoformat()
            row["primary_defect"] = item.primary_defect.value
            row["secondary_defects"] = ";".join(
                value.value for value in item.secondary_defects
            )
            row["final_coverage_status"] = item.final_coverage_status.value
            writer.writerow(row)


def _invalid_attribution(
    item: UpstoxHistoricalCandidateEvidence,
) -> UpstoxInvalidSeriesAttribution:
    primary = item.primary_series_defect or UpstoxSeriesDefect.UNKNOWN_SERIES_DEFECT
    return UpstoxInvalidSeriesAttribution(
        candidate_id=item.candidate_id,
        historical_symbol=item.requested_historical_symbol,
        candidate_date=item.candidate_date,
        raw_row_count=item.raw_bars_returned,
        pre_cutoff_row_count=item.pre_cutoff_bars,
        normalized_row_count=item.normalized_bars,
        valid_row_count=item.integrity_valid_bars,
        required_valid_bars=item.required_valid_bars,
        rejected_row_count=item.rejected_bars,
        primary_defect=primary,
        secondary_defects=item.secondary_series_defects,
        final_coverage_status=item.coverage_classification,
    )


def _attribution_line(item: UpstoxInvalidSeriesAttribution) -> str:
    secondary = ",".join(value.value for value in item.secondary_defects) or "none"
    return (
        f"- {item.candidate_id} {item.historical_symbol} {item.candidate_date}: "
        f"raw={item.raw_row_count}; pre_cutoff={item.pre_cutoff_row_count}; "
        f"normalized={item.normalized_row_count}; valid={item.valid_row_count}; "
        f"rejected={item.rejected_row_count}; primary={item.primary_defect.value}; "
        f"secondary={secondary}; final={item.final_coverage_status.value}"
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * 100).quantize(Decimal('0.01'))}%"


def _pairs(values: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) or "none"


__all__ = [
    "UPSTOX_SERIES_INTEGRITY_VERSION",
    "UpstoxInvalidSeriesAttribution",
    "UpstoxSeriesIntegrityEngine",
    "UpstoxSeriesIntegrityReport",
    "export_upstox_series_integrity_csv",
    "filter_upstox_series_records",
    "render_upstox_series_integrity",
]
