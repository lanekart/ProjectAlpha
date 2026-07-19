from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.market_intelligence.point_in_time_store import (
    resolve_point_in_time_store_path,
)
from alpha.version import __version__

REGIME_SHADOW_ENGINE_VERSION = "regime-shadow-engine-v1"
DEFAULT_REGIME_SHADOW_LEDGER_PATH = Path(".alpha/regime_shadow_ledger.json")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")
_POSITIVE_VERDICTS = {"BUY", "STRONG_BUY"}
_PROHIBITED_ACTION = (
    "Do not activate context-only or bearish-only policy in production, change "
    "regime intervention values, tune regime thresholds, alter regime labels, "
    "modify classifier conditions, change recommendation weights, alter "
    "candidate generation, change verdict thresholds, modify entry timing, "
    "change gates, alter trade plans, change approvals, modify allocation, "
    "ingest sector sources, build diagnostic v3, flip retracement signs, "
    "rewrite historical records or choose a production policy from replay "
    "performance alone."
)


class RegimeShadowPolicyId(StrEnum):
    CONTROL = "CONTROL"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    BEARISH_ONLY = "BEARISH_ONLY"


class RegimeShadowIntegrityStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_LIMITATIONS = "VALID_WITH_LIMITATIONS"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"


class RegimeShadowDecisionStatus(StrEnum):
    READY_FOR_CONTEXT_ONLY_FEATURE_FLAG = "READY_FOR_CONTEXT_ONLY_FEATURE_FLAG"
    READY_FOR_BEARISH_ONLY_FEATURE_FLAG = "READY_FOR_BEARISH_ONLY_FEATURE_FLAG"
    READY_FOR_LONGER_SHADOW_OBSERVATION = "READY_FOR_LONGER_SHADOW_OBSERVATION"
    NOT_READY_FOR_POLICY_CHANGE = "NOT_READY_FOR_POLICY_CHANGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RegimeShadowNextMilestone(StrEnum):
    CONTINUE_LIVE_REGIME_SHADOW_COLLECTION = "CONTINUE_LIVE_REGIME_SHADOW_COLLECTION"
    IMPLEMENT_CONTEXT_ONLY_FEATURE_FLAG = "IMPLEMENT_CONTEXT_ONLY_FEATURE_FLAG"
    IMPLEMENT_BEARISH_ONLY_FEATURE_FLAG = "IMPLEMENT_BEARISH_ONLY_FEATURE_FLAG"
    AUDIT_BEARISH_DEMOTION_POLICY = "AUDIT_BEARISH_DEMOTION_POLICY"
    AUDIT_BULLISH_PROMOTION_POLICY = "AUDIT_BULLISH_PROMOTION_POLICY"
    RETAIN_CURRENT_REGIME_POLICY = "RETAIN_CURRENT_REGIME_POLICY"
    MATERIALIZE_BENCHMARK_FIELDS_IN_DIAGNOSTIC_STORE = (
        "MATERIALIZE_BENCHMARK_FIELDS_IN_DIAGNOSTIC_STORE"
    )
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )


class RegimeShadowConclusion(StrEnum):
    FULL_REGIME_INTERVENTION_ADDS_STABLE_VALUE = (
        "FULL_REGIME_INTERVENTION_ADDS_STABLE_VALUE"
    )
    FULL_REGIME_INTERVENTION_ADDS_LIMITED_VALUE = (
        "FULL_REGIME_INTERVENTION_ADDS_LIMITED_VALUE"
    )
    CONTEXT_ONLY_MATCHES_OR_IMPROVES_CONTROL = (
        "CONTEXT_ONLY_MATCHES_OR_IMPROVES_CONTROL"
    )
    CONTEXT_ONLY_REINTRODUCES_EXCESS_DOWNSIDE = (
        "CONTEXT_ONLY_REINTRODUCES_EXCESS_DOWNSIDE"
    )
    BEARISH_ONLY_PRESERVES_DOWNSIDE_PROTECTION = (
        "BEARISH_ONLY_PRESERVES_DOWNSIDE_PROTECTION"
    )
    BEARISH_ONLY_OUTPERFORMS_FULL_INTERVENTION = (
        "BEARISH_ONLY_OUTPERFORMS_FULL_INTERVENTION"
    )
    BULLISH_PROMOTIONS_ADD_VALUE = "BULLISH_PROMOTIONS_ADD_VALUE"
    BULLISH_PROMOTIONS_ADD_FALSE_POSITIVES = "BULLISH_PROMOTIONS_ADD_FALSE_POSITIVES"
    REGIME_SHADOW_POLICIES_ARE_ECONOMICALLY_SIMILAR = (
        "REGIME_SHADOW_POLICIES_ARE_ECONOMICALLY_SIMILAR"
    )
    SHADOW_EVIDENCE_IS_TEMPORALLY_UNSTABLE = "SHADOW_EVIDENCE_IS_TEMPORALLY_UNSTABLE"
    INSUFFICIENT_EVIDENCE_FOR_POLICY_CHANGE = "INSUFFICIENT_EVIDENCE_FOR_POLICY_CHANGE"


class RegimeShadowMatrixStatus(StrEnum):
    CONTROL_REMAINS_PREFERRED = "CONTROL_REMAINS_PREFERRED"
    CONTEXT_ONLY_IS_PREFERRED_FOR_RESEARCH = "CONTEXT_ONLY_IS_PREFERRED_FOR_RESEARCH"
    BEARISH_ONLY_IS_PREFERRED_FOR_RESEARCH = "BEARISH_ONLY_IS_PREFERRED_FOR_RESEARCH"
    ALL_POLICIES_SIMILAR = "ALL_POLICIES_SIMILAR"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RegimeShadowFinding(StrEnum):
    BULLISH_PROMOTIONS_ADD_VALUE = "BULLISH_PROMOTIONS_ADD_VALUE"
    BULLISH_PROMOTIONS_ADD_LIMITED_VALUE = "BULLISH_PROMOTIONS_ADD_LIMITED_VALUE"
    BULLISH_PROMOTIONS_ADD_FALSE_POSITIVES = "BULLISH_PROMOTIONS_ADD_FALSE_POSITIVES"
    BULLISH_PROMOTIONS_HAVE_NO_MATERIAL_EFFECT = (
        "BULLISH_PROMOTIONS_HAVE_NO_MATERIAL_EFFECT"
    )
    INSUFFICIENT_BULLISH_PROMOTION_SAMPLE = "INSUFFICIENT_BULLISH_PROMOTION_SAMPLE"


@dataclass(frozen=True, slots=True)
class RegimeShadowPolicyVersion:
    policy_id: RegimeShadowPolicyId
    policy_version: str
    policy_fingerprint: str
    regime_classifier_version: str
    regime_classifier_fingerprint: str
    recommendation_policy_version: str
    verdict_policy_version: str
    approval_policy_version: str
    allocation_policy_version: str
    intervention_configuration_fingerprint: str
    created_at: datetime
    code_version: str

    @property
    def policy_key(self) -> str:
        return f"{self.policy_id.value}:{self.policy_version}"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy_id"] = self.policy_id.value
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class RegimeShadowDecision:
    shadow_decision_id: str
    authoritative_candidate_id: str
    decision_timestamp: datetime
    symbol: str
    policy_id: RegimeShadowPolicyId
    policy_version: str
    policy_fingerprint: str
    setup_type: str | None
    recorded_regime: str | None
    regime_source: str
    regime_quality: str
    regime_snapshot_id: str | None
    base_score: Decimal
    regime_adjustment: Decimal
    shadow_score: Decimal
    authoritative_score: Decimal
    shadow_verdict: str
    authoritative_verdict: str
    shadow_approval_eligible: bool
    authoritative_approval_eligible: bool
    shadow_allocation_eligible: bool
    authoritative_allocation_eligible: bool
    score_difference: Decimal
    rank_difference: int
    verdict_difference: bool
    approval_difference: bool
    allocation_difference: bool
    difference_reasons: tuple[str, ...]
    source_fingerprint: str
    authoritative: bool
    executable: bool
    capital_effect: str
    authoritative_provenance_id: str | None
    shadow_engine_version: str
    shadow_configuration_fingerprint: str
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy_id"] = self.policy_id.value
        for field in (
            "base_score",
            "regime_adjustment",
            "shadow_score",
            "authoritative_score",
            "score_difference",
        ):
            payload[field] = str(payload[field])
        payload["decision_timestamp"] = self.decision_timestamp.isoformat()
        payload["created_at"] = self.created_at.isoformat()
        payload["difference_reasons"] = list(self.difference_reasons)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegimeShadowDecision:
        return cls(
            shadow_decision_id=str(payload["shadow_decision_id"]),
            authoritative_candidate_id=str(payload["authoritative_candidate_id"]),
            decision_timestamp=datetime.fromisoformat(
                str(payload["decision_timestamp"])
            ),
            symbol=str(payload["symbol"]),
            policy_id=RegimeShadowPolicyId(str(payload["policy_id"])),
            policy_version=str(payload["policy_version"]),
            policy_fingerprint=str(payload["policy_fingerprint"]),
            setup_type=_optional_text(payload.get("setup_type")),
            recorded_regime=_optional_text(payload.get("recorded_regime")),
            regime_source=str(payload["regime_source"]),
            regime_quality=str(payload["regime_quality"]),
            regime_snapshot_id=_optional_text(payload.get("regime_snapshot_id")),
            base_score=Decimal(str(payload["base_score"])),
            regime_adjustment=Decimal(str(payload["regime_adjustment"])),
            shadow_score=Decimal(str(payload["shadow_score"])),
            authoritative_score=Decimal(str(payload["authoritative_score"])),
            shadow_verdict=str(payload["shadow_verdict"]),
            authoritative_verdict=str(payload["authoritative_verdict"]),
            shadow_approval_eligible=bool(payload["shadow_approval_eligible"]),
            authoritative_approval_eligible=bool(
                payload["authoritative_approval_eligible"]
            ),
            shadow_allocation_eligible=bool(payload["shadow_allocation_eligible"]),
            authoritative_allocation_eligible=bool(
                payload["authoritative_allocation_eligible"]
            ),
            score_difference=Decimal(str(payload["score_difference"])),
            rank_difference=int(payload["rank_difference"]),
            verdict_difference=bool(payload["verdict_difference"]),
            approval_difference=bool(payload["approval_difference"]),
            allocation_difference=bool(payload["allocation_difference"]),
            difference_reasons=tuple(
                str(item) for item in payload.get("difference_reasons", ())
            ),
            source_fingerprint=str(payload["source_fingerprint"]),
            authoritative=bool(payload["authoritative"]),
            executable=bool(payload["executable"]),
            capital_effect=str(payload["capital_effect"]),
            authoritative_provenance_id=_optional_text(
                payload.get("authoritative_provenance_id")
            ),
            shadow_engine_version=str(payload["shadow_engine_version"]),
            shadow_configuration_fingerprint=str(
                payload["shadow_configuration_fingerprint"]
            ),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True, slots=True)
class RegimeShadowRun:
    run_id: str
    policy_versions: tuple[RegimeShadowPolicyVersion, ...]
    source_dataset_fingerprint: str
    candidate_count: int
    date_start: date | None
    date_end: date | None
    started_at: datetime
    completed_at: datetime
    integrity_status: RegimeShadowIntegrityStatus
    persisted: bool
    decision_count: int
    failure_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "policy_versions": [policy.as_dict() for policy in self.policy_versions],
            "source_dataset_fingerprint": self.source_dataset_fingerprint,
            "candidate_count": self.candidate_count,
            "date_start": None
            if self.date_start is None
            else self.date_start.isoformat(),
            "date_end": None if self.date_end is None else self.date_end.isoformat(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "integrity_status": self.integrity_status.value,
            "persisted": self.persisted,
            "decision_count": self.decision_count,
            "failure_count": self.failure_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegimeShadowRun:
        return cls(
            run_id=str(payload["run_id"]),
            policy_versions=tuple(
                _policy_from_dict(item)
                for item in payload.get("policy_versions", ())
                if isinstance(item, dict)
            ),
            source_dataset_fingerprint=str(payload["source_dataset_fingerprint"]),
            candidate_count=int(payload["candidate_count"]),
            date_start=(
                None
                if payload.get("date_start") is None
                else date.fromisoformat(str(payload["date_start"]))
            ),
            date_end=(
                None
                if payload.get("date_end") is None
                else date.fromisoformat(str(payload["date_end"]))
            ),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            completed_at=datetime.fromisoformat(str(payload["completed_at"])),
            integrity_status=RegimeShadowIntegrityStatus(
                str(payload["integrity_status"])
            ),
            persisted=bool(payload["persisted"]),
            decision_count=int(payload["decision_count"]),
            failure_count=int(payload["failure_count"]),
        )


@dataclass(frozen=True, slots=True)
class RegimeShadowFailure:
    policy_id: RegimeShadowPolicyId
    candidate_id: str
    exception_category: str
    source_fingerprint: str
    timestamp: datetime
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id.value,
            "candidate_id": self.candidate_id,
            "exception_category": self.exception_category,
            "source_fingerprint": self.source_fingerprint,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class RegimeShadowBuildResult:
    run: RegimeShadowRun
    decisions: tuple[RegimeShadowDecision, ...]
    failures: tuple[RegimeShadowFailure, ...]
    inserted_decisions: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class RegimeShadowStatusReport:
    repository_path: Path
    stored_runs: int
    stored_decisions: int
    stored_failures: int
    latest_run_id: str | None
    latest_integrity_status: RegimeShadowIntegrityStatus | None
    policies: tuple[RegimeShadowPolicyVersion, ...]


@dataclass(frozen=True, slots=True)
class RegimeShadowIntegrityReport:
    status: RegimeShadowIntegrityStatus
    candidate_count: int
    control_records: int
    context_only_records: int
    bearish_only_records: int
    duplicate_records: int
    orphan_records: int
    missing_policy_fingerprint: int
    missing_source_fingerprint: int
    authoritative_mutation_count: int
    failure_count: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeShadowScoreComparison:
    policy_id: RegimeShadowPolicyId
    candidate_count: int
    mean_score: Decimal | None
    median_score: Decimal | None
    mean_difference_vs_control: Decimal | None
    median_difference_vs_control: Decimal | None
    maximum_difference: Decimal | None
    minimum_difference: Decimal | None
    unchanged_scores: int
    changed_scores: int
    removed_bullish_adjustment: int
    removed_bearish_adjustment: int
    removed_neutral_adjustment: int
    retained_bearish_adjustment: int
    rank_changes: int
    mean_rank_displacement: Decimal | None
    median_rank_displacement: Decimal | None
    top_decile_membership_changes: int
    top_quartile_membership_changes: int


@dataclass(frozen=True, slots=True)
class RegimeShadowVerdictComparison:
    policy_id: RegimeShadowPolicyId
    transition: str
    transition_cause: str
    transition_count: int
    distinct_dates: int
    setup_distribution: tuple[tuple[str, int], ...]
    regime_distribution: tuple[tuple[str, int], ...]
    completed_outcomes: int


@dataclass(frozen=True, slots=True)
class RegimeShadowApprovalComparison:
    policy_id: RegimeShadowPolicyId
    approval_eligibility_changes: int
    strict_approval_changes: int
    raw_approval_changes: int
    mean_approval_margin_change: Decimal | None
    allocation_eligibility_changes: int
    target_weight_changes: int
    capital_action_changes: int


@dataclass(frozen=True, slots=True)
class RegimeShadowOutcomeComparison:
    policy_id: RegimeShadowPolicyId
    weighting: str
    candidate_count: int
    completed_outcomes: int
    auc: Decimal | None
    spearman_rank_correlation: Decimal | None
    top_decile_win_rate: Decimal | None
    bottom_decile_win_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    average_buy_return: Decimal | None
    median_buy_return: Decimal | None
    benchmark_relative_buy_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    promoted_winners: int
    promoted_losers: int
    demoted_winners: int
    demoted_losers: int


@dataclass(frozen=True, slots=True)
class RegimeShadowProtectionReport:
    bearish_demotions_removed: int
    demoted_winners_restored: int
    demoted_losers_restored: int
    bearish_demotions_preserved: int
    downside_avoided: Decimal | None
    downside_reintroduced: Decimal | None
    missed_upside: Decimal | None
    net_downside_protection_value: Decimal | None
    false_demotion_rate: Decimal | None
    true_protection_rate: Decimal | None
    average_mae_avoided: Decimal | None
    average_return_sacrificed: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeShadowBullishPromotionReport:
    bullish_promotions_under_control: int
    promoted_winners: int
    promoted_losers: int
    promotion_precision: Decimal | None
    average_promoted_return: Decimal | None
    benchmark_relative_promoted_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    finding: RegimeShadowFinding


@dataclass(frozen=True, slots=True)
class RegimeShadowSetupAttribution:
    setup_family: str
    policy_id: RegimeShadowPolicyId
    candidate_count: int
    verdict_changes: int
    auc: Decimal | None
    buy_precision: Decimal | None
    average_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    downside_avoided: Decimal | None
    missed_upside: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeShadowQualityReport:
    slice_name: str
    policy_id: RegimeShadowPolicyId
    candidate_count: int
    average_return: Decimal | None
    verdict_changes: int
    classification: str


@dataclass(frozen=True, slots=True)
class RegimeShadowTemporalReport:
    period: str
    policy_id: RegimeShadowPolicyId
    candidate_count: int
    date_count: int
    auc: Decimal | None
    buy_precision: Decimal | None
    average_return: Decimal | None
    downside_avoided: Decimal | None
    missed_upside: Decimal | None
    finding: str


@dataclass(frozen=True, slots=True)
class RegimeShadowReadinessReport:
    integrity_status: RegimeShadowIntegrityStatus
    decision_matrix: tuple[tuple[str, RegimeShadowMatrixStatus, str], ...]
    primary_conclusion: RegimeShadowConclusion
    secondary_conclusion: RegimeShadowConclusion | None
    readiness_status: RegimeShadowDecisionStatus
    recommended_next_milestone: RegimeShadowNextMilestone
    explicitly_prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class _Outcome:
    forward_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool
    stop_hit: bool
    quality: str


class RegimeShadowRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_regime_shadow_ledger_path(path)

    def load_runs(self) -> tuple[RegimeShadowRun, ...]:
        runs = self._read().get("runs", [])
        return tuple(
            RegimeShadowRun.from_dict(item) for item in runs if isinstance(item, dict)
        )

    def load_decisions(self) -> tuple[RegimeShadowDecision, ...]:
        rows = self._read().get("decisions", [])
        return tuple(
            sorted(
                (
                    RegimeShadowDecision.from_dict(item)
                    for item in rows
                    if isinstance(item, dict)
                ),
                key=lambda row: (
                    row.authoritative_candidate_id,
                    row.policy_id.value,
                    row.policy_version,
                ),
            )
        )

    def load_failures(self) -> tuple[RegimeShadowFailure, ...]:
        rows = self._read().get("failures", [])
        return tuple(
            RegimeShadowFailure(
                policy_id=RegimeShadowPolicyId(str(item["policy_id"])),
                candidate_id=str(item["candidate_id"]),
                exception_category=str(item["exception_category"]),
                source_fingerprint=str(item["source_fingerprint"]),
                timestamp=datetime.fromisoformat(str(item["timestamp"])),
                message=str(item["message"]),
            )
            for item in rows
            if isinstance(item, dict)
        )

    def save_result(self, result: RegimeShadowBuildResult) -> int:
        existing = {
            (
                row.authoritative_candidate_id,
                row.policy_id.value,
                row.policy_version,
                row.source_fingerprint,
            ): row
            for row in self.load_decisions()
        }
        inserted = 0
        for decision in result.decisions:
            key = (
                decision.authoritative_candidate_id,
                decision.policy_id.value,
                decision.policy_version,
                decision.source_fingerprint,
            )
            existed = key in existing
            if existed and (
                existing[key].policy_fingerprint == decision.policy_fingerprint
                and existing[key].shadow_engine_version
                == decision.shadow_engine_version
                and existing[key].shadow_configuration_fingerprint
                == decision.shadow_configuration_fingerprint
            ):
                continue
            existing[key] = decision
            if not existed:
                inserted += 1
        runs = tuple(
            {run.run_id: run for run in (*self.load_runs(), result.run)}.values()
        )
        failures = (*self.load_failures(), *result.failures)
        self._write(
            runs=runs,
            decisions=tuple(existing.values()),
            failures=failures,
        )
        return inserted

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": [], "decisions": [], "failures": []}
        payload = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        if isinstance(payload, dict):
            return payload
        return {"runs": [], "decisions": [], "failures": []}

    def _write(
        self,
        *,
        runs: tuple[RegimeShadowRun, ...],
        decisions: tuple[RegimeShadowDecision, ...],
        failures: tuple[RegimeShadowFailure, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs": [run.as_dict() for run in runs],
            "decisions": [decision.as_dict() for decision in decisions],
            "failures": [failure.as_dict() for failure in failures],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class RegimeShadowEngine:
    def __init__(
        self,
        *,
        learning_ledger_path: Path | str | None = None,
        shadow_ledger_path: Path | str | None = None,
        store_path: Path | str | None = None,
    ) -> None:
        self.learning = LearningLedgerRepository(learning_ledger_path)
        self.shadow = RegimeShadowRepository(shadow_ledger_path)
        self.store_path = resolve_point_in_time_store_path(store_path)

    def policies(self) -> tuple[RegimeShadowPolicyVersion, ...]:
        created = datetime(2026, 1, 1, tzinfo=UTC)
        return tuple(
            _policy(
                policy_id=policy_id,
                config=config,
                created=created,
                source_fingerprint=self.source_fingerprint(),
            )
            for policy_id, config in (
                (
                    RegimeShadowPolicyId.CONTROL,
                    "production-regime-adjustment-current",
                ),
                (
                    RegimeShadowPolicyId.CONTEXT_ONLY,
                    "zero-all-regime-score-and-decision-influence",
                ),
                (
                    RegimeShadowPolicyId.BEARISH_ONLY,
                    "retain-current-bearish-regime-adjustment-only",
                ),
            )
        )

    def build(self, *, persist: bool = False) -> RegimeShadowBuildResult:
        started = datetime.now(UTC)
        source = self.source_fingerprint()
        records = self.learning.load_records()
        outcomes = {
            outcome.candidate_id: _outcome_from(_primary_window(outcome))
            for outcome in self.learning.load_outcomes()
        }
        v2 = self._v2_quality()
        policies = self.policies()
        failures: list[RegimeShadowFailure] = []
        decisions: list[RegimeShadowDecision] = []
        for record in records:
            try:
                decisions.extend(
                    self._decisions_for(
                        record=record,
                        outcome=outcomes.get(record.candidate_id),
                        regime_quality=v2.get(record.candidate_id, "UNKNOWN"),
                        policies=policies,
                        source_fingerprint=source,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive isolation
                failures.append(
                    RegimeShadowFailure(
                        policy_id=RegimeShadowPolicyId.CONTROL,
                        candidate_id=record.candidate_id,
                        exception_category=exc.__class__.__name__,
                        source_fingerprint=source,
                        timestamp=datetime.now(UTC),
                        message=str(exc),
                    )
                )
        ranked = _with_rank_differences(tuple(decisions))
        completed = datetime.now(UTC)
        run = RegimeShadowRun(
            run_id=_run_id(source, records, policies),
            policy_versions=policies,
            source_dataset_fingerprint=source,
            candidate_count=len(records),
            date_start=min(
                (record.evaluation_date for record in records), default=None
            ),
            date_end=max((record.evaluation_date for record in records), default=None),
            started_at=started,
            completed_at=completed,
            integrity_status=(
                RegimeShadowIntegrityStatus.VALID
                if not failures and len(ranked) == len(records) * 3
                else RegimeShadowIntegrityStatus.VALID_WITH_LIMITATIONS
            ),
            persisted=persist,
            decision_count=len(ranked),
            failure_count=len(failures),
        )
        result = RegimeShadowBuildResult(
            run=run,
            decisions=ranked,
            failures=tuple(failures),
            inserted_decisions=0,
            dry_run=not persist,
        )
        if persist:
            inserted = self.shadow.save_result(result)
            result = RegimeShadowBuildResult(
                run=run,
                decisions=ranked,
                failures=tuple(failures),
                inserted_decisions=inserted,
                dry_run=False,
            )
        return result

    def status(self) -> RegimeShadowStatusReport:
        runs = self.shadow.load_runs()
        latest = runs[-1] if runs else None
        return RegimeShadowStatusReport(
            repository_path=self.shadow.path,
            stored_runs=len(runs),
            stored_decisions=len(self.shadow.load_decisions()),
            stored_failures=len(self.shadow.load_failures()),
            latest_run_id=None if latest is None else latest.run_id,
            latest_integrity_status=None if latest is None else latest.integrity_status,
            policies=self.policies(),
        )

    def integrity(self) -> RegimeShadowIntegrityReport:
        decisions = self._decisions()
        records = self.learning.load_records()
        ids = {record.candidate_id for record in records}
        keys = [
            (
                decision.authoritative_candidate_id,
                decision.policy_id.value,
                decision.policy_version,
                decision.source_fingerprint,
            )
            for decision in decisions
        ]
        duplicates = len(keys) - len(set(keys))
        by_policy = Counter(decision.policy_id for decision in decisions)
        orphan = sum(
            decision.authoritative_candidate_id not in ids for decision in decisions
        )
        missing_policy = sum(not decision.policy_fingerprint for decision in decisions)
        missing_source = sum(not decision.source_fingerprint for decision in decisions)
        mutation_count = sum(
            decision.authoritative
            or decision.executable
            or decision.capital_effect != "none"
            for decision in decisions
        )
        issues: list[str] = []
        if duplicates:
            issues.append("duplicate shadow records")
        if orphan:
            issues.append("orphan shadow records")
        for policy in RegimeShadowPolicyId:
            if by_policy[policy] not in {0, len(records)}:
                issues.append(f"incomplete {policy.value} records")
        if missing_policy:
            issues.append("missing policy fingerprint")
        if missing_source:
            issues.append("missing source fingerprint")
        if mutation_count:
            issues.append("shadow row marked authoritative/executable")
        status = (
            RegimeShadowIntegrityStatus.VALID
            if decisions
            and not issues
            and all(
                by_policy[policy] == len(records) for policy in RegimeShadowPolicyId
            )
            else RegimeShadowIntegrityStatus.INCOMPLETE
            if not decisions
            else RegimeShadowIntegrityStatus.INVALID
        )
        return RegimeShadowIntegrityReport(
            status=status,
            candidate_count=len(records),
            control_records=by_policy[RegimeShadowPolicyId.CONTROL],
            context_only_records=by_policy[RegimeShadowPolicyId.CONTEXT_ONLY],
            bearish_only_records=by_policy[RegimeShadowPolicyId.BEARISH_ONLY],
            duplicate_records=duplicates,
            orphan_records=orphan,
            missing_policy_fingerprint=missing_policy,
            missing_source_fingerprint=missing_source,
            authoritative_mutation_count=mutation_count,
            failure_count=len(self.shadow.load_failures()),
            issues=tuple(issues),
        )

    def score_comparison(self) -> tuple[RegimeShadowScoreComparison, ...]:
        decisions = self._decisions()
        control = _by_candidate(decisions, RegimeShadowPolicyId.CONTROL)
        output: list[RegimeShadowScoreComparison] = []
        for policy in RegimeShadowPolicyId:
            rows = tuple(row for row in decisions if row.policy_id is policy)
            output.append(_score_comparison(policy, rows, control))
        return tuple(output)

    def verdict_comparison(self) -> tuple[RegimeShadowVerdictComparison, ...]:
        decisions = self._decisions()
        outcomes = self._outcomes()
        output: list[RegimeShadowVerdictComparison] = []
        for policy in (
            RegimeShadowPolicyId.CONTEXT_ONLY,
            RegimeShadowPolicyId.BEARISH_ONLY,
        ):
            groups: dict[tuple[str, str], list[RegimeShadowDecision]] = defaultdict(
                list
            )
            for row in decisions:
                if row.policy_id is not policy:
                    continue
                transition = f"{row.authoritative_verdict} -> {row.shadow_verdict}"
                groups[(transition, _transition_cause(row))].append(row)
            output.extend(
                _verdict_row(policy, transition, cause, tuple(rows), outcomes)
                for (transition, cause), rows in sorted(groups.items())
            )
        return tuple(output)

    def approval_comparison(self) -> tuple[RegimeShadowApprovalComparison, ...]:
        return tuple(
            _approval_comparison(policy, self._policy_decisions(policy))
            for policy in RegimeShadowPolicyId
        )

    def allocation_comparison(self) -> tuple[RegimeShadowApprovalComparison, ...]:
        return self.approval_comparison()

    def outcomes(
        self,
        *,
        date_weighted: bool = False,
    ) -> tuple[RegimeShadowOutcomeComparison, ...]:
        outcomes = self._outcomes()
        rows: list[RegimeShadowOutcomeComparison] = []
        for policy in RegimeShadowPolicyId:
            policy_rows = self._policy_decisions(policy)
            rows.append(
                _outcome_comparison(policy, policy_rows, outcomes, date_weighted)
            )
        return tuple(rows)

    def bearish_protection(self) -> RegimeShadowProtectionReport:
        outcomes = self._outcomes()
        context = self._policy_decisions(RegimeShadowPolicyId.CONTEXT_ONLY)
        bearish = self._policy_decisions(RegimeShadowPolicyId.BEARISH_ONLY)
        context_removed = tuple(
            row
            for row in context
            if row.authoritative_verdict != row.shadow_verdict
            and row.score_difference > 0
            and (row.recorded_regime or "").strip().upper()
            in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}
        )
        preserved = tuple(
            row
            for row in bearish
            if row.regime_adjustment < 0
            and row.authoritative_verdict == row.shadow_verdict
        )
        restored_winners = tuple(
            row for row in context_removed if _winner(row, outcomes)
        )
        restored_losers = tuple(row for row in context_removed if _loser(row, outcomes))
        downside = [
            abs(forward_return)
            for row in restored_losers
            if (outcome := outcomes.get(row.authoritative_candidate_id)) is not None
            if (forward_return := outcome.forward_return) is not None
        ]
        upside = [
            forward_return
            for row in restored_winners
            if (outcome := outcomes.get(row.authoritative_candidate_id)) is not None
            if (forward_return := outcome.forward_return) is not None
        ]
        mae = [
            abs(adverse)
            for row in restored_losers
            if (outcome := outcomes.get(row.authoritative_candidate_id)) is not None
            if (adverse := outcome.mae) is not None
        ]
        return RegimeShadowProtectionReport(
            bearish_demotions_removed=len(context_removed),
            demoted_winners_restored=len(restored_winners),
            demoted_losers_restored=len(restored_losers),
            bearish_demotions_preserved=len(preserved),
            downside_avoided=_average(downside),
            downside_reintroduced=_average(downside),
            missed_upside=_average(upside),
            net_downside_protection_value=_net(_average(downside), _average(upside)),
            false_demotion_rate=_ratio(len(restored_winners), len(context_removed)),
            true_protection_rate=_ratio(len(restored_losers), len(context_removed)),
            average_mae_avoided=_average(mae),
            average_return_sacrificed=_average(upside),
        )

    def bullish_promotion(self) -> RegimeShadowBullishPromotionReport:
        outcomes = self._outcomes()
        bearish = self._policy_decisions(RegimeShadowPolicyId.BEARISH_ONLY)
        removed = tuple(
            row
            for row in bearish
            if row.score_difference < 0
            and row.authoritative_verdict != row.shadow_verdict
        )
        winners = tuple(row for row in removed if _winner(row, outcomes))
        losers = tuple(row for row in removed if _loser(row, outcomes))
        returns = [
            outcomes[row.authoritative_candidate_id].forward_return
            for row in removed
            if row.authoritative_candidate_id in outcomes
            and outcomes[row.authoritative_candidate_id].forward_return is not None
        ]
        mfe = [
            outcomes[row.authoritative_candidate_id].mfe
            for row in removed
            if row.authoritative_candidate_id in outcomes
            and outcomes[row.authoritative_candidate_id].mfe is not None
        ]
        mae = [
            outcomes[row.authoritative_candidate_id].mae
            for row in removed
            if row.authoritative_candidate_id in outcomes
            and outcomes[row.authoritative_candidate_id].mae is not None
        ]
        precision = _ratio(len(winners), len(removed))
        finding = (
            RegimeShadowFinding.INSUFFICIENT_BULLISH_PROMOTION_SAMPLE
            if len(removed) < 20
            else RegimeShadowFinding.BULLISH_PROMOTIONS_ADD_VALUE
            if precision is not None and precision >= Decimal("0.55")
            else RegimeShadowFinding.BULLISH_PROMOTIONS_ADD_FALSE_POSITIVES
        )
        return RegimeShadowBullishPromotionReport(
            bullish_promotions_under_control=len(removed),
            promoted_winners=len(winners),
            promoted_losers=len(losers),
            promotion_precision=precision,
            average_promoted_return=_average(returns),
            benchmark_relative_promoted_return=None,
            mfe=_average(mfe),
            mae=_average(mae),
            finding=finding,
        )

    def setup_attribution(self) -> tuple[RegimeShadowSetupAttribution, ...]:
        outcomes = self._outcomes()
        output: list[RegimeShadowSetupAttribution] = []
        for policy in RegimeShadowPolicyId:
            grouped: dict[str, list[RegimeShadowDecision]] = defaultdict(list)
            for row in self._policy_decisions(policy):
                grouped[_setup_family(row)].append(row)
            output.extend(
                _setup_row(policy, setup, tuple(rows), outcomes)
                for setup, rows in sorted(grouped.items())
            )
        return tuple(output)

    def quality(self) -> tuple[RegimeShadowQualityReport, ...]:
        outcomes = self._outcomes()
        output: list[RegimeShadowQualityReport] = []
        for slice_name, predicate in (
            ("HIGH", lambda row: row.regime_quality.upper().startswith("HIGH")),
            (
                "HIGH_OR_MEDIUM",
                lambda row: (
                    row.regime_quality.upper().split("_")[0] in {"HIGH", "MEDIUM"}
                ),
            ),
            ("COMPLETE_OR_EXACT", lambda row: row.regime_source != "unavailable"),
        ):
            for policy in RegimeShadowPolicyId:
                rows = tuple(
                    row for row in self._policy_decisions(policy) if predicate(row)
                )
                returns = [
                    outcomes[row.authoritative_candidate_id].forward_return
                    for row in rows
                    if row.authoritative_candidate_id in outcomes
                    and outcomes[row.authoritative_candidate_id].forward_return
                    is not None
                ]
                output.append(
                    RegimeShadowQualityReport(
                        slice_name=slice_name,
                        policy_id=policy,
                        candidate_count=len(rows),
                        average_return=_average(returns),
                        verdict_changes=sum(row.verdict_difference for row in rows),
                        classification=(
                            "INSUFFICIENT_SAMPLE"
                            if len(rows) < 20
                            else "STABLE_ACROSS_QUALITY"
                        ),
                    )
                )
        return tuple(output)

    def temporal_stability(self) -> tuple[RegimeShadowTemporalReport, ...]:
        decisions = self._decisions()
        dates = sorted({row.decision_timestamp.date() for row in decisions})
        if len(dates) < 3:
            return tuple(
                _temporal_row(
                    "all", policy, self._policy_decisions(policy), self._outcomes()
                )
                for policy in RegimeShadowPolicyId
            )
        one = max(1, len(dates) // 3)
        windows = (
            ("early", set(dates[:one])),
            ("middle", set(dates[one : one * 2])),
            ("recent", set(dates[one * 2 :])),
        )
        output = []
        outcomes = self._outcomes()
        for period, period_dates in windows:
            for policy in RegimeShadowPolicyId:
                rows = tuple(
                    row
                    for row in self._policy_decisions(policy)
                    if row.decision_timestamp.date() in period_dates
                )
                output.append(_temporal_row(period, policy, rows, outcomes))
        return tuple(output)

    def readiness(self) -> RegimeShadowReadinessReport:
        integrity = self.integrity()
        approval = {row.policy_id: row for row in self.approval_comparison()}
        protection = self.bearish_protection()
        no_approval_surprise = all(
            row.approval_eligibility_changes == 0
            and row.allocation_eligibility_changes == 0
            for row in approval.values()
        )
        valid = integrity.status is RegimeShadowIntegrityStatus.VALID
        conclusion = (
            RegimeShadowConclusion.BEARISH_ONLY_PRESERVES_DOWNSIDE_PROTECTION
            if valid
            and no_approval_surprise
            and (protection.true_protection_rate or _ZERO) >= Decimal("0.50")
            else RegimeShadowConclusion.INSUFFICIENT_EVIDENCE_FOR_POLICY_CHANGE
        )
        readiness = (
            RegimeShadowDecisionStatus.READY_FOR_LONGER_SHADOW_OBSERVATION
            if valid and no_approval_surprise
            else RegimeShadowDecisionStatus.NOT_READY_FOR_POLICY_CHANGE
        )
        next_milestone = (
            RegimeShadowNextMilestone.CONTINUE_LIVE_REGIME_SHADOW_COLLECTION
        )
        return RegimeShadowReadinessReport(
            integrity_status=integrity.status,
            decision_matrix=(
                (
                    "ranking value",
                    RegimeShadowMatrixStatus.INSUFFICIENT_EVIDENCE,
                    "replay ranking evidence is not live validation",
                ),
                (
                    "downside protection",
                    RegimeShadowMatrixStatus.BEARISH_ONLY_IS_PREFERRED_FOR_RESEARCH,
                    "bearish-only preserves the negative intervention path",
                ),
                (
                    "approval stability",
                    (
                        RegimeShadowMatrixStatus.ALL_POLICIES_SIMILAR
                        if no_approval_surprise
                        else RegimeShadowMatrixStatus.INSUFFICIENT_EVIDENCE
                    ),
                    "shadow approval is diagnostic-only",
                ),
                (
                    "rollback safety",
                    RegimeShadowMatrixStatus.INSUFFICIENT_EVIDENCE,
                    "production feature flag is not implemented in this milestone",
                ),
            ),
            primary_conclusion=conclusion,
            secondary_conclusion=(
                RegimeShadowConclusion.CONTEXT_ONLY_REINTRODUCES_EXCESS_DOWNSIDE
                if protection.bearish_demotions_removed
                else None
            ),
            readiness_status=readiness,
            recommended_next_milestone=next_milestone,
            explicitly_prohibited_next_action=_PROHIBITED_ACTION,
        )

    def live_shadow_enabled(self) -> bool:
        return os.getenv("ALPHA_REGIME_SHADOW_ENABLED", "false").lower() == "true"

    def source_fingerprint(self) -> str:
        ledger_ids = ",".join(
            record.candidate_id for record in self.learning.load_records()
        )
        v2 = self._v2_fingerprint()
        return _fingerprint(f"{v2}|{ledger_ids}")

    def _decisions_for(
        self,
        *,
        record: CandidateDecisionRecord,
        outcome: _Outcome | None,
        regime_quality: str,
        policies: tuple[RegimeShadowPolicyVersion, ...],
        source_fingerprint: str,
    ) -> tuple[RegimeShadowDecision, ...]:
        del outcome
        recorded_adjustment = _recorded_regime_adjustment(record)
        base_score = _clamp_score(record.strategy_score - recorded_adjustment)
        rows = []
        for policy in policies:
            adjustment = _policy_adjustment(
                policy.policy_id,
                recorded_adjustment,
                record,
            )
            score = _clamp_score(base_score + adjustment)
            verdict = (
                record.final_verdict
                if policy.policy_id is RegimeShadowPolicyId.CONTROL
                else _verdict_from_score(score)
            )
            approved = _shadow_approved(record, score, verdict)
            allocation = approved
            reasons = _difference_reasons(
                score=score,
                verdict=verdict,
                approved=approved,
                allocation=allocation,
                record=record,
                policy=policy.policy_id,
                recorded_adjustment=recorded_adjustment,
            )
            rows.append(
                RegimeShadowDecision(
                    shadow_decision_id=_shadow_id(
                        record.candidate_id,
                        policy.policy_version,
                        source_fingerprint,
                    ),
                    authoritative_candidate_id=record.candidate_id,
                    decision_timestamp=datetime.combine(
                        record.evaluation_date,
                        datetime.min.time(),
                        tzinfo=UTC,
                    ),
                    symbol=record.symbol,
                    policy_id=policy.policy_id,
                    policy_version=policy.policy_version,
                    policy_fingerprint=policy.policy_fingerprint,
                    setup_type=record.setup_type,
                    recorded_regime=record.market_regime,
                    regime_source=(
                        "recorded_candidate_regime"
                        if record.market_regime
                        else "unavailable"
                    ),
                    regime_quality=regime_quality,
                    regime_snapshot_id=record.market_state_snapshot_id,
                    base_score=base_score,
                    regime_adjustment=adjustment,
                    shadow_score=score,
                    authoritative_score=record.strategy_score,
                    shadow_verdict=verdict,
                    authoritative_verdict=record.final_verdict,
                    shadow_approval_eligible=approved,
                    authoritative_approval_eligible=record.approved_for_deployment,
                    shadow_allocation_eligible=allocation,
                    authoritative_allocation_eligible=record.approved_for_deployment,
                    score_difference=(score - record.strategy_score).quantize(_FOUR),
                    rank_difference=0,
                    verdict_difference=verdict != record.final_verdict,
                    approval_difference=approved != record.approved_for_deployment,
                    allocation_difference=allocation != record.approved_for_deployment,
                    difference_reasons=reasons,
                    source_fingerprint=source_fingerprint,
                    authoritative=False,
                    executable=False,
                    capital_effect="none",
                    authoritative_provenance_id=record.decision_provenance_id,
                    shadow_engine_version=REGIME_SHADOW_ENGINE_VERSION,
                    shadow_configuration_fingerprint=_configuration_fingerprint(
                        policies
                    ),
                    created_at=datetime.now(UTC),
                )
            )
        return tuple(rows)

    def _decisions(self) -> tuple[RegimeShadowDecision, ...]:
        decisions = self.shadow.load_decisions()
        if decisions:
            runs = self.shadow.load_runs()
            if runs:
                latest = runs[-1].source_dataset_fingerprint
                filtered = tuple(
                    row for row in decisions if row.source_fingerprint == latest
                )
                if filtered:
                    return filtered
            return decisions
        return self.build(persist=False).decisions

    def _policy_decisions(
        self,
        policy: RegimeShadowPolicyId,
    ) -> tuple[RegimeShadowDecision, ...]:
        return tuple(row for row in self._decisions() if row.policy_id is policy)

    def _outcomes(self) -> dict[str, _Outcome]:
        return {
            outcome.candidate_id: converted
            for outcome in self.learning.load_outcomes()
            if (converted := _outcome_from(_primary_window(outcome))) is not None
        }

    def _v2_quality(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT link.candidate_stable_id, state.diagnostic_quality
                FROM diagnostic_market_state_v2_candidate_links AS link
                LEFT JOIN diagnostic_market_state_v2 AS state
                  ON state.reconstruction_id = link.reconstruction_id
                ORDER BY link.candidate_stable_id
                """
            ).fetchall()
        return {str(row[0]): str(row[1] or "UNKNOWN") for row in rows}

    def _v2_fingerprint(self) -> str:
        if not self.store_path.exists():
            return "unavailable"
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT source_fingerprint
                FROM diagnostic_pit_builds
                ORDER BY imported_at DESC, build_id DESC
                LIMIT 1
                """
            ).fetchone()
        return "unavailable" if row is None else str(row[0])


def resolve_regime_shadow_ledger_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_REGIME_SHADOW_LEDGER")
    return Path(configured) if configured else DEFAULT_REGIME_SHADOW_LEDGER_PATH


def render_regime_shadow_build(result: RegimeShadowBuildResult) -> tuple[str, ...]:
    return (
        "Regime Shadow Build",
        f"Run ID: {result.run.run_id}",
        f"Mode: {'dry-run' if result.dry_run else 'persisted'}",
        f"Source Fingerprint: {result.run.source_dataset_fingerprint}",
        f"Candidate Count: {result.run.candidate_count}",
        f"Decision Count: {result.run.decision_count}",
        f"Inserted Decisions: {result.inserted_decisions}",
        f"Failure Count: {result.run.failure_count}",
        f"Integrity Status: {result.run.integrity_status.value}",
        "Policies: "
        + ", ".join(policy.policy_version for policy in result.run.policy_versions),
        "Authoritative Output Changed: no",
    )


def render_regime_shadow_status(
    report: RegimeShadowStatusReport,
) -> tuple[str, ...]:
    return (
        "Regime Shadow Status",
        f"Repository: {report.repository_path}",
        f"Stored Runs: {report.stored_runs}",
        f"Stored Decisions: {report.stored_decisions}",
        f"Stored Failures: {report.stored_failures}",
        f"Latest Run ID: {_text(report.latest_run_id)}",
        "Latest Integrity Status: "
        + _text(
            report.latest_integrity_status.value
            if report.latest_integrity_status
            else None
        ),
        "Policy Versions: "
        + ", ".join(policy.policy_version for policy in report.policies),
    )


def render_regime_shadow_integrity(
    report: RegimeShadowIntegrityReport,
) -> tuple[str, ...]:
    return (
        "Regime Shadow Integrity",
        f"Status: {report.status.value}",
        f"Candidate Count: {report.candidate_count}",
        f"Control Records: {report.control_records}",
        f"Context-Only Records: {report.context_only_records}",
        f"Bearish-Only Records: {report.bearish_only_records}",
        f"Duplicate Records: {report.duplicate_records}",
        f"Orphan Records: {report.orphan_records}",
        f"Authoritative Mutation Count: {report.authoritative_mutation_count}",
        f"Failure Count: {report.failure_count}",
        "Issues: " + (", ".join(report.issues) if report.issues else "none"),
    )


def render_regime_shadow_score_comparison(
    rows: tuple[RegimeShadowScoreComparison, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Score Comparison"]
    for row in rows:
        lines.append(
            f"- {row.policy_id.value}: n={row.candidate_count}, "
            f"mean={_text(row.mean_score)}, "
            f"diff={_text(row.mean_difference_vs_control)}, "
            f"rank_changes={row.rank_changes}, "
            f"top_decile_changes={row.top_decile_membership_changes}"
        )
    return tuple(lines)


def render_regime_shadow_verdict_comparison(
    rows: tuple[RegimeShadowVerdictComparison, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Verdict Comparison"]
    for row in rows:
        lines.append(
            f"- {row.policy_id.value}/{row.transition}: "
            f"n={row.transition_count}, dates={row.distinct_dates}, "
            f"cause={row.transition_cause}, completed={row.completed_outcomes}"
        )
    return tuple(lines)


def render_regime_shadow_approval_comparison(
    rows: tuple[RegimeShadowApprovalComparison, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Approval/Allocation Comparison"]
    for row in rows:
        lines.append(
            f"- {row.policy_id.value}: approvals={row.approval_eligibility_changes}, "
            f"allocation={row.allocation_eligibility_changes}, "
            f"capital_action={row.capital_action_changes}, "
            f"margin={_text(row.mean_approval_margin_change)}"
        )
    return tuple(lines)


def render_regime_shadow_outcomes(
    rows: tuple[RegimeShadowOutcomeComparison, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Outcomes"]
    for row in rows:
        lines.append(
            f"- {row.policy_id.value}/{row.weighting}: n={row.candidate_count}, "
            f"completed={row.completed_outcomes}, auc={_text(row.auc)}, "
            f"top_win={_text(row.top_decile_win_rate)}, "
            f"buy_precision={_text(row.buy_precision_proxy)}, "
            f"avg_buy={_text(row.average_buy_return)}"
        )
    return tuple(lines)


def render_regime_shadow_bearish_protection(
    report: RegimeShadowProtectionReport,
) -> tuple[str, ...]:
    return (
        "Regime Shadow Bearish Protection",
        f"Bearish Demotions Removed: {report.bearish_demotions_removed}",
        f"Demoted Winners Restored: {report.demoted_winners_restored}",
        f"Demoted Losers Restored: {report.demoted_losers_restored}",
        f"Bearish Demotions Preserved: {report.bearish_demotions_preserved}",
        f"Downside Avoided: {_text(report.downside_avoided)}",
        f"Downside Reintroduced: {_text(report.downside_reintroduced)}",
        f"Missed Upside: {_text(report.missed_upside)}",
        f"Net Downside-Protection Value: {_text(report.net_downside_protection_value)}",
        f"True Protection Rate: {_text(report.true_protection_rate)}",
        f"False Demotion Rate: {_text(report.false_demotion_rate)}",
    )


def render_regime_shadow_bullish_promotion(
    report: RegimeShadowBullishPromotionReport,
) -> tuple[str, ...]:
    return (
        "Regime Shadow Bullish Promotion",
        f"Bullish Promotions Under Control: {report.bullish_promotions_under_control}",
        f"Promoted Winners: {report.promoted_winners}",
        f"Promoted Losers: {report.promoted_losers}",
        f"Promotion Precision: {_text(report.promotion_precision)}",
        f"Average Promoted Return: {_text(report.average_promoted_return)}",
        f"MFE: {_text(report.mfe)}",
        f"MAE: {_text(report.mae)}",
        f"Finding: {report.finding.value}",
    )


def render_regime_shadow_setup_attribution(
    rows: tuple[RegimeShadowSetupAttribution, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Setup Attribution"]
    for row in rows:
        lines.append(
            f"- {row.setup_family}/{row.policy_id.value}: n={row.candidate_count}, "
            f"changes={row.verdict_changes}, auc={_text(row.auc)}, "
            f"buy_precision={_text(row.buy_precision)}, "
            f"avg={_text(row.average_return)}"
        )
    return tuple(lines)


def render_regime_shadow_quality(
    rows: tuple[RegimeShadowQualityReport, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Quality"]
    for row in rows:
        lines.append(
            f"- {row.slice_name}/{row.policy_id.value}: n={row.candidate_count}, "
            f"avg={_text(row.average_return)}, changes={row.verdict_changes}, "
            f"classification={row.classification}"
        )
    return tuple(lines)


def render_regime_shadow_temporal_stability(
    rows: tuple[RegimeShadowTemporalReport, ...],
) -> tuple[str, ...]:
    lines = ["Regime Shadow Temporal Stability"]
    for row in rows:
        lines.append(
            f"- {row.period}/{row.policy_id.value}: n={row.candidate_count}, "
            f"dates={row.date_count}, auc={_text(row.auc)}, "
            f"buy_precision={_text(row.buy_precision)}, "
            f"avg={_text(row.average_return)}, finding={row.finding}"
        )
    return tuple(lines)


def render_regime_shadow_readiness(
    report: RegimeShadowReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Regime Shadow Readiness",
        f"Integrity Status: {report.integrity_status.value}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        "Secondary Conclusion: "
        + _text(
            report.secondary_conclusion.value if report.secondary_conclusion else None
        ),
        f"Readiness Status: {report.readiness_status.value}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Decision Matrix:",
    ]
    lines.extend(
        f"- {item}: {status.value}; {reason}"
        for item, status, reason in report.decision_matrix
    )
    lines.append(
        f"Explicitly Prohibited Next Action: {report.explicitly_prohibited_next_action}"
    )
    return tuple(lines)


def export_regime_shadow_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_regime_shadow_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_flatten(_jsonable(row)) for row in rows] or [{"status": "empty"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _policy(
    *,
    policy_id: RegimeShadowPolicyId,
    config: str,
    created: datetime,
    source_fingerprint: str,
) -> RegimeShadowPolicyVersion:
    version = {
        RegimeShadowPolicyId.CONTROL: "regime-shadow-control-v1",
        RegimeShadowPolicyId.CONTEXT_ONLY: "regime-shadow-context-only-v1",
        RegimeShadowPolicyId.BEARISH_ONLY: "regime-shadow-bearish-only-v1",
    }[policy_id]
    fingerprint = _fingerprint(
        f"{policy_id.value}|{version}|{config}|{source_fingerprint}"
    )
    return RegimeShadowPolicyVersion(
        policy_id=policy_id,
        policy_version=version,
        policy_fingerprint=fingerprint,
        regime_classifier_version="current-production",
        regime_classifier_fingerprint=source_fingerprint,
        recommendation_policy_version="current-production",
        verdict_policy_version="current-production-thresholds",
        approval_policy_version="current-production",
        allocation_policy_version="current-production",
        intervention_configuration_fingerprint=_fingerprint(config),
        created_at=created,
        code_version=__version__,
    )


def _policy_from_dict(payload: dict[str, Any]) -> RegimeShadowPolicyVersion:
    return RegimeShadowPolicyVersion(
        policy_id=RegimeShadowPolicyId(str(payload["policy_id"])),
        policy_version=str(payload["policy_version"]),
        policy_fingerprint=str(payload["policy_fingerprint"]),
        regime_classifier_version=str(payload["regime_classifier_version"]),
        regime_classifier_fingerprint=str(payload["regime_classifier_fingerprint"]),
        recommendation_policy_version=str(payload["recommendation_policy_version"]),
        verdict_policy_version=str(payload["verdict_policy_version"]),
        approval_policy_version=str(payload["approval_policy_version"]),
        allocation_policy_version=str(payload["allocation_policy_version"]),
        intervention_configuration_fingerprint=str(
            payload["intervention_configuration_fingerprint"]
        ),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        code_version=str(payload["code_version"]),
    )


def _recorded_regime_adjustment(record: CandidateDecisionRecord) -> Decimal:
    regime = (record.market_regime or "").strip().upper()
    setup = (record.setup_type or "").strip().upper()
    if regime in {"BULL", "BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return Decimal("4") if "BREAKOUT" in setup else Decimal("2")
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return Decimal("-8")
    if "BREAKOUT" in setup:
        return Decimal("-4")
    return Decimal("-2")


def _policy_adjustment(
    policy: RegimeShadowPolicyId,
    recorded_adjustment: Decimal,
    record: CandidateDecisionRecord,
) -> Decimal:
    if policy is RegimeShadowPolicyId.CONTROL:
        return recorded_adjustment
    if policy is RegimeShadowPolicyId.CONTEXT_ONLY:
        return _ZERO
    regime = (record.market_regime or "").strip().upper()
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return recorded_adjustment
    return _ZERO


def _shadow_approved(
    record: CandidateDecisionRecord, score: Decimal, verdict: str
) -> bool:
    if not record.approved_for_deployment:
        return False
    return verdict in _POSITIVE_VERDICTS and score >= Decimal("75")


def _difference_reasons(
    *,
    score: Decimal,
    verdict: str,
    approved: bool,
    allocation: bool,
    record: CandidateDecisionRecord,
    policy: RegimeShadowPolicyId,
    recorded_adjustment: Decimal,
) -> tuple[str, ...]:
    reasons = []
    if score != record.strategy_score:
        reasons.append("score differs from authoritative control")
    if verdict != record.final_verdict:
        reasons.append("verdict differs from authoritative control")
    if approved != record.approved_for_deployment:
        reasons.append("approval eligibility differs from authoritative control")
    if allocation != record.approved_for_deployment:
        reasons.append("allocation eligibility differs from authoritative control")
    if policy is RegimeShadowPolicyId.CONTEXT_ONLY and recorded_adjustment != 0:
        reasons.append("context-only removed recorded regime adjustment")
    if policy is RegimeShadowPolicyId.BEARISH_ONLY and recorded_adjustment > 0:
        reasons.append("bearish-only removed positive regime adjustment")
    return tuple(reasons) or ("no difference",)


def _with_rank_differences(
    decisions: tuple[RegimeShadowDecision, ...],
) -> tuple[RegimeShadowDecision, ...]:
    control = _rank_by_policy(decisions, RegimeShadowPolicyId.CONTROL)
    ranks = {
        policy: _rank_by_policy(decisions, policy) for policy in RegimeShadowPolicyId
    }
    output: list[RegimeShadowDecision] = []
    for decision in decisions:
        rank_diff = abs(
            ranks[decision.policy_id].get(decision.authoritative_candidate_id, 0)
            - control.get(decision.authoritative_candidate_id, 0)
        )
        output.append(replace(decision, rank_difference=rank_diff))
    return tuple(output)


def _rank_by_policy(
    decisions: tuple[RegimeShadowDecision, ...],
    policy: RegimeShadowPolicyId,
) -> dict[str, int]:
    rows = sorted(
        (row for row in decisions if row.policy_id is policy),
        key=lambda row: row.shadow_score,
        reverse=True,
    )
    return {
        row.authoritative_candidate_id: index for index, row in enumerate(rows, start=1)
    }


def _by_candidate(
    decisions: tuple[RegimeShadowDecision, ...],
    policy: RegimeShadowPolicyId,
) -> dict[str, RegimeShadowDecision]:
    return {
        row.authoritative_candidate_id: row
        for row in decisions
        if row.policy_id is policy
    }


def _score_comparison(
    policy: RegimeShadowPolicyId,
    rows: tuple[RegimeShadowDecision, ...],
    control: dict[str, RegimeShadowDecision],
) -> RegimeShadowScoreComparison:
    diffs = [
        (
            row.shadow_score - control[row.authoritative_candidate_id].shadow_score
        ).quantize(_FOUR)
        for row in rows
        if row.authoritative_candidate_id in control
    ]
    scores = [row.shadow_score for row in rows]
    return RegimeShadowScoreComparison(
        policy_id=policy,
        candidate_count=len(rows),
        mean_score=_average(scores),
        median_score=_median(scores),
        mean_difference_vs_control=_average(diffs),
        median_difference_vs_control=_median(diffs),
        maximum_difference=max(diffs) if diffs else None,
        minimum_difference=min(diffs) if diffs else None,
        unchanged_scores=sum(diff == 0 for diff in diffs),
        changed_scores=sum(diff != 0 for diff in diffs),
        removed_bullish_adjustment=sum(
            row.regime_adjustment == 0
            and control.get(row.authoritative_candidate_id) is not None
            and control[row.authoritative_candidate_id].regime_adjustment > 0
            for row in rows
        ),
        removed_bearish_adjustment=sum(
            row.regime_adjustment == 0
            and control.get(row.authoritative_candidate_id) is not None
            and control[row.authoritative_candidate_id].regime_adjustment < 0
            for row in rows
        ),
        removed_neutral_adjustment=sum(
            row.regime_adjustment == 0
            and control.get(row.authoritative_candidate_id) is not None
            and control[row.authoritative_candidate_id].regime_adjustment == -2
            for row in rows
        ),
        retained_bearish_adjustment=sum(row.regime_adjustment < 0 for row in rows),
        rank_changes=sum(row.rank_difference > 0 for row in rows),
        mean_rank_displacement=_average([Decimal(row.rank_difference) for row in rows]),
        median_rank_displacement=_median(
            [Decimal(row.rank_difference) for row in rows]
        ),
        top_decile_membership_changes=_membership_changes(
            rows, control, Decimal("0.10")
        ),
        top_quartile_membership_changes=_membership_changes(
            rows, control, Decimal("0.25")
        ),
    )


def _membership_changes(
    rows: tuple[RegimeShadowDecision, ...],
    control: dict[str, RegimeShadowDecision],
    share: Decimal,
) -> int:
    if not rows or not control:
        return 0
    count = max(1, int(Decimal(len(rows)) * share))
    left = {
        row.authoritative_candidate_id
        for row in sorted(
            control.values(), key=lambda item: item.shadow_score, reverse=True
        )[:count]
    }
    right = {
        row.authoritative_candidate_id
        for row in sorted(rows, key=lambda item: item.shadow_score, reverse=True)[
            :count
        ]
    }
    return len(left.symmetric_difference(right))


def _verdict_row(
    policy: RegimeShadowPolicyId,
    transition: str,
    cause: str,
    rows: tuple[RegimeShadowDecision, ...],
    outcomes: dict[str, _Outcome],
) -> RegimeShadowVerdictComparison:
    return RegimeShadowVerdictComparison(
        policy_id=policy,
        transition=transition,
        transition_cause=cause,
        transition_count=len(rows),
        distinct_dates=len({row.decision_timestamp.date() for row in rows}),
        setup_distribution=(),
        regime_distribution=_counts(row.recorded_regime or "UNKNOWN" for row in rows),
        completed_outcomes=sum(
            row.authoritative_candidate_id in outcomes for row in rows
        ),
    )


def _transition_cause(row: RegimeShadowDecision) -> str:
    if row.regime_adjustment == 0 and row.score_difference < 0:
        return "BULLISH_PROMOTION_REMOVED"
    if row.regime_adjustment == 0 and row.score_difference > 0:
        regime = (row.recorded_regime or "").strip().upper()
        if regime not in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
            return "NEUTRAL_ADJUSTMENT_REMOVED"
        return "BEARISH_DEMOTION_REMOVED"
    if row.score_difference != 0:
        return "NEUTRAL_ADJUSTMENT_REMOVED"
    return "NO_REGIME_EFFECT"


def _approval_comparison(
    policy: RegimeShadowPolicyId,
    rows: tuple[RegimeShadowDecision, ...],
) -> RegimeShadowApprovalComparison:
    margins = [
        (row.shadow_score - row.authoritative_score).quantize(_FOUR)
        for row in rows
        if abs(row.authoritative_score - Decimal("75")) <= Decimal("5")
    ]
    return RegimeShadowApprovalComparison(
        policy_id=policy,
        approval_eligibility_changes=sum(row.approval_difference for row in rows),
        strict_approval_changes=sum(row.approval_difference for row in rows),
        raw_approval_changes=sum(row.approval_difference for row in rows),
        mean_approval_margin_change=_average(margins),
        allocation_eligibility_changes=sum(row.allocation_difference for row in rows),
        target_weight_changes=0,
        capital_action_changes=sum(row.allocation_difference for row in rows),
    )


def _outcome_comparison(
    policy: RegimeShadowPolicyId,
    rows: tuple[RegimeShadowDecision, ...],
    outcomes: dict[str, _Outcome],
    date_weighted: bool,
) -> RegimeShadowOutcomeComparison:
    weighted_rows = _date_weight_rows(rows, outcomes) if date_weighted else rows
    scored = tuple(
        (row.shadow_score, row)
        for row in weighted_rows
        if row.authoritative_candidate_id in outcomes
    )
    buys = tuple(
        row for row in weighted_rows if row.shadow_verdict in _POSITIVE_VERDICTS
    )
    buy_returns = [
        outcomes[row.authoritative_candidate_id].forward_return
        for row in buys
        if row.authoritative_candidate_id in outcomes
        and outcomes[row.authoritative_candidate_id].forward_return is not None
    ]
    completed = tuple(
        row for row in weighted_rows if row.authoritative_candidate_id in outcomes
    )
    return RegimeShadowOutcomeComparison(
        policy_id=policy,
        weighting="DATE" if date_weighted else "CANDIDATE",
        candidate_count=len(weighted_rows),
        completed_outcomes=len(completed),
        auc=_auc(scored, outcomes),
        spearman_rank_correlation=_spearman(
            [row.authoritative_score for row in weighted_rows],
            [row.shadow_score for row in weighted_rows],
        ),
        top_decile_win_rate=_decile_win_rate(scored, outcomes, top=True),
        bottom_decile_win_rate=_decile_win_rate(scored, outcomes, top=False),
        buy_precision_proxy=_ratio(
            sum(_winner(row, outcomes) for row in buys),
            len(buys),
        ),
        average_buy_return=_average(buy_returns),
        median_buy_return=_median(buy_returns),
        benchmark_relative_buy_return=None,
        mfe=_average(
            [
                outcomes[row.authoritative_candidate_id].mfe
                for row in completed
                if outcomes[row.authoritative_candidate_id].mfe is not None
            ]
        ),
        mae=_average(
            [
                outcomes[row.authoritative_candidate_id].mae
                for row in completed
                if outcomes[row.authoritative_candidate_id].mae is not None
            ]
        ),
        stop_hit_rate=_ratio(
            sum(outcomes[row.authoritative_candidate_id].stop_hit for row in completed),
            len(completed),
        ),
        target_hit_rate=_ratio(
            sum(
                outcomes[row.authoritative_candidate_id].target_hit for row in completed
            ),
            len(completed),
        ),
        promoted_winners=sum(
            row.verdict_difference and _winner(row, outcomes) for row in weighted_rows
        ),
        promoted_losers=sum(
            row.verdict_difference and _loser(row, outcomes) for row in weighted_rows
        ),
        demoted_winners=sum(
            row.verdict_difference and _winner(row, outcomes) for row in weighted_rows
        ),
        demoted_losers=sum(
            row.verdict_difference and _loser(row, outcomes) for row in weighted_rows
        ),
    )


def _date_weight_rows(
    rows: tuple[RegimeShadowDecision, ...],
    outcomes: dict[str, _Outcome],
) -> tuple[RegimeShadowDecision, ...]:
    grouped: dict[date, list[RegimeShadowDecision]] = defaultdict(list)
    for row in rows:
        if row.authoritative_candidate_id in outcomes:
            grouped[row.decision_timestamp.date()].append(row)
    output = []
    for day, items in grouped.items():
        output.append(items[0])
        del day
    return tuple(output)


def _setup_row(
    policy: RegimeShadowPolicyId,
    setup: str,
    rows: tuple[RegimeShadowDecision, ...],
    outcomes: dict[str, _Outcome],
) -> RegimeShadowSetupAttribution:
    completed = tuple(row for row in rows if row.authoritative_candidate_id in outcomes)
    returns = [
        outcomes[row.authoritative_candidate_id].forward_return
        for row in completed
        if outcomes[row.authoritative_candidate_id].forward_return is not None
    ]
    return RegimeShadowSetupAttribution(
        setup_family=setup,
        policy_id=policy,
        candidate_count=len(rows),
        verdict_changes=sum(row.verdict_difference for row in rows),
        auc=_auc(tuple((row.shadow_score, row) for row in completed), outcomes),
        buy_precision=_ratio(
            sum(
                _winner(row, outcomes)
                for row in rows
                if row.shadow_verdict in _POSITIVE_VERDICTS
            ),
            sum(row.shadow_verdict in _POSITIVE_VERDICTS for row in rows),
        ),
        average_return=_average(returns),
        benchmark_relative_return=None,
        mfe=_average(
            [
                outcomes[row.authoritative_candidate_id].mfe
                for row in completed
                if outcomes[row.authoritative_candidate_id].mfe is not None
            ]
        ),
        mae=_average(
            [
                outcomes[row.authoritative_candidate_id].mae
                for row in completed
                if outcomes[row.authoritative_candidate_id].mae is not None
            ]
        ),
        downside_avoided=None,
        missed_upside=None,
    )


def _temporal_row(
    period: str,
    policy: RegimeShadowPolicyId,
    rows: tuple[RegimeShadowDecision, ...],
    outcomes: dict[str, _Outcome],
) -> RegimeShadowTemporalReport:
    completed = tuple(row for row in rows if row.authoritative_candidate_id in outcomes)
    returns = [
        outcomes[row.authoritative_candidate_id].forward_return
        for row in completed
        if outcomes[row.authoritative_candidate_id].forward_return is not None
    ]
    return RegimeShadowTemporalReport(
        period=period,
        policy_id=policy,
        candidate_count=len(rows),
        date_count=len({row.decision_timestamp.date() for row in rows}),
        auc=_auc(tuple((row.shadow_score, row) for row in completed), outcomes),
        buy_precision=_ratio(
            sum(
                _winner(row, outcomes)
                for row in rows
                if row.shadow_verdict in _POSITIVE_VERDICTS
            ),
            sum(row.shadow_verdict in _POSITIVE_VERDICTS for row in rows),
        ),
        average_return=_average(returns),
        downside_avoided=None,
        missed_upside=None,
        finding="INSUFFICIENT_PERIOD_COVERAGE"
        if len(rows) < 20
        else "STABLE_ACROSS_PERIODS",
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None or not outcome.windows:
        return None
    return next(
        (window for window in outcome.windows if window.window == "20d"),
        outcome.windows[0],
    )


def _outcome_from(window: CandidateForwardWindowOutcome | None) -> _Outcome | None:
    if window is None:
        return None
    forward = window.forward_return_pct_from_entry
    if forward is None:
        forward = window.forward_return_pct_from_close
    if forward is None:
        return None
    return _Outcome(
        forward_return=forward,
        benchmark_relative_return=None,
        mfe=window.max_favourable_excursion_pct,
        mae=window.max_adverse_excursion_pct,
        target_hit=window.target_1_touched,
        stop_hit=window.risk_stop_touched,
        quality=str(window.outcome_label),
    )


def _verdict_from_score(score: Decimal) -> str:
    if score >= Decimal("90"):
        return "STRONG_BUY"
    if score >= Decimal("75"):
        return "BUY"
    if score >= Decimal("60"):
        return "WATCHLIST"
    if score >= Decimal("40"):
        return "AVOID"
    return "SELL"


def _clamp_score(score: Decimal) -> Decimal:
    return max(_ZERO, min(_HUNDRED, score)).quantize(_TWO, rounding=ROUND_HALF_UP)


def _winner(row: RegimeShadowDecision, outcomes: dict[str, _Outcome]) -> bool:
    outcome = outcomes.get(row.authoritative_candidate_id)
    return (
        outcome is not None
        and outcome.forward_return is not None
        and outcome.forward_return > 0
    )


def _loser(row: RegimeShadowDecision, outcomes: dict[str, _Outcome]) -> bool:
    outcome = outcomes.get(row.authoritative_candidate_id)
    return (
        outcome is not None
        and outcome.forward_return is not None
        and outcome.forward_return <= 0
    )


def _setup_family(row: RegimeShadowDecision) -> str:
    setup = (row.setup_type or "").strip().upper()
    if not setup:
        return "UNKNOWN_SETUP"
    if "BREAKOUT" in setup:
        return "BREAKOUT"
    if "PULLBACK" in setup or "RETRACEMENT" in setup:
        return "PULLBACK_RETRACEMENT"
    if "MOMENTUM" in setup:
        return "MOMENTUM"
    if "REVERSAL" in setup:
        return "REVERSAL"
    return setup


def _auc(
    scored: Sequence[tuple[Decimal, RegimeShadowDecision]],
    outcomes: dict[str, _Outcome],
) -> Decimal | None:
    positives = [score for score, row in scored if _winner(row, outcomes)]
    negatives = [score for score, row in scored if _loser(row, outcomes)]
    if not positives or not negatives:
        return None
    wins = Decimal("0")
    total = Decimal(len(positives) * len(negatives))
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += Decimal("1")
            elif pos == neg:
                wins += Decimal("0.5")
    return (wins / total).quantize(_FOUR)


def _decile_win_rate(
    scored: Sequence[tuple[Decimal, RegimeShadowDecision]],
    outcomes: dict[str, _Outcome],
    *,
    top: bool,
) -> Decimal | None:
    completed = tuple(scored)
    if not completed:
        return None
    count = max(1, len(completed) // 10)
    selected = sorted(completed, key=lambda item: item[0], reverse=top)[:count]
    return _ratio(sum(_winner(row, outcomes) for _, row in selected), len(selected))


def _spearman(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_ranks(left), _ranks(right))


def _ranks(values: Sequence[Decimal]) -> list[Decimal]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return ranks


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    avg_left = _average(left)
    avg_right = _average(right)
    if avg_left is None or avg_right is None:
        return None
    numerator = sum(
        (lval - avg_left) * (rval - avg_right)
        for lval, rval in zip(left, right, strict=True)
    )
    left_var = sum((value - avg_left) ** 2 for value in left)
    right_var = sum((value - avg_right) ** 2 for value in right)
    if left_var == 0 or right_var == 0:
        return None
    value = float(numerator) / ((float(left_var) * float(right_var)) ** 0.5)
    return Decimal(str(value)).quantize(_FOUR)


def _counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _average(values: Sequence[Decimal | None]) -> Decimal | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return (sum(cleaned, _ZERO) / Decimal(len(cleaned))).quantize(_FOUR)


def _median(values: Sequence[Decimal | None]) -> Decimal | None:
    cleaned = sorted(value for value in values if value is not None)
    if not cleaned:
        return None
    middle = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[middle].quantize(_FOUR)
    return ((cleaned[middle - 1] + cleaned[middle]) / Decimal("2")).quantize(_FOUR)


def _ratio(numerator: int | bool, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(int(numerator)) / Decimal(denominator)).quantize(_FOUR)


def _net(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_FOUR)


def _run_id(
    source: str,
    records: tuple[CandidateDecisionRecord, ...],
    policies: tuple[RegimeShadowPolicyVersion, ...],
) -> str:
    dates = [record.evaluation_date.isoformat() for record in records]
    raw = "|".join(
        [
            source,
            str(len(records)),
            min(dates) if dates else "",
            max(dates) if dates else "",
            ",".join(policy.policy_fingerprint for policy in policies),
        ]
    )
    return _fingerprint(raw)[:16]


def _shadow_id(candidate_id: str, policy_version: str, source: str) -> str:
    return _fingerprint(f"{candidate_id}|{policy_version}|{source}")[:24]


def _configuration_fingerprint(
    policies: tuple[RegimeShadowPolicyVersion, ...],
) -> str:
    return _fingerprint(",".join(policy.policy_fingerprint for policy in policies))


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _flatten(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"value": value}
    output: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, list | tuple | dict):
            output[key] = json.dumps(item, sort_keys=True)
        else:
            output[key] = item
    return output


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text(value: object) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "RegimeShadowBuildResult",
    "RegimeShadowDecision",
    "RegimeShadowDecisionStatus",
    "RegimeShadowEngine",
    "RegimeShadowFinding",
    "RegimeShadowIntegrityReport",
    "RegimeShadowIntegrityStatus",
    "RegimeShadowNextMilestone",
    "RegimeShadowPolicyId",
    "RegimeShadowPolicyVersion",
    "RegimeShadowReadinessReport",
    "RegimeShadowRepository",
    "export_regime_shadow_csv",
    "export_regime_shadow_json",
    "render_regime_shadow_approval_comparison",
    "render_regime_shadow_bearish_protection",
    "render_regime_shadow_build",
    "render_regime_shadow_bullish_promotion",
    "render_regime_shadow_integrity",
    "render_regime_shadow_outcomes",
    "render_regime_shadow_quality",
    "render_regime_shadow_readiness",
    "render_regime_shadow_score_comparison",
    "render_regime_shadow_setup_attribution",
    "render_regime_shadow_status",
    "render_regime_shadow_temporal_stability",
    "render_regime_shadow_verdict_comparison",
    "resolve_regime_shadow_ledger_path",
]
