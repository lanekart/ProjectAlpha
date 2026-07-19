# Tradable Opportunity Definition and Candidate Generation Recovery

## Purpose

This research milestone separates retrospective price advances from trading
setups that were objectively visible at the time. A forward move is an outcome label.
It is never an entry rule.

The research policy is `ALPHA_CANDIDATE_RESEARCH_v1.0`, with frozen parent
`ALPHA_CANONICAL_v1.0`. It cannot alter production recommendations, scores,
weights, approval gates, trade plans, or allocation.

## Evidence Boundary

Point-in-time features contain only the onset candle and preceding bars. Stored
inputs include prior resistance and support, EMA20, EMA50, ATR, volume relative
to its trailing average, pre-onset range contraction, turnover, extension, and
an evidence hash. Future return is absent from the feature snapshot and setup
predicate.

The existing `+20%/60`, `+30%/90`, and `+50%/180` definitions remain
retrospective labels. An event can therefore be:

- linked to a point-in-time tradable onset;
- a later winner with no qualifying onset;
- blocked by provisional identity or corporate-action evidence.

No large historical increase is assumed to have been tradable.

## Canonical Trace Limitation

The frozen ACU artifact retains ten ranked technical candidates per session. It
does not retain every negative setup-engine decision. The audit can prove that a
symbol was absent from the frozen candidate surface, but cannot always prove
which unpersisted internal predicate rejected it. Those rows carry an explicit
evidence limitation and a bounded structural attribution rather than a false
claim of exact internal provenance.

## Tradability

The initial research definition requires a configurable subset of observable
structure, liquidity, extension, stop feasibility, and prospective reward/risk.
It supports these typed families:

- breakout from base;
- volume breakout;
- trend reversal;
- EMA reclaim;
- pullback continuation;
- retest hold;
- volatility-contraction breakout;
- relative-strength breakout when benchmark evidence exists;
- failed-breakout reversal;
- early accumulation;
- no tradable onset.

The legacy dataset contains no authoritative benchmark or sector history.
Relative-strength and sector evidence therefore remain unavailable where they
cannot be computed honestly.

## Variant Validation

Variants are bounded and interpretable. They cover recognition tolerance, setup
vocabulary, timing state, and candidate-creation order. The engine evaluates
all point-in-time onsets, including signals that did not precede a major move.
This prevents winner-only precision.

Chronological partitions are fixed at 60% development, 20% validation, and 20%
holdout. Development and validation select at most one variant. Holdout cannot
select a variant; it can only confirm or reject the frozen selection.

Every variant is penalized for excessive candidates, duplicate unresolved
setups, poor prospective reward/risk, symbol concentration, negative net
expectancy, and false-candidate rate. A policy proposal is emitted only when the
selected variant passes development, validation, stability, and holdout.

## TradingView Boundary

TradingView remains a secondary validator. Strategy Tester rows are aggregated
by logical entry before parity or trade counts are reported. Exit legs retain a
logical entry ID, leg ID, quantity, remaining quantity, and forced-boundary flag.
No parity conclusion is reported without exact trade-level CSV evidence.

The chart overlay labels EMA20, EMA50, EMA200, entry, stop, and targets. The
institutional strategy uses one compact panel containing only score/verdict,
setup, entry, stop, targets, primary blocker, and evidence source. Partial-exit
strategies explicitly close the remaining position at the final target and at
the end boundary.

## Commands

```text
poetry run python -m alpha candidate-research define-opportunities
poetry run python -m alpha candidate-research funnel
poetry run python -m alpha candidate-research setups
poetry run python -m alpha candidate-research timing
poetry run python -m alpha candidate-research parity
poetry run python -m alpha candidate-research variants
poetry run python -m alpha candidate-research validate
poetry run python -m alpha candidate-research zero-candidates
poetry run python -m alpha candidate-research case-study --symbol KALYANKJIL
poetry run python -m alpha candidate-research policy
poetry run python -m alpha candidate-research report --json --csv
```

## Guardrails

- `PRODUCTION_INFLUENCE=false`
- `NO_AUTOMATIC_DEPLOYMENT=true`
- `NO_APPROVAL_RELAXATION=true`
- `NO_WEIGHT_CHANGES=true`
- `NO_FUTURE_LEAKAGE=true`
- `POINT_IN_TIME_ONLY=true`
- `HOLDOUT_REQUIRED=true`
- `CANDIDATE_EXPLOSION_PENALTY=true`
- `LEGACY_DATA_IS_PROVISIONAL=true`
- `TRADINGVIEW_IS_SECONDARY_VALIDATOR=true`
