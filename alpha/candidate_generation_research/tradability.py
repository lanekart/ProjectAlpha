from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from alpha.candidate_generation_research.models import (
    DATASET_VERSION,
    OpportunityFamily,
    PointInTimeFeatureSnapshot,
    TradableOpportunityOnset,
)


@dataclass(frozen=True, slots=True)
class TradabilityConfig:
    minimum_average_turnover: Decimal = Decimal("5000000")
    minimum_volume_ratio: Decimal = Decimal("1.10")
    minimum_reward_risk: Decimal = Decimal("1.50")
    maximum_extension: Decimal = Decimal("0.10")
    maximum_base_width: Decimal = Decimal("0.25")
    minimum_confidence: Decimal = Decimal("0.55")


class TradabilityEngine:
    """Convert a frozen feature snapshot into an actionable research onset."""

    def assess(
        self,
        snapshot: PointInTimeFeatureSnapshot,
        *,
        config: TradabilityConfig = TradabilityConfig(),
    ) -> TradableOpportunityOnset | None:
        family = _family(snapshot, config)
        if family is None:
            return None
        plan = _trade_plan(snapshot, family)
        if plan is None:
            return None
        entry, reference, stop, target = plan
        risk = entry - stop
        reward_risk = (target - entry) / risk
        extension = _extension(snapshot)
        liquid = (
            snapshot.average_turnover_20 is not None
            and snapshot.average_turnover_20 >= config.minimum_average_turnover
        )
        evidence = _evidence(snapshot, family, reward_risk, liquid)
        confidence = Decimal(len(evidence)) / Decimal("10")
        if not liquid:
            return None
        if reward_risk < config.minimum_reward_risk:
            return None
        if extension is None or extension > config.maximum_extension:
            return None
        if confidence < config.minimum_confidence:
            return None
        onset_id = _onset_id(snapshot, family)
        return TradableOpportunityOnset(
            onset_id=onset_id,
            forward_event_id=None,
            symbol=snapshot.symbol,
            onset_date=snapshot.observed_on,
            onset_sequence=snapshot.sequence,
            event_family=family,
            setup_evidence=evidence,
            entry_trigger=entry,
            reference_level=reference,
            prospective_stop=stop,
            prospective_target=target,
            prospective_rr=reward_risk,
            extension_state="ACCEPTABLE",
            liquidity_state="PASS",
            confidence=confidence,
            point_in_time_inputs={
                "feature_hash": snapshot.input_hash,
                "resistance_20": _text(snapshot.resistance_20),
                "support_20": _text(snapshot.support_20),
                "ema_20": _text(snapshot.ema_20),
                "ema_50": _text(snapshot.ema_50),
                "atr_14": _text(snapshot.atr_14),
                "volume_ratio_20": _text(snapshot.volume_ratio_20),
                "average_turnover_20": _text(snapshot.average_turnover_20),
                "base_width": _text(snapshot.base_width),
                "extension_pct": _text(extension),
                "relative_strength_20": _text(snapshot.relative_strength_20),
                "future_return_used_for_detection": "false",
            },
            dataset_version=DATASET_VERSION,
        )


def _family(
    item: PointInTimeFeatureSnapshot,
    config: TradabilityConfig,
) -> OpportunityFamily | None:
    resistance = item.resistance_20
    ema20 = item.ema_20
    ema50 = item.ema_50
    if resistance is None or ema20 is None:
        return None
    breakout = item.close > resistance
    base = item.base_width is not None and item.base_width <= config.maximum_base_width
    volume = item.volume_ratio_20 or Decimal("0")
    contraction = (
        item.recent_range_ratio is not None
        and item.prior_range_ratio is not None
        and item.recent_range_ratio <= item.prior_range_ratio * Decimal("0.75")
    )
    if breakout and base and contraction and volume >= Decimal("1.20"):
        return OpportunityFamily.VOLATILITY_CONTRACTION_BREAKOUT
    if breakout and volume >= Decimal("1.50"):
        return OpportunityFamily.VOLUME_BREAKOUT
    if breakout and base and volume >= config.minimum_volume_ratio:
        return OpportunityFamily.BREAKOUT_FROM_BASE
    if (
        item.prior_breakout
        and item.low <= resistance * Decimal("1.03")
        and item.close >= resistance
        and volume >= Decimal("1.00")
    ):
        return OpportunityFamily.RETEST_HOLD
    if (
        ema50 is not None
        and ema20 > ema50
        and item.low <= ema20 * Decimal("1.03")
        and item.prior_high is not None
        and item.close > item.prior_high
        and (item.close_location or Decimal("0")) >= Decimal("0.60")
    ):
        return OpportunityFamily.PULLBACK_CONTINUATION
    if (
        item.prior_close is not None
        and item.prior_ema_20 is not None
        and item.prior_close <= item.prior_ema_20
        and item.close > ema20
        and ema20 >= item.prior_ema_20
        and volume >= Decimal("1.00")
    ):
        return OpportunityFamily.EMA_RECLAIM
    if (
        ema50 is not None
        and item.prior_close is not None
        and item.prior_close < ema50
        and item.close > ema20
        and ema20 >= (item.prior_ema_20 or ema20)
        and volume >= Decimal("1.20")
    ):
        return OpportunityFamily.TREND_REVERSAL
    if (
        breakout
        and item.relative_strength_20 is not None
        and item.relative_strength_20 > Decimal("0.05")
    ):
        return OpportunityFamily.RELATIVE_STRENGTH_BREAKOUT
    if (
        base
        and item.base_width is not None
        and item.base_width <= Decimal("0.15")
        and volume >= Decimal("1.20")
        and (item.close_location or Decimal("0")) >= Decimal("0.70")
    ):
        return OpportunityFamily.EARLY_ACCUMULATION
    return None


def _trade_plan(
    item: PointInTimeFeatureSnapshot,
    family: OpportunityFamily,
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    if item.resistance_20 is None or item.atr_14 is None or item.atr_14 <= 0:
        return None
    reference = (
        item.ema_20
        if family
        in {
            OpportunityFamily.EMA_RECLAIM,
            OpportunityFamily.PULLBACK_CONTINUATION,
            OpportunityFamily.TREND_REVERSAL,
        }
        else item.resistance_20
    )
    if reference is None:
        return None
    entry = max(item.close, reference)
    anchors = tuple(
        value
        for value in (item.support_20, item.ema_20, item.recent_low_10)
        if value is not None and value < entry
    )
    if not anchors:
        return None
    anchor = max(anchors)
    stop = anchor - item.atr_14 * Decimal("0.50")
    if stop <= 0 or stop >= entry:
        return None
    if item.support_20 is None:
        return None
    measured_height = item.resistance_20 - item.support_20
    target = item.resistance_20 + measured_height
    if family in {OpportunityFamily.EMA_RECLAIM, OpportunityFamily.TREND_REVERSAL}:
        target = item.resistance_20
    if target <= entry:
        return None
    return entry, reference, stop, target


def _evidence(
    item: PointInTimeFeatureSnapshot,
    family: OpportunityFamily,
    reward_risk: Decimal,
    liquid: bool,
) -> tuple[str, ...]:
    evidence = [f"family={family.value}", "stop_is_point_in_time"]
    if item.base_width is not None and item.base_width <= Decimal("0.25"):
        evidence.append("bounded_pre_onset_base")
    if item.resistance_20 is not None and item.close > item.resistance_20:
        evidence.append("close_above_prior_resistance")
    if item.volume_ratio_20 is not None and item.volume_ratio_20 >= Decimal("1.10"):
        evidence.append("observable_volume_confirmation")
    if item.ema_20 is not None and item.close >= item.ema_20:
        evidence.append("price_above_ema20")
    if (
        item.ema_20 is not None
        and item.ema_50 is not None
        and item.ema_20 >= item.ema_50
    ):
        evidence.append("ema20_above_ema50")
    if item.recent_range_ratio is not None and item.prior_range_ratio is not None:
        if item.recent_range_ratio < item.prior_range_ratio:
            evidence.append("volatility_contracted_before_onset")
    if reward_risk >= Decimal("1.50"):
        evidence.append("prospective_rr_at_least_1_5")
    if liquid:
        evidence.append("minimum_turnover_passed")
    return tuple(evidence)


def _extension(item: PointInTimeFeatureSnapshot) -> Decimal | None:
    if item.ema_20 is None or item.ema_20 <= 0:
        return None
    return max(Decimal("0"), item.close / item.ema_20 - 1)


def _onset_id(item: PointInTimeFeatureSnapshot, family: OpportunityFamily) -> str:
    payload = f"{item.symbol}|{item.observed_on}|{family.value}|{item.input_hash}"
    return "onset-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _text(value: Decimal | None) -> str:
    return "UNAVAILABLE" if value is None else str(value)


__all__ = ["TradabilityConfig", "TradabilityEngine"]
