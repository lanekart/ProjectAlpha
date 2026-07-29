"""Deterministic natural-language compiler for governed research experiments."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

from alpha.research.lab_models import (
    ComparisonOperator,
    CompilationIssue,
    CompilationResult,
    Condition,
    ConditionGroup,
    ExperimentStatus,
    LogicOperator,
    ParameterSweep,
    ResearchExperimentSpec,
    RuleKind,
    SameSessionPolicy,
    SpecificationChange,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)
from alpha.research.lab_registry import candle_registry

_SPACE = re.compile(r"\s+")
_RSI = re.compile(
    r"rsi(?:\s+over)?\s*(\d+)?(?:\s*sessions?)?\s+(above|below)\s+(\d+(?:\.\d+)?)"
)
_MA = re.compile(
    r"(?:price|close)\s+(above|below)\s+(?:its\s+|the\s+)?(\d+)[-\s]?(?:dma|sma|ema)"
)
_VOLUME = re.compile(
    r"volume\s+(?:is\s+)?(?:at least|above|more than)\s+"
    r"(\d+(?:\.\d+)?)\s*(?:times|x)\s+(?:its\s+)?(\d+)[-\s]"
    r"(?:session|day)\s+average"
)
_MAX_POSITIONS = re.compile(r"(?:maximum|max(?:imum)? of)\s+(\d+)\s+positions?")
_HOLD = re.compile(
    r"(?:hold|maximum(?: holding period)?|after)\s+(?:for\s+)?(\d+)"
    r"\s+(?:trading\s+)?sessions?"
)
_PERCENT_STOP = re.compile(r"(\d+(?:\.\d+)?)%\s+stop")
_ATR_STOP = re.compile(r"(\d+(?:\.\d+)?)\s+atr\s+stop")
_PERCENT_TARGET = re.compile(r"(\d+(?:\.\d+)?)%\s+target")
_R_TARGET = re.compile(r"(\d+(?:\.\d+)?)r\s+target")
_ATR_TARGET = re.compile(
    r"(?:target\s+)?(\d+(?:\.\d+)?)\s+atr\s+(?:target|above entry)"
)
_DELAY = re.compile(r"(?:wait|delay(?: by)?)\s+(\d+)\s+sessions?")
_EXPIRY = re.compile(r"(?:within|after)\s+(\d+)\s+sessions?")
_RETRACEMENT = re.compile(r"(\d+(?:\.\d+)?)%\s+retracement")
_INITIAL_CAPITAL = re.compile(r"(?:use\s+)?(?:₹|rs\.?\s*)?(\d+)\s+crore")
_SWEEP = re.compile(
    r"test\s+(rsi thresholds|holding periods|portfolio sizes)\s+of\s+"
    r"([0-9,\sand]+)"
)

_AMBIGUOUS = {
    "good stocks": (
        "definition of 'good stocks'",
        ("Alpha BUY signals", "a registered technical condition"),
    ),
    "reasonable stop": (
        "stop method and level",
        ("8% stop", "2 ATR stop", "STOP-STRUCTURAL-10D"),
    ),
    "momentum weakens": (
        "definition of momentum weakness",
        ("RSI below 50", "MACD bearish crossover", "signal reversal"),
    ),
    "after a correction": (
        "definition of 'correction'",
        ("3% retracement", "price within 2% of the 50-DMA"),
    ),
}
_EXECUTABLE_CANDLES = {
    "BULLISH_CANDLE",
    "BEARISH_CANDLE",
    "DOJI",
    "HAMMER",
    "BULLISH_ENGULFING",
    "BEARISH_ENGULFING",
    "INSIDE_BAR",
    "OUTSIDE_BAR",
    "INSIDE_BAR_BREAKOUT",
    "CLOSE_TOP_20_PERCENT",
    "MARUBOZU",
    "SPINNING_TOP",
    "LONG_UPPER_WICK",
    "LONG_LOWER_WICK",
}


class NaturalLanguageResearchCompiler:
    """Compile a bounded research DSL without eval, SQL, or generated code."""

    def compile(
        self,
        request: str,
        *,
        experiment_id: str,
        session_id: str,
        certified_start: date,
        certified_end: date,
        parent: ResearchExperimentSpec | None = None,
    ) -> CompilationResult:
        normalized = _normalize(request)
        if not normalized:
            return _blocked(normalized, "request", "Research request cannot be empty.")
        issues = _ambiguity_issues(normalized)
        if issues:
            return CompilationResult(
                status=ExperimentStatus.BLOCKED,
                normalized_request=normalized,
                intent="COMPILE",
                specification=None,
                issues=issues,
            )
        unsupported = _unsupported_issue(normalized, certified_start)
        if unsupported is not None:
            return CompilationResult(
                status=ExperimentStatus.BLOCKED,
                normalized_request=normalized,
                intent="COMPILE",
                specification=None,
                issues=(unsupported,),
            )
        unsupported_feature = _unsupported_feature_issue(normalized)
        if unsupported_feature is not None:
            return CompilationResult(
                status=ExperimentStatus.BLOCKED,
                normalized_request=normalized,
                intent="COMPILE",
                specification=None,
                issues=(unsupported_feature,),
            )
        spec = parent or _default_spec(
            experiment_id=experiment_id,
            session_id=session_id,
            start=certified_start,
            end=certified_end,
            normalized=normalized,
        )
        if parent is not None:
            spec = spec.with_identity(
                experiment_id=experiment_id,
                parent_experiment_id=parent.experiment_id,
            )
        before = spec
        try:
            spec = self._apply(spec, normalized)
        except ValueError as error:
            return _blocked(normalized, "strategy", str(error))
        changes = _diff(before, spec) if parent is not None else ()
        return CompilationResult(
            status=ExperimentStatus.COMPILED,
            normalized_request=normalized,
            intent="MODIFY" if parent is not None else "CREATE",
            specification=spec,
            changes=changes,
            planned_children=_planned_children(spec),
        )

    def _apply(
        self,
        spec: ResearchExperimentSpec,
        request: str,
    ) -> ResearchExperimentSpec:
        result = spec
        result = _apply_mode(result, request)
        result = _apply_removals(result, request)
        result = _apply_conditions(result, request)
        result = _apply_entry(result, request)
        result = _apply_stops(result, request)
        result = _apply_targets(result, request)
        result = _apply_portfolio(result, request)
        result = _apply_sweeps(result, request)
        if "target-first" in request:
            result = replace(
                result,
                same_session_policy=SameSessionPolicy.ASSUME_TARGET_FIRST,
            )
        elif "stop-first" in request:
            result = replace(
                result,
                same_session_policy=SameSessionPolicy.ASSUME_STOP_FIRST,
            )
        return result


def _default_spec(
    *,
    experiment_id: str,
    session_id: str,
    start: date,
    end: date,
    normalized: str,
) -> ResearchExperimentSpec:
    has_alpha = "alpha" in normalized or "buy and strong buy" in normalized
    mode = StrategyMode.ALPHA_SIGNAL if has_alpha else StrategyMode.PURE_TECHNICAL
    sources = ("BUY", "STRONG_BUY") if has_alpha else ()
    return ResearchExperimentSpec(
        experiment_id=experiment_id,
        research_session_id=session_id,
        experiment_name=normalized[:120],
        parent_experiment_id=None,
        strategy_mode=mode,
        data_start=start,
        data_end=end,
        base_signal_source=sources,
    )


def _apply_mode(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    has_alpha = "alpha" in request or "buy and strong buy" in request
    has_technical = any(
        item in request
        for item in ("rsi", "dma", "sma", "ema", "volume", "adx", "macd")
    )
    if has_alpha and has_technical:
        return replace(
            spec,
            strategy_mode=StrategyMode.HYBRID,
            base_signal_source=("BUY", "STRONG_BUY"),
        )
    if has_alpha:
        return replace(
            spec,
            strategy_mode=StrategyMode.ALPHA_SIGNAL,
            base_signal_source=("BUY", "STRONG_BUY"),
        )
    if spec.base_signal_source and has_technical:
        return replace(spec, strategy_mode=StrategyMode.HYBRID)
    return spec


def _apply_removals(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    conditions = list(spec.entry_conditions.conditions)
    if "remove all technical indicators" in request:
        conditions = [
            item for item in conditions if item.kind is not RuleKind.INDICATOR
        ]
    if "remove all candle" in request or "remove candlestick confirmation" in request:
        conditions = [item for item in conditions if item.kind is not RuleKind.CANDLE]
    if "remove rsi" in request:
        conditions = [item for item in conditions if item.name != "RSI"]
    if "remove only the volume filter" in request or "remove all volume" in request:
        conditions = [
            item
            for item in conditions
            if item.name not in {"VOLUME_RATIO", "VOLUME_SMA"}
        ]
    if "remove bullish engulfing" in request:
        conditions = [item for item in conditions if item.name != "BULLISH_ENGULFING"]
    stop_policy = spec.stop_policy
    if "remove the stop" in request or "remove all stops" in request:
        stop_policy = StopPolicy()
    target_policy = spec.target_policy
    if "remove the fixed target" in request:
        target_policy = replace(
            target_policy,
            rules=tuple(
                item for item in target_policy.rules if item.rule_id != "FIXED_PERCENT"
            ),
        )
    if "remove the target" in request or "remove all targets" in request:
        target_policy = TargetPolicy(trailing_rule=target_policy.trailing_rule)
    return replace(
        spec,
        entry_conditions=ConditionGroup(
            operator=spec.entry_conditions.operator,
            conditions=tuple(conditions),
            groups=spec.entry_conditions.groups,
            required_count=spec.entry_conditions.required_count,
        ),
        stop_policy=stop_policy,
        target_policy=target_policy,
    )


def _apply_conditions(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    conditions = list(spec.entry_conditions.conditions)
    rsi = _RSI.search(request)
    if rsi:
        period = int(rsi.group(1) or 14)
        operator = (
            ComparisonOperator.ABOVE
            if rsi.group(2) == "above"
            else ComparisonOperator.BELOW
        )
        conditions = [item for item in conditions if item.name != "RSI"]
        conditions.append(
            Condition(
                condition_id=f"RSI_{period}_{operator.value}_{rsi.group(3)}",
                kind=RuleKind.INDICATOR,
                name="RSI",
                operator=operator,
                value=Decimal(rsi.group(3)),
                period=period,
            )
        )
    ma = _MA.search(request)
    if ma:
        period = int(ma.group(2))
        operator = (
            ComparisonOperator.ABOVE
            if ma.group(1) == "above"
            else ComparisonOperator.BELOW
        )
        conditions = [
            item
            for item in conditions
            if not (item.name == "SMA" and item.reference == "CLOSE")
        ]
        conditions.append(
            Condition(
                condition_id=f"CLOSE_{operator.value}_SMA_{period}",
                kind=RuleKind.INDICATOR,
                name="SMA",
                operator=operator,
                period=period,
                reference="CLOSE",
            )
        )
    volume = _VOLUME.search(request)
    if volume:
        conditions = [item for item in conditions if item.name != "VOLUME_RATIO"]
        conditions.append(
            Condition(
                condition_id=f"VOLUME_RATIO_{volume.group(1)}_{volume.group(2)}",
                kind=RuleKind.INDICATOR,
                name="VOLUME_RATIO",
                operator=ComparisonOperator.AT_LEAST,
                value=Decimal(volume.group(1)),
                period=int(volume.group(2)),
            )
        )
    if "adx above" in request:
        match = re.search(r"adx above\s+(\d+(?:\.\d+)?)", request)
        if match:
            conditions = [item for item in conditions if item.name != "ADX"]
            conditions.append(
                Condition(
                    condition_id=f"ADX_ABOVE_{match.group(1)}",
                    kind=RuleKind.INDICATOR,
                    name="ADX",
                    operator=ComparisonOperator.ABOVE,
                    value=Decimal(match.group(1)),
                    period=14,
                )
            )
    candle_aliases = sorted(
        (
            (alias, definition.pattern_id)
            for definition in candle_registry().values()
            if definition.pattern_id in _EXECUTABLE_CANDLES
            for alias in definition.aliases
        ),
        key=lambda item: -len(item[0]),
    )
    for alias, pattern_id in candle_aliases:
        if alias in request and f"remove {alias}" not in request:
            conditions = [
                item for item in conditions if item.kind is not RuleKind.CANDLE
            ]
            conditions.append(
                Condition(
                    condition_id=pattern_id,
                    kind=RuleKind.CANDLE,
                    name=pattern_id,
                )
            )
            break
    return replace(
        spec,
        entry_conditions=ConditionGroup(
            operator=LogicOperator.ALL,
            conditions=tuple(conditions),
        ),
    )


def _apply_entry(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    entry = spec.entry_rule
    if "next session close" in request:
        entry = replace(entry, rule_id="NEXT_VALID_SESSION_CLOSE")
    elif "next session open" in request or "next valid session open" in request:
        entry = replace(entry, rule_id="NEXT_VALID_SESSION_OPEN", delay_sessions=0)
    delay = _DELAY.search(request)
    if delay:
        entry = replace(
            entry,
            rule_id="DELAYED_SESSION_OPEN",
            delay_sessions=int(delay.group(1)),
        )
    if "breaks above the signal candle high" in request:
        entry = replace(entry, rule_id="BREAKOUT_ABOVE_SIGNAL_HIGH")
    retracement = _RETRACEMENT.search(request)
    if retracement and "entry" in request:
        entry = replace(
            entry,
            rule_id="PERCENT_RETRACEMENT_LIMIT",
            retracement_percent=Decimal(retracement.group(1)),
        )
    if "does not trigger within" in request:
        expiry = _EXPIRY.search(request)
        if expiry:
            entry = replace(entry, expiry_sessions=int(expiry.group(1)))
    return replace(spec, entry_rule=entry)


def _apply_stops(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    stop = spec.stop_policy
    percent = _PERCENT_STOP.search(request)
    atr = _ATR_STOP.search(request)
    structural = "stop-structural-10d" in request
    if percent:
        stop = StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal(percent.group(1))),))
    if atr:
        stop = StopPolicy(
            rules=(StopRule("ATR", Decimal(atr.group(1)), atr_period=14),)
        )
    if structural:
        stop = StopPolicy(rules=(StopRule("STOP-STRUCTURAL-10D"),))
    if "below the signal candle low" in request:
        stop = StopPolicy(rules=(StopRule("SIGNAL_CANDLE_LOW"),))
    if "below the latest swing low" in request:
        stop = StopPolicy(rules=(StopRule("SWING_LOW"),))
    if "below support" in request and "whichever" not in request:
        stop = StopPolicy(rules=(StopRule("SUPPORT"),))
    if "whichever is tighter" in request and percent:
        stop = StopPolicy(
            rules=(
                StopRule("FIXED_PERCENT", Decimal(percent.group(1))),
                StopRule("SWING_LOW"),
            ),
            combination="TIGHTER",
        )
    trailing = re.search(
        r"(\d+(?:\.\d+)?)%\s+trailing stop(?: after the trade gains "
        r"(\d+(?:\.\d+)?)%)?",
        request,
    )
    if trailing:
        rules = tuple(item for item in stop.rules if item.rule_id != "TRAILING_PERCENT")
        stop = StopPolicy(
            rules=(
                *rules,
                StopRule(
                    "TRAILING_PERCENT",
                    Decimal(trailing.group(1)),
                    activation_gain_percent=(
                        None
                        if trailing.group(2) is None
                        else Decimal(trailing.group(2))
                    ),
                ),
            ),
            combination="STAGED" if rules else None,
        )
    return replace(spec, stop_policy=stop)


def _apply_targets(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    target = spec.target_policy
    percent = _PERCENT_TARGET.search(request)
    r_target = _R_TARGET.search(request)
    atr = _ATR_TARGET.search(request)
    if percent:
        target = TargetPolicy(
            rules=(TargetRule("FIXED_PERCENT", Decimal(percent.group(1))),),
            trailing_rule=target.trailing_rule,
        )
    if r_target:
        target = TargetPolicy(
            rules=(TargetRule("R_MULTIPLE", Decimal(r_target.group(1))),),
            trailing_rule=target.trailing_rule,
        )
    if atr:
        target = TargetPolicy(
            rules=(TargetRule("ATR_MULTIPLE", Decimal(atr.group(1))),),
            trailing_rule=target.trailing_rule,
        )
    half = re.search(r"half (?:the position )?at\s+(\d+(?:\.\d+)?)r", request)
    trail = re.search(r"trail the (?:balance|rest) with a\s+(\d+(?:\.\d+)?)%", request)
    if half:
        target = TargetPolicy(
            rules=(
                TargetRule(
                    "R_MULTIPLE",
                    Decimal(half.group(1)),
                    Decimal("50"),
                ),
            ),
            trailing_rule=(
                StopRule("TRAILING_PERCENT", Decimal(trail.group(1)))
                if trail
                else StopRule("TRAILING_PERCENT", Decimal("10"))
            ),
        )
    if "no fixed target" in request:
        target = TargetPolicy(trailing_rule=target.trailing_rule)
    return replace(spec, target_policy=target)


def _apply_portfolio(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    result = spec
    positions = _MAX_POSITIONS.search(request)
    if positions:
        result = replace(result, maximum_concurrent_positions=int(positions.group(1)))
    hold = _HOLD.search(request)
    if hold:
        result = replace(result, maximum_holding_sessions=int(hold.group(1)))
    capital = _INITIAL_CAPITAL.search(request)
    if capital:
        result = replace(
            result,
            initial_capital=Decimal(capital.group(1)) * Decimal("10000000"),
        )
    return result


def _apply_sweeps(
    spec: ResearchExperimentSpec,
    request: str,
) -> ResearchExperimentSpec:
    match = _SWEEP.search(request)
    if match:
        values = tuple(re.findall(r"\d+(?:\.\d+)?", match.group(2)))
        field = {
            "rsi thresholds": "ENTRY.RSI.THRESHOLD",
            "holding periods": "MAXIMUM_HOLDING_SESSIONS",
            "portfolio sizes": "MAXIMUM_CONCURRENT_POSITIONS",
        }[match.group(1)]
        return replace(spec, parameter_sweeps=(ParameterSweep(field, values),))
    if "compare" in request and "target" in request:
        values = _target_sweep_values(request)
        if values:
            return replace(
                spec,
                parameter_sweeps=(ParameterSweep("TARGET_POLICY", values),),
            )
    if "compare" in request and "stop" in request:
        values = _stop_sweep_values(request)
        if values:
            return replace(
                spec,
                parameter_sweeps=(ParameterSweep("STOP_POLICY", values),),
            )
    if "compare" in request and any(
        item in request
        for item in ("bullish engulfing", "hammer", "inside-bar breakout")
    ):
        candle_values = ["NONE"]
        for phrase, identifier in (
            ("bullish engulfing", "BULLISH_ENGULFING"),
            ("hammer", "HAMMER"),
            ("inside-bar breakout", "INSIDE_BAR_BREAKOUT"),
            ("top 20%", "CLOSE_TOP_20_PERCENT"),
        ):
            if phrase in request:
                candle_values.append(identifier)
        return replace(
            spec,
            parameter_sweeps=(
                ParameterSweep(
                    "CANDLE_CONFIRMATION",
                    tuple(candle_values),
                ),
            ),
        )
    return spec


def _stop_sweep_values(request: str) -> tuple[str, ...]:
    values = [
        f"FIXED_PERCENT:{item}"
        for item in re.findall(r"(\d+(?:\.\d+)?)%\s+stop", request)
    ]
    values.extend(
        f"ATR:{item}" for item in re.findall(r"(\d+(?:\.\d+)?)\s+atr\s+stop", request)
    )
    if "stop-structural-10d" in request:
        values.append("STOP-STRUCTURAL-10D")
    return tuple(dict.fromkeys(values))


def _target_sweep_values(request: str) -> tuple[str, ...]:
    values = [
        f"FIXED_PERCENT:{item}"
        for item in re.findall(r"(\d+(?:\.\d+)?)%\s+target", request)
    ]
    values.extend(
        f"R_MULTIPLE:{item}"
        for item in re.findall(r"(\d+(?:\.\d+)?)r\s+target", request)
    )
    if "no fixed target" in request:
        values.append("NONE")
    return tuple(dict.fromkeys(values))


def _normalize(request: str) -> str:
    return _SPACE.sub(" ", request.strip().lower())


def _ambiguity_issues(request: str) -> tuple[CompilationIssue, ...]:
    return tuple(
        CompilationIssue(field=field, message=message, alternatives=alternatives)
        for phrase, (message, alternatives) in _AMBIGUOUS.items()
        if phrase in request
        for field in (phrase.upper().replace(" ", "_"),)
    )


def _unsupported_issue(
    request: str,
    certified_start: date,
) -> CompilationIssue | None:
    year_matches = tuple(int(value) for value in re.findall(r"\b(20\d{2})\b", request))
    if year_matches and min(year_matches) < certified_start.year:
        return CompilationIssue(
            field="data_start",
            message=(
                f"Requested date precedes certified boundary "
                f"{certified_start.isoformat()}."
            ),
            alternatives=(f"Use {certified_start.isoformat()} onward",),
        )
    for phrase, field in (
        ("intraday", "intraday sequencing"),
        ("level 2", "level-2 order book"),
        ("level 3", "level-3 order book"),
        ("market impact", "market-impact simulation"),
        ("python", "arbitrary Python"),
        (" sql", "arbitrary SQL"),
    ):
        if phrase in request:
            return CompilationIssue(
                field=field,
                message=f"Unsupported DSI-011 request: {field}.",
            )
    return None


def _unsupported_feature_issue(request: str) -> CompilationIssue | None:
    unsupported = {
        "macd": "MACD",
        "supertrend": "SUPERTREND",
        "stochastic": "STOCHASTIC",
        "williams": "WILLIAMS_R",
        "bollinger": "BOLLINGER_BANDS",
        "relative strength": "RELATIVE_STRENGTH",
        "fibonacci": "FIBONACCI_RETRACEMENT",
        "morning star": "MORNING_STAR",
        "evening star": "EVENING_STAR",
        "three white soldiers": "THREE_WHITE_SOLDIERS",
        "three black crows": "THREE_BLACK_CROWS",
    }
    for phrase, feature in unsupported.items():
        if phrase in request:
            return CompilationIssue(
                field="entry_conditions",
                message=(
                    f"{feature} is registered for research metadata but does not "
                    "yet have a canonical DSI-011 execution adapter."
                ),
                alternatives=(
                    "RSI",
                    "SMA or DMA",
                    "volume ratio",
                    "bullish engulfing",
                    "hammer",
                ),
            )
    if " either " in f" {request} " or "at least two of" in request:
        return CompilationIssue(
            field="entry_conditions",
            message=(
                "This logical expression contains an unsupported conversational "
                "shape; use an explicit registered ALL expression."
            ),
            alternatives=("Require RSI above 50 and price above the 200-DMA",),
        )
    return None


def _blocked(request: str, field: str, message: str) -> CompilationResult:
    return CompilationResult(
        status=ExperimentStatus.BLOCKED,
        normalized_request=request,
        intent="COMPILE",
        specification=None,
        issues=(CompilationIssue(field=field, message=message),),
    )


def _diff(
    before: ResearchExperimentSpec,
    after: ResearchExperimentSpec,
) -> tuple[SpecificationChange, ...]:
    ignored = {"experiment_id", "parent_experiment_id", "experiment_name"}
    old = before.as_dict()
    new = after.as_dict()
    return tuple(
        SpecificationChange(
            field=key,
            before=str(old.get(key)),
            after=str(new.get(key)),
        )
        for key in sorted(set(old) | set(new))
        if key not in ignored and old.get(key) != new.get(key)
    )


def _planned_children(spec: ResearchExperimentSpec) -> int:
    count = 1
    for sweep in spec.parameter_sweeps:
        count *= len(sweep.values)
    return count if spec.parameter_sweeps else 0


__all__ = ["NaturalLanguageResearchCompiler"]
