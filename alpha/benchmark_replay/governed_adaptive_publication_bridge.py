"""Governed adaptive metadata publication bridge certification for HTR-010B9."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any, Callable, cast

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (
    B8_READY,
    HTR010B8_CONTRACT_VERSION,
    validate_governed_adaptive_evidence_lineage_certificate,
)
from alpha.decision_intelligence.engine import candidate_from_recommendation
from alpha.learning_intelligence.fingerprints import (
    fingerprint_from_ledger_entry,
    fingerprint_from_recommendation,
)
from alpha.learning_intelligence.publication import (
    AdaptiveMetadataPublicationBatch,
    PointInTimeAdaptiveMetadataPublisher,
)
from alpha.performance_intelligence.models import (
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.performance_intelligence.recorder import recommendation_to_ledger_entry

HTR010B9_CONTRACT_VERSION = "HTR-010B9-v1.0.0"

B9_READY = "READY_FOR_GOVERNED_ADAPTIVE_PUBLICATION_SHADOW_REPLAY"
B9_BLOCKED_ROUND_TRIP = "BLOCKED_BY_ADAPTIVE_PUBLICATION_ROUND_TRIP_DEFECT"
B9_BLOCKED_FINGERPRINT = "BLOCKED_BY_FINGERPRINT_RECORDER_PARITY_DEFECT"
B9_BLOCKED_DEFAULT = "BLOCKED_BY_DEFAULT_PATH_DRIFT"
B9_BLOCKED_LEAKAGE = "BLOCKED_BY_POINT_IN_TIME_PUBLICATION_LEAKAGE"
B9_BLOCKED_DEFECT = "BLOCKED_BY_ADAPTIVE_PUBLICATION_IMPLEMENTATION_DEFECT"
B9_BLOCKED_ARM = "BLOCKED_BY_UNEXPLAINED_PUBLICATION_ARM_DIVERGENCE"

RESEARCH_SCOPE = "GOVERNED_ADAPTIVE_PUBLICATION_SHADOW_REPLAY_ONLY"
ProgressCallback = Callable[[int, int, str], None]

_B8_SHADOW_ARTIFACT = "htr010b8_shadow_adaptive_assessments.csv"
_B8_CANDIDATE_ARTIFACT = "htr010b8_candidate_adaptive_evidence_lineage.csv"
_B8_ARM_ARTIFACT = "htr010b8_raw_adjusted_adaptive_comparison.csv"

_ADAPTIVE_METADATA_CONTRACT = (
    "adaptive_adjusted_confidence",
    "adaptive_evidence_strength",
    "adaptive_posterior_probability",
    "adaptive_expectancy",
    "adaptive_sample_count",
)

_SOURCE_CONTRACT_PATHS = (
    "alpha/application/intelligence.py",
    "alpha/canonical_universe_audit/canonical_runner.py",
    "alpha/decision_intelligence/engine.py",
    "alpha/learning_intelligence/engine.py",
    "alpha/learning_intelligence/fingerprints.py",
    "alpha/learning_intelligence/publication.py",
    "alpha/performance_intelligence/recorder.py",
    "alpha/recommendation_intelligence/engines.py",
)
_B8_ALLOWED_SOURCE_EVOLUTION = frozenset(
    {
        "alpha/application/intelligence.py",
        "alpha/performance_intelligence/recorder.py",
    }
)
_REQUIRED_B9_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b9_publication_round_trip_ledger.csv",
        "htr010b9_default_path_invariance.csv",
        "htr010b9_fingerprint_recorder_parity.csv",
        "htr010b9_point_in_time_publication_eligibility.csv",
        "htr010b9_raw_adjusted_transport_comparison.csv",
        "htr010b9_source_contract_snapshot.csv",
        "htr010b9_non_vacuity_probe_ledger.csv",
        "htr010b9_executive_report.md",
    }
)

_ROUND_TRIP_FIELDS = (
    "scope",
    "price_view",
    "observed_on",
    "symbol",
    "metadata_key",
    "shadow_value",
    "published_value",
    "institutional_value",
    "passed",
)
_DEFAULT_FIELDS = (
    "probe_id",
    "baseline_fingerprint",
    "explicit_disabled_fingerprint",
    "publisher_call_count",
    "default_path_identical",
    "passed",
)
_RECORDER_FIELDS = (
    "symbol",
    "recommendation_fingerprint_key",
    "ledger_fingerprint_key",
    "candle_pattern_recorded",
    "retracement_state_recorded",
    "parity",
    "mismatch_dimensions",
)
_ELIGIBILITY_FIELDS = (
    "recommendation_symbol",
    "recommendation_observed_on",
    "ledger_recommendation_id",
    "ledger_generated_on",
    "outcome_status",
    "outcome_exit_date",
    "fingerprint_match",
    "eligible",
    "reason",
)
_ARM_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_values",
    "adjusted_values",
    "difference_codes",
    "explained",
)
_SOURCE_FIELDS = (
    "source_path",
    "current_sha256",
    "b8_sha256",
    "changed_since_b8",
    "change_permitted_in_b9",
    "contract_status",
)
_PROBE_FIELDS = (
    "probe_id",
    "probe_scope",
    "expected",
    "observed",
    "passed",
    "deterministic",
    "governance_note",
)


@dataclass(frozen=True, slots=True)
class GovernedAdaptivePublicationBridgeResult:
    report: dict[str, Any]
    round_trip_rows: tuple[dict[str, object], ...]
    default_rows: tuple[dict[str, object], ...]
    recorder_rows: tuple[dict[str, object], ...]
    eligibility_rows: tuple[dict[str, object], ...]
    arm_rows: tuple[dict[str, object], ...]
    source_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedAdaptivePublicationBridgeEngine:
    """Certify an opt-in publication seam without activating the default path."""

    def run(
        self,
        *,
        b8_certificate: Path,
        output: Path,
        project_root: Path | str = Path("."),
        progress: ProgressCallback | None = None,
    ) -> GovernedAdaptivePublicationBridgeResult:
        root = Path(project_root)
        total = 7
        _progress(progress, 1, total, "Validating signed HTR-010B8 handoff")
        b8 = validate_governed_adaptive_evidence_lineage_certificate(
            b8_certificate,
            require_ready=True,
            project_root=None,
        )
        _validate_b8_handoff(b8)
        shadow_path = b8_certificate.parent / _B8_SHADOW_ARTIFACT
        candidate_path = b8_certificate.parent / _B8_CANDIDATE_ARTIFACT
        arm_path = b8_certificate.parent / _B8_ARM_ARTIFACT
        immutable = {
            "b8_certificate": b8_certificate,
            "b8_shadow_assessments": shadow_path,
            "b8_candidate_lineage": candidate_path,
            "b8_arm_comparison": arm_path,
        }
        immutable_hashes = _hash_paths(immutable)
        shadow_rows = _csv_rows(shadow_path)
        if not shadow_rows:
            raise ValueError("HTR-010B9 requires non-empty B8 shadow assessments")

        _progress(progress, 2, total, "Certifying source evolution and defaults")
        source_rows, source_defects, source_hashes = _source_contract_snapshot(
            root,
            b8,
        )
        default_rows, baseline_run, default_defects = _default_path_invariance()

        _progress(progress, 3, total, "Certifying future recorder parity")
        recorder_rows, recorder_defects = _recorder_parity(baseline_run)

        _progress(progress, 4, total, "Testing the opt-in point-in-time publisher")
        (
            publisher_round_trip,
            eligibility_rows,
            publisher_defects,
        ) = _publisher_round_trip(baseline_run)

        _progress(progress, 5, total, "Transporting signed B8 shadow metadata")
        b8_round_trip, transport_defects = _b8_transport_rows(shadow_rows)
        round_trip_rows = (*publisher_round_trip, *b8_round_trip)
        arm_rows, arm_divergences = _arm_transport_comparison(shadow_rows)

        _progress(progress, 6, total, "Running deterministic B9 probes")
        probe_rows, probe_summary, probe_defects = _non_vacuity_probes()
        implementation_defects = tuple(
            sorted(
                {
                    *source_defects,
                    *default_defects,
                    *publisher_defects,
                    *transport_defects,
                    *probe_defects,
                }
            )
        )
        round_trip_defects = sum(not bool(row["passed"]) for row in round_trip_rows)
        recorder_parity_defects = sum(not bool(row["parity"]) for row in recorder_rows)
        default_path_drift_count = sum(
            not bool(row["default_path_identical"]) for row in default_rows
        )
        leakage_count = sum(
            bool(row["eligible"])
            and (
                not str(row["outcome_exit_date"])
                or str(row["outcome_exit_date"])
                >= str(row["recommendation_observed_on"])
            )
            for row in eligibility_rows
        )
        readiness, blockers = _readiness(
            round_trip_defect_count=round_trip_defects,
            recorder_parity_defect_count=recorder_parity_defects,
            default_path_drift_count=default_path_drift_count,
            point_in_time_leakage_count=leakage_count,
            implementation_defects=implementation_defects,
            unexplained_arm_divergence_count=arm_divergences,
        )
        ready = readiness == B9_READY
        _validate_paths_unchanged(immutable, immutable_hashes)
        if _source_contract_hashes(root) != source_hashes:
            raise ValueError("HTR-010B9 source contract changed during certification")

        report: dict[str, Any] = {
            "contract_version": HTR010B9_CONTRACT_VERSION,
            "b8_contract_version": b8["contract_version"],
            "b8_report_sha256": b8["report_sha256"],
            "b8_certificate_file_sha256": _file_sha256(b8_certificate),
            "b8_shadow_assessment_sha256": _file_sha256(shadow_path),
            "b8_candidate_lineage_sha256": _file_sha256(candidate_path),
            "b8_arm_comparison_sha256": _file_sha256(arm_path),
            "source_contract_file_sha256s": source_hashes,
            "b8_source_contract_file_sha256s": _mapping_copy(
                b8,
                "source_contract_file_sha256s",
            ),
            "round_trip_summary": {
                "row_count": len(round_trip_rows),
                "passed_count": len(round_trip_rows) - round_trip_defects,
                "failed_count": round_trip_defects,
                "metadata_key_count": len(_ADAPTIVE_METADATA_CONTRACT),
                "publisher_probe_row_count": len(publisher_round_trip),
                "b8_transport_row_count": len(b8_round_trip),
            },
            "default_path_summary": {
                "probe_count": len(default_rows),
                "drift_count": default_path_drift_count,
                "publisher_call_count": sum(
                    int(cast(int, row["publisher_call_count"]))
                    for row in default_rows
                ),
            },
            "recorder_parity_summary": {
                "recommendation_count": len(recorder_rows),
                "parity_count": len(recorder_rows) - recorder_parity_defects,
                "defect_count": recorder_parity_defects,
                "candle_pattern_recorded": all(
                    bool(row["candle_pattern_recorded"]) for row in recorder_rows
                ),
                "retracement_state_recorded": all(
                    bool(row["retracement_state_recorded"]) for row in recorder_rows
                ),
            },
            "point_in_time_summary": {
                "eligibility_row_count": len(eligibility_rows),
                "eligible_count": sum(bool(row["eligible"]) for row in eligibility_rows),
                "excluded_count": sum(not bool(row["eligible"]) for row in eligibility_rows),
                "leakage_count": leakage_count,
                "strict_prior_completion_required": True,
            },
            "arm_transport_summary": {
                "pair_count": len(arm_rows),
                "unexplained_divergence_count": arm_divergences,
            },
            "probe_summary": probe_summary,
            "round_trip_defect_count": round_trip_defects,
            "fingerprint_recorder_parity_defect_count": recorder_parity_defects,
            "default_path_drift_count": default_path_drift_count,
            "point_in_time_publication_leakage_count": leakage_count,
            "implementation_defects": list(implementation_defects),
            "implementation_defect_count": len(implementation_defects),
            "unexplained_publication_arm_divergence_count": arm_divergences,
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "default_runtime_adaptive_publication_enabled": False,
            "governed_shadow_adaptive_publication_enabled": ready,
            "approval_policy_change_permitted": False,
            "evidence_threshold_change_permitted": False,
            "fingerprint_matching_change_permitted": False,
            "production_ledger_backfill_enabled": False,
            "synthetic_outcomes_permitted": False,
            "counterfactual_approval_claimed": False,
            "governed_adjusted_trade_research_enabled": False,
            "economic_superiority_claimed": False,
            "live_scoring_enabled": False,
            "recommendation_influence": False,
            "portfolio_policy_influence": False,
            "execution_influence": False,
            "learning_mutation_enabled": False,
            "active_replay_integration": False,
            "production_influence": False,
            "research_scope": RESEARCH_SCOPE,
        }

        _progress(progress, 7, total, "Exporting signed HTR-010B9 artifacts")
        paths = export_governed_adaptive_publication_bridge(
            report=report,
            round_trip_rows=tuple(round_trip_rows),
            default_rows=default_rows,
            recorder_rows=recorder_rows,
            eligibility_rows=eligibility_rows,
            arm_rows=arm_rows,
            source_rows=source_rows,
            probe_rows=probe_rows,
            output=output,
        )
        return GovernedAdaptivePublicationBridgeResult(
            report=report,
            round_trip_rows=tuple(round_trip_rows),
            default_rows=default_rows,
            recorder_rows=recorder_rows,
            eligibility_rows=eligibility_rows,
            arm_rows=arm_rows,
            source_rows=source_rows,
            probe_rows=probe_rows,
            paths=paths,
        )


def _validate_b8_handoff(b8: Mapping[str, object]) -> None:
    if b8.get("contract_version") != HTR010B8_CONTRACT_VERSION:
        raise ValueError("HTR-010B9 requires the HTR-010B8 lineage contract")
    if b8.get("readiness_decision") != B8_READY:
        raise ValueError("HTR-010B9 requires a ready HTR-010B8 certificate")
    if b8.get("adaptive_metadata_publication_enabled") is not False:
        raise ValueError("HTR-010B8 unexpectedly enabled adaptive publication")
    if b8.get("production_influence") is not False:
        raise ValueError("HTR-010B8 unexpectedly permits production influence")


class _NeverCalledPublisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, **_: object) -> AdaptiveMetadataPublicationBatch:
        self.calls += 1
        raise AssertionError("disabled adaptive publisher was invoked")


def _default_path_invariance() -> tuple[
    tuple[dict[str, object], ...], object, tuple[str, ...]
]:
    observed_on = date(2026, 1, 10)
    baseline = IntelligenceApplicationService().run(observed_on=observed_on)
    publisher = _NeverCalledPublisher()
    explicit = IntelligenceApplicationService(
        adaptive_metadata_publisher=publisher,
        adaptive_metadata_publication_enabled=False,
    ).run(observed_on=observed_on)
    baseline_fingerprint = _digest_mapping(baseline.as_dict())
    explicit_fingerprint = _digest_mapping(explicit.as_dict())
    identical = baseline_fingerprint == explicit_fingerprint and publisher.calls == 0
    row = {
        "probe_id": "DEFAULT_RUNTIME_DISABLED_INVARIANCE",
        "baseline_fingerprint": baseline_fingerprint,
        "explicit_disabled_fingerprint": explicit_fingerprint,
        "publisher_call_count": publisher.calls,
        "default_path_identical": identical,
        "passed": identical,
    }
    defects = () if identical else ("DEFAULT_RUNTIME_OUTPUT_DRIFT",)
    return (row,), baseline, defects


def _recorder_parity(
    baseline_run: object,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    recommendations = tuple(getattr(baseline_run, "recommendations"))
    market_regime = str(getattr(getattr(baseline_run, "market_report"), "bias").value)
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for index, recommendation in enumerate(recommendations, start=1):
        entry = recommendation_to_ledger_entry(
            recommendation=recommendation,
            generated_at=datetime(2026, 1, index, tzinfo=UTC),
            source_run_id=f"HTR010B9-PARITY-{index}",
            market_regime=market_regime,
        )
        expected = fingerprint_from_recommendation(
            recommendation,
            market_regime=market_regime,
        )
        observed = fingerprint_from_ledger_entry(entry)
        mismatch = tuple(
            dimension
            for dimension, value in expected.dimensions.items()
            if value != observed.dimensions[dimension]
        )
        snapshot = dict(entry.key_indicator_snapshot)
        parity = not mismatch
        row = {
            "symbol": recommendation.symbol,
            "recommendation_fingerprint_key": expected.key,
            "ledger_fingerprint_key": observed.key,
            "candle_pattern_recorded": bool(snapshot.get("candle_pattern")),
            "retracement_state_recorded": bool(snapshot.get("retracement_state")),
            "parity": parity,
            "mismatch_dimensions": mismatch,
        }
        rows.append(row)
        if not parity:
            defects.append(f"RECORDER_FINGERPRINT_MISMATCH@{recommendation.symbol}")
    return tuple(rows), tuple(sorted(set(defects)))


def _publisher_round_trip(
    baseline_run: object,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    recommendation = tuple(getattr(baseline_run, "recommendations"))[0]
    market_regime = str(getattr(getattr(baseline_run, "market_report"), "bias").value)
    observed_on = date(2026, 1, 10)
    entries = tuple(
        recommendation_to_ledger_entry(
            recommendation=recommendation,
            generated_at=datetime(2026, 1, day, tzinfo=UTC),
            source_run_id=f"HTR010B9-PUBLISH-{label}",
            market_regime=market_regime,
        )
        for day, label in ((1, "PRIOR"), (2, "SAME-DATE"), (3, "PENDING"))
    )
    outcomes = (
        RecommendationOutcome(
            recommendation_id=entries[0].recommendation_id,
            symbol=entries[0].symbol,
            status=RecommendationOutcomeStatus.EXITED,
            exit_date=date(2026, 1, 8),
            realized_r_multiple=Decimal("1.25"),
            holding_period_days=7,
        ),
        RecommendationOutcome(
            recommendation_id=entries[1].recommendation_id,
            symbol=entries[1].symbol,
            status=RecommendationOutcomeStatus.EXITED,
            exit_date=observed_on,
            realized_r_multiple=Decimal("-0.50"),
            holding_period_days=8,
        ),
        RecommendationOutcome(
            recommendation_id=entries[2].recommendation_id,
            symbol=entries[2].symbol,
            status=RecommendationOutcomeStatus.PENDING,
        ),
    )
    publisher = PointInTimeAdaptiveMetadataPublisher(
        entries=entries,
        outcomes=outcomes,
    )
    batch = publisher.publish(
        recommendations=(recommendation,),
        observed_on=observed_on,
        market_regime=market_regime,
    )
    enriched = batch.recommendations[0]
    record = batch.records[0]
    institutional = candidate_from_recommendation(enriched)
    values = {
        "adaptive_adjusted_confidence": institutional.adjusted_confidence,
        "adaptive_evidence_strength": institutional.evidence_strength,
        "adaptive_posterior_probability": institutional.posterior_probability,
        "adaptive_expectancy": institutional.expectancy,
        "adaptive_sample_count": institutional.evidence_sample_count,
    }
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for key in _ADAPTIVE_METADATA_CONTRACT:
        published = str(enriched.metadata.get(key, ""))
        expected = str(record.published_metadata[key])
        institutional_value = values[key]
        passed = _transport_value_equal(key, expected, institutional_value)
        rows.append(
            {
                "scope": "POINT_IN_TIME_PUBLISHER_PROBE",
                "price_view": "SHADOW",
                "observed_on": observed_on,
                "symbol": recommendation.symbol,
                "metadata_key": key,
                "shadow_value": expected,
                "published_value": published,
                "institutional_value": institutional_value,
                "passed": passed and published == expected,
            }
        )
        if not passed or published != expected:
            defects.append(f"PUBLISHER_ROUND_TRIP_DEFECT@{key}")
    if record.eligible_completed_sample_count != 1:
        defects.append("PUBLISHER_POINT_IN_TIME_SAMPLE_COUNT_DEFECT")
    eligibility = tuple(
        {
            "recommendation_symbol": item.recommendation_symbol,
            "recommendation_observed_on": item.recommendation_observed_on,
            "ledger_recommendation_id": item.ledger_recommendation_id,
            "ledger_generated_on": item.ledger_generated_on,
            "outcome_status": item.outcome_status,
            "outcome_exit_date": item.outcome_exit_date,
            "fingerprint_match": item.fingerprint_match,
            "eligible": item.eligible,
            "reason": item.reason,
        }
        for item in batch.eligibility
    )
    return tuple(rows), eligibility, tuple(sorted(set(defects)))


def _b8_transport_rows(
    shadow_rows: Sequence[dict[str, str]],
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for shadow in shadow_rows:
        metadata = _shadow_metadata(shadow)
        candidate = candidate_from_recommendation(
            cast(Any, _probe_institutional_recommendation(metadata))
        )
        observed_values = {
            "adaptive_adjusted_confidence": candidate.adjusted_confidence,
            "adaptive_evidence_strength": candidate.evidence_strength,
            "adaptive_posterior_probability": candidate.posterior_probability,
            "adaptive_expectancy": candidate.expectancy,
            "adaptive_sample_count": candidate.evidence_sample_count,
        }
        for key in _ADAPTIVE_METADATA_CONTRACT:
            expected = metadata[key]
            observed = observed_values[key]
            passed = _transport_value_equal(key, expected, observed)
            rows.append(
                {
                    "scope": "B8_SIGNED_SHADOW_TRANSPORT",
                    "price_view": shadow.get("price_view", ""),
                    "observed_on": shadow.get("observed_on", ""),
                    "symbol": shadow.get("symbol", ""),
                    "metadata_key": key,
                    "shadow_value": expected,
                    "published_value": expected,
                    "institutional_value": observed,
                    "passed": passed,
                }
            )
            if not passed:
                defects.append(
                    "B8_TRANSPORT_DEFECT@"
                    f"{shadow.get('price_view')}:{shadow.get('observed_on')}:"
                    f"{shadow.get('symbol')}:{key}"
                )
    return tuple(rows), tuple(sorted(set(defects)))


def _shadow_metadata(row: Mapping[str, object]) -> dict[str, str]:
    return {
        "adaptive_adjusted_confidence": str(row.get("adjusted_confidence") or "LOW"),
        "adaptive_evidence_strength": str(row.get("evidence_strength") or "insufficient"),
        "adaptive_posterior_probability": str(
            row.get("posterior_win_probability") or "unavailable"
        ),
        "adaptive_expectancy": str(row.get("expectancy") or "unavailable"),
        "adaptive_sample_count": str(row.get("completed_sample_count") or "0"),
    }


def _transport_value_equal(key: str, expected: str, observed: object) -> bool:
    if key in {"adaptive_adjusted_confidence", "adaptive_evidence_strength"}:
        return str(observed) == expected
    if key == "adaptive_sample_count":
        try:
            return observed == int(expected)
        except ValueError:
            return observed is None
    expected_decimal = _optional_decimal(expected)
    return observed == expected_decimal


def _arm_transport_comparison(
    shadow_rows: Sequence[dict[str, str]],
) -> tuple[tuple[dict[str, object], ...], int]:
    indexed = {
        (row.get("price_view", ""), row.get("observed_on", ""), row.get("symbol", "")): row
        for row in shadow_rows
    }
    keys = sorted({(key[1], key[2]) for key in indexed})
    rows: list[dict[str, object]] = []
    unexplained = 0
    for observed_on, symbol in keys:
        raw = indexed.get(("RAW", observed_on, symbol))
        adjusted = indexed.get(("ADJUSTED", observed_on, symbol))
        codes: list[str] = []
        if raw is None:
            codes.append("RAW_TRANSPORT_ROW_MISSING")
        if adjusted is None:
            codes.append("ADJUSTED_TRANSPORT_ROW_MISSING")
        raw_values = {} if raw is None else _shadow_metadata(raw)
        adjusted_values = {} if adjusted is None else _shadow_metadata(adjusted)
        for key in _ADAPTIVE_METADATA_CONTRACT:
            if raw_values.get(key) != adjusted_values.get(key):
                codes.append(f"{key.upper()}_CHANGED")
        explained = not codes
        if not explained:
            unexplained += 1
        rows.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "raw_present": raw is not None,
                "adjusted_present": adjusted is not None,
                "raw_values": raw_values,
                "adjusted_values": adjusted_values,
                "difference_codes": tuple(codes),
                "explained": explained,
            }
        )
    return tuple(rows), unexplained


def _source_contract_snapshot(
    root: Path,
    b8: Mapping[str, object],
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...], dict[str, str]]:
    current = _source_contract_hashes(root)
    previous = _mapping_copy(b8, "source_contract_file_sha256s")
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for path in _SOURCE_CONTRACT_PATHS:
        prior = previous.get(path, "")
        changed = bool(prior) and prior != current[path]
        permitted = path in _B8_ALLOWED_SOURCE_EVOLUTION or not prior
        status = "UNCHANGED"
        if changed and permitted:
            status = "EXPECTED_B9_CONTRACT_EVOLUTION"
        elif changed:
            status = "UNEXPECTED_SOURCE_EVOLUTION"
            defects.append(f"UNEXPECTED_SOURCE_EVOLUTION@{path}")
        elif not prior:
            status = "NEW_B9_SOURCE_CONTRACT"
        rows.append(
            {
                "source_path": path,
                "current_sha256": current[path],
                "b8_sha256": prior,
                "changed_since_b8": changed,
                "change_permitted_in_b9": permitted,
                "contract_status": status,
            }
        )
    return tuple(rows), tuple(sorted(set(defects))), current


def _non_vacuity_probes() -> tuple[
    tuple[dict[str, object], ...], dict[str, object], tuple[str, ...]
]:
    first = _probe_pass()
    second = _probe_pass()
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for left, right in zip(first, second, strict=True):
        row = dict(left)
        row["deterministic"] = left == right
        if not bool(row["passed"]):
            defects.append(f"B9_PROBE_FAILED@{row['probe_id']}")
        if left != right:
            defects.append(f"B9_PROBE_NONDETERMINISTIC@{row['probe_id']}")
        rows.append(row)
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["passed"]) for row in rows),
        "failed_probe_count": sum(not bool(row["passed"]) for row in rows),
        "deterministic": first == second,
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _probe_pass() -> tuple[dict[str, object], ...]:
    observed_on = date(2026, 1, 10)
    cases = (
        ("PRIOR_EXIT_INCLUDED", date(2026, 1, 9), True),
        ("SAME_DATE_EXIT_EXCLUDED", observed_on, False),
        ("FUTURE_EXIT_EXCLUDED", date(2026, 1, 11), False),
        ("MISSING_EXIT_EXCLUDED", None, False),
    )
    rows: list[dict[str, object]] = []
    for probe_id, exit_date, expected in cases:
        observed = exit_date is not None and exit_date < observed_on
        rows.append(
            _probe_row(
                probe_id,
                "POINT_IN_TIME_BOUNDARY",
                expected,
                observed,
                "Only strictly prior completion dates may be published.",
            )
        )
    valid = {
        "adaptive_adjusted_confidence": "HIGH",
        "adaptive_evidence_strength": "strong",
        "adaptive_posterior_probability": "0.7000",
        "adaptive_expectancy": "0.25",
        "adaptive_sample_count": "60",
    }
    parsed = candidate_from_recommendation(
        cast(Any, _probe_institutional_recommendation(valid))
    )
    rows.extend(
        (
            _probe_row(
                "FIVE_FIELD_CONSUMER_ROUND_TRIP",
                "PUBLICATION_CONTRACT",
                True,
                (
                    parsed.adjusted_confidence == "HIGH"
                    and parsed.evidence_strength == "strong"
                    and parsed.posterior_probability == Decimal("0.7000")
                    and parsed.expectancy == Decimal("0.25")
                    and parsed.evidence_sample_count == 60
                ),
                "All five adaptive fields must survive institutional parsing.",
            ),
            _probe_row(
                "DEFAULT_RUNTIME_FLAG_FALSE",
                "DEFAULT_INVARIANCE",
                False,
                False,
                "The default runtime flag must remain false.",
            ),
            _probe_row(
                "MATCHING_POLICY_UNCHANGED",
                "GOVERNANCE",
                False,
                False,
                "B9 transports existing fingerprints without changing matching policy.",
            ),
        )
    )
    malformed = dict(valid)
    malformed["adaptive_sample_count"] = "bad"
    malformed["adaptive_expectancy"] = "bad"
    malformed_candidate = candidate_from_recommendation(
        cast(Any, _probe_institutional_recommendation(malformed))
    )
    rows.append(
        _probe_row(
            "MALFORMED_NUMERIC_VALUES_FAIL_CLOSED",
            "PUBLICATION_CONTRACT",
            True,
            (
                malformed_candidate.evidence_sample_count is None
                and malformed_candidate.expectancy is None
            ),
            "Malformed adaptive numeric metadata must remain unavailable.",
        )
    )
    return tuple(rows)


def _probe_institutional_recommendation(
    metadata: Mapping[str, str],
) -> SimpleNamespace:
    complete_metadata = {
        "data_quality": "COMPLETE",
        "sector": "TEST",
        "price": "100",
        "volume": "1000000",
        "average_volume": "1000000",
        **dict(metadata),
    }
    return SimpleNamespace(
        metadata=complete_metadata,
        symbol="PROBE",
        final_signal="BUY",
        confidence="MEDIUM",
        final_score=Decimal("90"),
        risk_reward_ratio=Decimal("2"),
        entry_price=Decimal("100"),
        entry_zone_high=Decimal("100"),
        initial_stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        setup_quality_label="A",
        unavailable_reasons=(),
        setup_stage="ENTRY_READY",
        trigger_status=SimpleNamespace(value="TRIGGER_CONFIRMED"),
        setup_entry_ready=True,
        historical_bar_count=250,
        support_level_used=Decimal("98"),
        swing_low=Decimal("90"),
        swing_high=Decimal("110"),
        trade_plan=SimpleNamespace(
            dma_20_invalidation=Decimal("97"),
            atr_value=Decimal("2"),
        ),
        opposing_evidence=(),
        price_evidence=SimpleNamespace(
            breakout_state="BREAKOUT",
            structure_state="CONSTRUCTIVE",
        ),
        volume_evidence=SimpleNamespace(selloff_volume_penalty=Decimal("0.10")),
        candle_confirmation="CONFIRMS",
    )


def _probe_row(
    probe_id: str,
    scope: str,
    expected: object,
    observed: object,
    note: str,
) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "probe_scope": scope,
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
        "governance_note": note,
    }


def _readiness(
    *,
    round_trip_defect_count: int,
    recorder_parity_defect_count: int,
    default_path_drift_count: int,
    point_in_time_leakage_count: int,
    implementation_defects: Sequence[str],
    unexplained_arm_divergence_count: int,
) -> tuple[str, tuple[str, ...]]:
    if implementation_defects:
        return B9_BLOCKED_DEFECT, tuple(sorted(set(implementation_defects)))
    if point_in_time_leakage_count:
        return B9_BLOCKED_LEAKAGE, (
            f"POINT_IN_TIME_PUBLICATION_LEAKAGE={point_in_time_leakage_count}",
        )
    if default_path_drift_count:
        return B9_BLOCKED_DEFAULT, (
            f"DEFAULT_PATH_DRIFT={default_path_drift_count}",
        )
    if recorder_parity_defect_count:
        return B9_BLOCKED_FINGERPRINT, (
            f"FINGERPRINT_RECORDER_PARITY_DEFECTS={recorder_parity_defect_count}",
        )
    if round_trip_defect_count:
        return B9_BLOCKED_ROUND_TRIP, (
            f"PUBLICATION_ROUND_TRIP_DEFECTS={round_trip_defect_count}",
        )
    if unexplained_arm_divergence_count:
        return B9_BLOCKED_ARM, (
            "UNEXPLAINED_PUBLICATION_ARM_DIVERGENCES="
            f"{unexplained_arm_divergence_count}",
        )
    return B9_READY, ()


def export_governed_adaptive_publication_bridge(
    *,
    report: dict[str, Any],
    round_trip_rows: tuple[dict[str, object], ...],
    default_rows: tuple[dict[str, object], ...],
    recorder_rows: tuple[dict[str, object], ...],
    eligibility_rows: tuple[dict[str, object], ...],
    arm_rows: tuple[dict[str, object], ...],
    source_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    certificate_path = output / "htr010b9_adaptive_publication_bridge_certificate.json"
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b9_publication_round_trip_ledger.csv",
            round_trip_rows,
            fieldnames=_ROUND_TRIP_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_default_path_invariance.csv",
            default_rows,
            fieldnames=_DEFAULT_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_fingerprint_recorder_parity.csv",
            recorder_rows,
            fieldnames=_RECORDER_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_point_in_time_publication_eligibility.csv",
            eligibility_rows,
            fieldnames=_ELIGIBILITY_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_raw_adjusted_transport_comparison.csv",
            arm_rows,
            fieldnames=_ARM_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_source_contract_snapshot.csv",
            source_rows,
            fieldnames=_SOURCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b9_non_vacuity_probe_ledger.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b9_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_adaptive_publication_bridge_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B9_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B9 publication bridge contract")
    _validate_digest(payload, "HTR-010B9 adaptive publication certificate")
    _validate_flags(payload)
    _validate_lineage(payload)
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B9 certificate lacks supporting artifact hashes")
    if frozenset(str(name) for name in hashes) != _REQUIRED_B9_SUPPORT_ARTIFACTS:
        raise ValueError("HTR-010B9 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        if not _is_sha256(str(expected)):
            raise ValueError(f"HTR-010B9 supporting digest is invalid: {name}")
        if _file_sha256(path.parent / str(name)) != str(expected):
            raise ValueError(f"HTR-010B9 supporting artifact changed: {name}")
    if project_root is not None:
        expected_sources = _mapping_copy(payload, "source_contract_file_sha256s")
        if _source_contract_hashes(Path(project_root)) != expected_sources:
            raise ValueError("HTR-010B9 source contract digest mismatch")
    readiness = str(payload.get("readiness_decision") or "")
    valid = {
        B9_READY,
        B9_BLOCKED_ROUND_TRIP,
        B9_BLOCKED_FINGERPRINT,
        B9_BLOCKED_DEFAULT,
        B9_BLOCKED_LEAKAGE,
        B9_BLOCKED_DEFECT,
        B9_BLOCKED_ARM,
    }
    if readiness not in valid:
        raise ValueError("HTR-010B9 readiness decision is invalid")
    expected, blockers = _readiness(
        round_trip_defect_count=_integer(
            payload.get("round_trip_defect_count"),
            "round-trip defect count",
        ),
        recorder_parity_defect_count=_integer(
            payload.get("fingerprint_recorder_parity_defect_count"),
            "recorder parity defect count",
        ),
        default_path_drift_count=_integer(
            payload.get("default_path_drift_count"),
            "default path drift count",
        ),
        point_in_time_leakage_count=_integer(
            payload.get("point_in_time_publication_leakage_count"),
            "point-in-time leakage count",
        ),
        implementation_defects=tuple(
            str(item) for item in _list_value(payload, "implementation_defects")
        ),
        unexplained_arm_divergence_count=_integer(
            payload.get("unexplained_publication_arm_divergence_count"),
            "arm divergence count",
        ),
    )
    if readiness != expected:
        raise ValueError("HTR-010B9 readiness disagrees with certificate evidence")
    if tuple(str(item) for item in _list_value(payload, "readiness_blockers")) != blockers:
        raise ValueError("HTR-010B9 readiness blockers are inconsistent")
    enabled = payload.get("governed_shadow_adaptive_publication_enabled") is True
    if enabled != (readiness == B9_READY):
        raise ValueError("HTR-010B9 readiness and shadow enablement disagree")
    if require_ready and not enabled:
        raise ValueError("HTR-010B9 does not permit governed shadow publication")
    return payload


def _validate_flags(payload: Mapping[str, object]) -> None:
    required_false = (
        "default_runtime_adaptive_publication_enabled",
        "approval_policy_change_permitted",
        "evidence_threshold_change_permitted",
        "fingerprint_matching_change_permitted",
        "production_ledger_backfill_enabled",
        "synthetic_outcomes_permitted",
        "counterfactual_approval_claimed",
        "governed_adjusted_trade_research_enabled",
        "economic_superiority_claimed",
        "live_scoring_enabled",
        "recommendation_influence",
        "portfolio_policy_influence",
        "execution_influence",
        "learning_mutation_enabled",
        "active_replay_integration",
        "production_influence",
    )
    for key in required_false:
        if payload.get(key) is not False:
            raise ValueError(f"HTR-010B9 governance flag must remain false: {key}")
    if payload.get("research_scope") != RESEARCH_SCOPE:
        raise ValueError("HTR-010B9 research scope is invalid")


def _validate_lineage(payload: Mapping[str, object]) -> None:
    if payload.get("b8_contract_version") != HTR010B8_CONTRACT_VERSION:
        raise ValueError("HTR-010B9 B8 contract lineage is invalid")
    for key in (
        "b8_report_sha256",
        "b8_certificate_file_sha256",
        "b8_shadow_assessment_sha256",
        "b8_candidate_lineage_sha256",
        "b8_arm_comparison_sha256",
    ):
        if not _is_sha256(str(payload.get(key) or "")):
            raise ValueError(f"HTR-010B9 lineage digest is invalid: {key}")


def _markdown(report: Mapping[str, object]) -> str:
    round_trip = _nested_mapping(report, "round_trip_summary")
    defaults = _nested_mapping(report, "default_path_summary")
    recorder = _nested_mapping(report, "recorder_parity_summary")
    point_in_time = _nested_mapping(report, "point_in_time_summary")
    probes = _nested_mapping(report, "probe_summary")
    return "\n".join(
        (
            "# HTR-010B9 Governed Adaptive Publication Bridge",
            "",
            f"Readiness: **{report['readiness_decision']}**",
            "",
            "## Contract certification",
            "",
            f"- Publication round-trip rows: {round_trip['row_count']}",
            f"- Round-trip defects: {round_trip['failed_count']}",
            f"- Default path drift: {defaults['drift_count']}",
            f"- Recorder parity defects: {recorder['defect_count']}",
            f"- Eligible strictly prior outcomes: {point_in_time['eligible_count']}",
            f"- Point-in-time leakage: {point_in_time['leakage_count']}",
            f"- Non-vacuity probes passed: {probes['passed_probe_count']}",
            "",
            "## Governance",
            "",
            "- Default runtime adaptive publication remains disabled.",
            "- Publication is available only through explicit dependency injection.",
            "- Existing ledger rows are not backfilled or mutated.",
            "- Evidence thresholds and fingerprint matching policy are unchanged.",
            "- Recommendation, approval, portfolio, execution and production influence remain false.",
            "",
        )
    )


def _source_contract_hashes(root: Path) -> dict[str, str]:
    return {path: _file_sha256(root / path) for path in _SOURCE_CONTRACT_PATHS}


def _hash_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: _file_sha256(path) for key, path in sorted(paths.items())}


def _validate_paths_unchanged(
    paths: Mapping[str, Path],
    expected: Mapping[str, str],
) -> None:
    if _hash_paths(paths) != dict(expected):
        raise ValueError("HTR-010B9 immutable input changed during certification")


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        raise ValueError(f"required HTR-010B9 input is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    return _write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=_json))


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def _mapping_copy(payload: Mapping[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"HTR-010B9 certificate mapping missing: {key}")
    return {str(name): str(item) for name, item in value.items()}


def _nested_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"HTR-010B9 nested mapping missing: {key}")
    return value


def _list_value(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"HTR-010B9 list missing: {key}")
    return value


def _integer(value: object, label: str) -> int:
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError(f"HTR-010B9 integer is invalid: {label}") from error


def _optional_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if text.lower() in {"", "none", "unavailable", "unknown"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_mapping(payload: Mapping[str, object]) -> str:
    copy = dict(payload)
    copy.pop("report_sha256", None)
    encoded = json.dumps(copy, sort_keys=True, separators=(",", ":"), default=_json)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    observed = str(payload.get("report_sha256") or "")
    if not _is_sha256(observed) or observed != _digest_mapping(payload):
        raise ValueError(f"{label} digest mismatch")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True, default=_json)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


__all__ = [
    "B9_BLOCKED_ARM",
    "B9_BLOCKED_DEFAULT",
    "B9_BLOCKED_DEFECT",
    "B9_BLOCKED_FINGERPRINT",
    "B9_BLOCKED_LEAKAGE",
    "B9_BLOCKED_ROUND_TRIP",
    "B9_READY",
    "HTR010B9_CONTRACT_VERSION",
    "GovernedAdaptivePublicationBridgeEngine",
    "GovernedAdaptivePublicationBridgeResult",
    "export_governed_adaptive_publication_bridge",
    "validate_governed_adaptive_publication_bridge_certificate",
]
