# HTR-009B Corporate Actions, Price Basis, and Identity Transitions

## Scope

HTR-009B is a diagnostic-only Historical Truth milestone. It acquires official
NSE equity corporate-action records, retains their source bytes immutably,
normalizes action terms, derives adjustment factors only where the evidence is
sufficient, and audits price continuity and downstream contamination.

`PRODUCTION_INFLUENCE=false`

It does not alter recommendations, replay policy, signal weights, approval
thresholds, stop-loss rules, targets, allocation, portfolio construction, or
execution. Canonical `daily_candle` rows remain raw and immutable.

## Official Evidence Boundary

The default adapter uses yearly slices of NSE's official equity corporate-action
API. Only `nseindia.com` and approved NSE archive hosts are authoritative. A
third-party source may help discover an NSE record but cannot supply admitted
terms or an adjustment factor.

Raw responses live under:

```text
alpha_data/raw/nse/corporate_actions/historical/<year>/
```

Each response has a SHA-256-addressed immutable filename and a manifest retaining
the request URL, official host, retrieval timestamp, HTTP metadata, redirect
chain, byte count, covered dates, parser version, checksum, and reuse state.
Verification-only mode reads those bytes, validates their checksums, and performs
no acquisition or database mutation.

Failures use a typed taxonomy. Empty, malformed, wrong-segment, wrong-period,
duplicate, conflicting, ambiguous, identity-unresolved, and checksum-failed
evidence stays visible and cannot silently become an admitted action.

## Raw and Adjusted Price Bases

`daily_candle` remains the immutable raw market observation. HTR-009B adds:

- `corporate_action_event`
- `corporate_action_lineage`
- `corporate_action_adjustment_factor`
- `price_basis_interval`
- `adjusted_daily_candle`
- `adjusted_candle_lineage`
- `identity_transition`
- `corporate_action_rejection`
- `candidate_corporate_action_exposure`

`adjusted_daily_candle` contains only derived pre-action rows for admitted,
known factors. Every row carries its raw OHLCV values, cumulative price and
quantity factors, adjusted OHLCV, action IDs, calculation version, and as-of
date. It does not replace or update raw candles.

Price basis is explicit per identity interval: raw, backward-adjusted,
forward-adjusted, total-return-adjusted, mixed, factor unknown, transition
unresolved, no adjustment required, or conflicting.

## Factor Derivation

### Splits and Face-Value Changes

For old face value 10 and new face value 5, the backward price factor is `0.5`
and the quantity factor is `2.0`. Non-positive or incomplete face-value terms do
not produce a factor.

### Bonuses

For bonus shares `new:old`, the backward price factor is:

```text
old / (old + new)
```

Thus a 1:1 bonus produces price factor `0.5` and quantity factor `2.0`.

### Rights

Rights are never adjusted using the ratio alone. The theoretical ex-rights price
requires the official entitlement ratio, official rights price, and the last raw
close before the ex-date:

```text
TERP = (old_quantity * prior_close + new_quantity * rights_price)
       / (old_quantity + new_quantity)
price_factor = TERP / prior_close
```

If any input is unavailable, the factor remains `UNKNOWN`.

### Dividends

Cash dividends are retained for later total-return work. HTR-009B does not alter
the price-only technical series for ordinary or special dividends. This avoids
quietly mixing total-return and technical-price contracts.

### Mergers, Demergers, and Schemes

Reorganisations do not receive a simple multiplicative factor unless official
terms explicitly support it. They are represented as predecessor/successor
transitions. Missing successor identity or exchange terms remain unresolved.
Histories are never joined by name similarity.

## Point-in-Time Semantics

The system separates two concepts:

1. **Price normalization:** after an action occurs, an economically adjusted
   history may be used to keep pre- and post-action prices comparable.
2. **Predictive knowledge:** the action cannot be used as candidate evidence
   before its official announcement or effective boundary.

Candidate attribution excludes future ex-dates. When saved benchmark artifacts
contain only aggregate totals, HTR-009B reports
`BASELINE_TOTALS_NOT_IDENTITY_DATE_LINKABLE`; it does not fabricate row-level
exposure.

## Continuity and Contamination

For each admitted material action, the audit compares the last pre-action close
with the first candle on or after the ex-date. It reports raw and theoretically
adjusted gaps, ATR-normalized gaps, volume changes, continuity restoration, and
false-breakout or false-breakdown risk.

A material raw discontinuity is diagnostic evidence that moving averages, ATR,
Fibonacci levels, support/resistance, stop distances, targets, returns, MFE/MAE,
or outcome labels may be contaminated. HTR-009B flags these inputs; it does not
change any indicator or stop formula.

## Identity Transitions

Official merger, demerger, amalgamation, scheme, spin-off, replacement, ISIN,
symbol, relisting, and cancellation events are converted into explicit
transition assessments. Each states whether histories may be linked, price
comparison is valid, or a new identity is required. Unsupported transitions
remain fail-closed.

## CLI

Acquisition and certification:

```bash
poetry run python -m alpha historical-truth corporate-action-price-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --root alpha_data \
  --start 2016-01-01 \
  --end auto \
  --output artifacts/htr009b_corporate_action_price_continuity \
  --refresh-sources
```

Immutable verification and reuse:

```bash
poetry run python -m alpha historical-truth corporate-action-price-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --root alpha_data \
  --start 2016-01-01 \
  --end auto \
  --output artifacts/htr009b_corporate_action_price_continuity_reuse_audit \
  --verify-only
```

Filters include `--symbol`, `--isin`, `--year`, `--action-type`,
`--price-basis-state`, `--only-unresolved`, and
`--only-candidate-exposed`. Filtered commands are report-only and do not replace
the complete persisted certification surface.

## Artifacts and Certification

The exporter creates the required executive, source, action, factor, price-basis,
adjusted summary, discontinuity, indicator, stop, transition, candidate,
rejection, and certification JSON/CSV/Markdown artifacts with stable ordering.

Certification is not based on event count alone. Missing years, unknown factors,
mixed bases, unresolved transitions, conflicting events, and point-in-time cutoff
mismatches are independent blockers. 2026 YTD is certified only when calendar,
canonical candle, snapshot, corporate-action, and identity-transition evidence
share a common 2026 cutoff.

## Known Limitations

- NSE's corporate-action listing does not always contain complete announcement
  timestamps or full reorganisation terms.
- Candidate-level stop and outcome attribution is unavailable when the frozen
  baseline retains aggregate counts only.
- Dividend total-return adjustment is deliberately deferred to a separately
  versioned policy.
- An official action listing can establish that an event occurred without being
  sufficient to establish predecessor/successor continuity.
- The current milestone does not repair the missing suspension source and does
  not perform gate, decision-layer, or stop-loss optimization.

## Governance

- Historical truth only.
- No synthetic action evidence.
- No future event leakage.
- No naive rights adjustment.
- No name-only identity joins.
- No raw candle mutation.
- No production or trading policy changes.
- `PRODUCTION_INFLUENCE=false`.
