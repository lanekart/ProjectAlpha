from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from alpha.candidate_learning import LearningLedgerRepository
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
    RawForwardWindowOutcome,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_PERIODS = ("1d", "3d", "5d", "10d", "20d", "60d")


@dataclass(frozen=True, slots=True)
class PlaybookRank:
    name: str
    sample_size: int
    win_rate: Decimal | None
    expected_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class BestSetupPlaybook:
    total_samples: int
    completed_samples: int
    best_setup_types: tuple[PlaybookRank, ...]
    best_regimes: tuple[PlaybookRank, ...]
    best_holding_periods: tuple[PlaybookRank, ...]
    best_stop_target_structures: tuple[PlaybookRank, ...]
    worst_patterns_to_avoid: tuple[PlaybookRank, ...]
    insufficient_sample_warning: str | None


class BestSetupPlaybookBuilder:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def build(self, *, minimum_sample_size: int = 30) -> BestSetupPlaybook:
        records = self.repository.load_raw_records()
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        completed = sum(
            1
            for record in records
            if _window(outcomes.get(record.raw_candidate_id), "20d") is not None
        )
        warning = (
            f"Insufficient evidence: {completed} completed samples, "
            f"minimum {minimum_sample_size} preferred."
            if completed < minimum_sample_size
            else None
        )
        return BestSetupPlaybook(
            total_samples=len(records),
            completed_samples=completed,
            best_setup_types=_rank_groups(
                records=records,
                outcomes=outcomes,
                key_fn=_setup_key,
                holding_period="20d",
                reverse=True,
            ),
            best_regimes=_rank_groups(
                records=records,
                outcomes=outcomes,
                key_fn=lambda record: record.market_regime or "UNKNOWN",
                holding_period="20d",
                reverse=True,
            ),
            best_holding_periods=_best_holding_periods(
                records=records,
                outcomes=outcomes,
            ),
            best_stop_target_structures=_rank_groups(
                records=records,
                outcomes=outcomes,
                key_fn=_stop_target_structure,
                holding_period="20d",
                reverse=True,
            ),
            worst_patterns_to_avoid=_rank_groups(
                records=records,
                outcomes=outcomes,
                key_fn=_avoid_pattern,
                holding_period="20d",
                reverse=False,
            ),
            insufficient_sample_warning=warning,
        )


def render_best_setup_playbook(playbook: BestSetupPlaybook) -> tuple[str, ...]:
    lines = [
        "Best Setup Playbook",
        f"Total Replay Samples: {playbook.total_samples}",
        f"Completed Samples: {playbook.completed_samples}",
        f"Playbook Verdict: {_playbook_verdict(playbook)}",
    ]
    if playbook.insufficient_sample_warning:
        lines.append(playbook.insufficient_sample_warning)
    lines.extend(("", "Best-Performing Setup Types:"))
    lines.extend(_rank_lines(playbook.best_setup_types))
    lines.extend(("", "Best Regimes:"))
    lines.extend(_rank_lines(playbook.best_regimes))
    lines.extend(("", "Best Holding Periods:"))
    lines.extend(_rank_lines(playbook.best_holding_periods))
    lines.extend(("", "Best Stop/Target Structures:"))
    lines.extend(_rank_lines(playbook.best_stop_target_structures))
    lines.extend(("", "Worst Patterns To Avoid:"))
    lines.extend(_rank_lines(playbook.worst_patterns_to_avoid))
    lines.extend(("", "How Alpha Should Use This:"))
    lines.extend(_usage_lines(playbook))
    return tuple(lines)


def _rank_groups(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    key_fn: object,
    holding_period: str,
    reverse: bool,
) -> tuple[PlaybookRank, ...]:
    groups: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        window = _window(outcomes.get(record.raw_candidate_id), holding_period)
        if window is None or window.forward_return_pct_from_close is None:
            continue
        key = key_fn(record)  # type: ignore[operator]
        groups[str(key)].append(window.forward_return_pct_from_close)
    ranked = tuple(
        PlaybookRank(
            name=key,
            sample_size=len(values),
            win_rate=_ratio(sum(1 for value in values if value > 0), len(values)),
            expected_return_pct=_average(tuple(values)),
        )
        for key, values in groups.items()
    )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                item.expected_return_pct
                if item.expected_return_pct is not None
                else Decimal("-999"),
                Decimal(item.sample_size),
            ),
            reverse=reverse,
        )[:5]
    )


def _best_holding_periods(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> tuple[PlaybookRank, ...]:
    ranks: list[PlaybookRank] = []
    for period in _PERIODS:
        returns = tuple(
            window.forward_return_pct_from_close
            for record in records
            if (window := _window(outcomes.get(record.raw_candidate_id), period))
            is not None
            and window.forward_return_pct_from_close is not None
        )
        ranks.append(
            PlaybookRank(
                name=period,
                sample_size=len(returns),
                win_rate=_ratio(sum(1 for value in returns if value > 0), len(returns)),
                expected_return_pct=_average(returns),
            )
        )
    return tuple(
        sorted(
            ranks,
            key=lambda item: (
                item.expected_return_pct
                if item.expected_return_pct is not None
                else Decimal("-999"),
                Decimal(item.sample_size),
            ),
            reverse=True,
        )[:5]
    )


def _setup_key(record: RawCandidateRecord) -> str:
    return record.indicators_active[0] if record.indicators_active else "UNKNOWN"


def _stop_target_structure(record: RawCandidateRecord) -> str:
    if (
        record.close_price is None
        or record.risk_stop is None
        or record.target_1 is None
        or record.close_price <= record.risk_stop
    ):
        return "structure unavailable"
    risk = record.close_price - record.risk_stop
    reward = record.target_1 - record.close_price
    ratio = reward / risk
    if ratio >= Decimal("3"):
        return "3R+ target with structural stop"
    if ratio >= Decimal("2"):
        return "2R target with structural stop"
    return "sub-2R target structure"


def _avoid_pattern(record: RawCandidateRecord) -> str:
    setup = _setup_key(record)
    regime = record.market_regime or "UNKNOWN"
    quality = "emitted" if record.was_emitted_decision else "filtered"
    return f"{setup} in {regime} ({quality})"


def _window(
    outcome: RawCandidateForwardOutcome | None,
    period: str,
) -> RawForwardWindowOutcome | None:
    if outcome is None:
        return None
    return next((window for window in outcome.windows if window.window == period), None)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def _rank_lines(ranks: tuple[PlaybookRank, ...]) -> list[str]:
    if not ranks:
        return ["- unavailable"]
    return [
        "- "
        f"{rank.name}: sample {rank.sample_size}, "
        f"win rate {_metric(rank.win_rate)}, "
        f"EV {_metric(rank.expected_return_pct)}%"
        for rank in ranks
    ]


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _playbook_verdict(playbook: BestSetupPlaybook) -> str:
    if playbook.completed_samples <= 0:
        return "No completed replay evidence yet."
    if playbook.insufficient_sample_warning is not None:
        return "Directional only; sample size is still below the preferred threshold."
    return "Usable for ranking setups, regimes, holding periods, and avoid patterns."


def _usage_lines(playbook: BestSetupPlaybook) -> list[str]:
    if playbook.completed_samples <= 0:
        return ["- Build replay outcomes before using the playbook in decisions."]
    lines: list[str] = []
    if playbook.best_setup_types:
        lines.append(
            "- Prefer setups like "
            f"{playbook.best_setup_types[0].name} when current evidence also agrees."
        )
    if playbook.best_regimes:
        lines.append(
            "- Favor regimes like "
            f"{playbook.best_regimes[0].name} when trade plans have clean risk/reward."
        )
    if playbook.best_holding_periods:
        lines.append(
            "- Use "
            f"{playbook.best_holding_periods[0].name} as the first holding-period "
            "benchmark, then validate with stop/target evidence."
        )
    if playbook.worst_patterns_to_avoid:
        lines.append(
            "- Disqualify or heavily discount patterns like "
            f"{playbook.worst_patterns_to_avoid[0].name} unless fresh evidence is "
            "exceptional."
        )
    return lines or ["- No actionable playbook preference is available yet."]


__all__ = [
    "BestSetupPlaybook",
    "BestSetupPlaybookBuilder",
    "PlaybookRank",
    "render_best_setup_playbook",
]
