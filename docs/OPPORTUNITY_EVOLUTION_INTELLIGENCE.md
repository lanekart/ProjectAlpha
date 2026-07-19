# Opportunity Evolution Intelligence

Opportunity Evolution Intelligence is a research-only diagnostic layer for studying
how repeated BUY observations mature into one underlying trade opportunity. It does
not change production recommendations, thresholds, allocation, live feeds, order
logic, or trade plans.

## Purpose

Alpha can observe the same symbol many times while a setup forms. Counting every
observation as a separate signal inflates precision and hides the real question:
when should one underlying opportunity become tradeable?

This layer groups observations into deterministic opportunity paths, assigns a
point-in-time lifecycle state, compares trigger rules, and reports whether earlier
or later entry timing would have improved opportunity-level outcomes.

## Opportunity Identity

An opportunity is grouped by:

- symbol
- setup family
- BUY side
- first detection date
- deterministic reset index

The grouping resets when a new observation shows a material boundary:

- symbol changes
- setup family changes
- prior observation was invalidated
- market-regime family changes
- observation gap exceeds the reset window

This keeps one trade idea from being counted many times while still separating
genuinely new setups.

## Lifecycle States

Each observation is assigned one point-in-time lifecycle state:

- `DETECTED`
- `FORMING`
- `IMPROVING`
- `TRADEABLE_EARLY`
- `TRADEABLE_PREFERRED`
- `CONFIRMED`
- `EXTENDED`
- `DISTRIBUTING`
- `INVALIDATED`
- `EXPIRED`
- `COMPLETED`
- `UNAVAILABLE`

States are derived from evidence available at the observation date. Future return
labels are used only for diagnostic outcome evaluation.

## Scores

The engine separates two concepts:

- `opportunity_quality_score`: whether the setup is likely worth caring about.
- `entry_trigger_score`: whether the setup is actionable now.

This prevents a promising idea from being confused with an immediately executable
trade.

## Entry Trigger Research

The engine compares baseline and interpretable trigger rules:

- detected immediately
- current production-style threshold
- first early/aggressive/preferred/confirmation state
- best timing threshold
- full-stack score only
- full-stack plus timing
- price confirmation
- volume confirmation
- risk contraction
- retest hold
- multi-factor maturation
- trajectory improvement
- persistence
- no trigger

Each policy triggers at most once per opportunity. Opportunity-level precision is
the primary metric; observation-level precision is reported only to reveal signal
inflation.

## Hindsight Isolation

The diagnostic can mark `HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY`, but that marker is
never used as a production trigger. It exists only to estimate missed timing
opportunity and delay cost.

## CLI Commands

Run the primary report:

```bash
poetry run python -m alpha replay opportunity-evolution
```

Additional views:

```bash
poetry run python -m alpha replay opportunity-lifecycle-audit
poetry run python -m alpha replay entry-trigger-discovery
poetry run python -m alpha replay entry-trigger-frontier
poetry run python -m alpha replay early-entry-failures
poetry run python -m alpha replay confirmation-delay-audit
poetry run python -m alpha replay opportunity-paths
```

Supported filters and exports:

```bash
poetry run python -m alpha replay opportunity-evolution --symbol SYMBOL
poetry run python -m alpha replay opportunity-evolution --opportunity-id ID
poetry run python -m alpha replay opportunity-evolution --trigger FULL_STACK_PLUS_TIMING
poetry run python -m alpha replay opportunity-evolution --group-by setup
poetry run python -m alpha replay opportunity-evolution --format json --output report.json
poetry run python -m alpha replay opportunity-evolution --format csv --output paths.csv
```

Supported groupings:

- `setup`
- `regime`
- `lifecycle-state`
- `transition`
- `trigger`
- `year`
- `horizon`

## Production Boundary

Every report prints `PRODUCTION_INFLUENCE=false`. This milestone is intentionally
diagnostic. Any future promotion into production recommendation logic should happen
only after out-of-sample stability, sufficient opportunity-level sample size, and
explicit policy review.
