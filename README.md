============================================================
# Project Alpha

Project Alpha is an enterprise-grade quantitative research platform for the Indian equity market.

## Status

Project Alpha is in the v1.5 release-readiness hardening phase.

Current platform capabilities include:

- Deterministic backtesting
- Broker simulation
- Execution ledger
- Portfolio accounting
- Portfolio analytics
- Portfolio optimization
- Objective and constraint evaluation
- Walk-forward research
- Parameter sweep research
- Experiment persistence
- Research session modeling
- Strategy comparison
- Professional research reports
- Research CLI
- Live daily runtime for market intelligence, recommendations, and portfolio allocation

## Daily Runtime

Run the current daily workflow:

```bash
poetry run python -m alpha run
```

The runtime loads the latest available NSE bhavcopy for the requested date,
builds live analysis rows, adapts them into intelligence inputs, then prints:

- market intelligence
- recommendation candidates
- approved portfolio deployment
- portfolio summary
- detailed allocation reports
- trading signal counts

If the current live feed does not include sector metadata, the market section can
show `Top Sector : UNKNOWN`. In that case the runtime prints:

```text
Metadata Notice: Sector metadata unavailable from current live feed.
```

This notice is informational only. Project Alpha does not infer or hardcode
sectors when metadata is unavailable.

## Recommendation Semantics

Recommendation rows show model output before portfolio policy is applied:

```text
1. PCJEWELLER: BUY action=BUY score=82.20 raw_allocation_hint=8.1698%
   drivers: alpha_signal, market_participation, market_volatility
```

`raw_allocation_hint` is a recommendation-level sizing hint. It is not approved
capital. `Allocation Reports` are the source of truth for approved deployment.
This means an `AVOID` recommendation may still display a raw hint, while its
allocation report correctly shows `SKIP` and `target_weight=0.0000`.

Driver lines are compact labels derived from existing recommendation evidence
and risk labels. They are deterministic, capped at four drivers, and omitted
when no evidence is available.

## Portfolio Allocation Semantics

The runtime distinguishes recommendation intent from approved deployment:

- `ALLOCATE` means approved fresh capital deployment.
- `REDUCE` with `capital_action=reduced_deployment` means a fresh candidate was
  approved at a risk-reduced deployment size.
- `REDUCE` with `capital_action=existing_position_reduction` means an existing
  position target is below the current holding.
- `SKIP` means no approved deployment.

The `Portfolio Summary` section is a compact view of approved deployment:

```text
Portfolio Summary
Approved Deployments : 3
Approved Capital     : 82000.00
Cash Remaining       : 218000.00
Highest Conviction   : PCJEWELLER
Largest Position     : PCJEWELLER 4.68%
```

`Approved Deployments` counts allocation reports with positive `target_weight`.
Approved weight and amount are summed from positive deployment reports.

## Quality Gates

Every release-readiness change must pass:

```bash
poetry run pytest
poetry run ruff check .
poetry run mypy alpha
poetry build
poetry run python -m alpha run
```

## CLI

Show the installed version:

```bash
poetry run python -m alpha version
```

Show release metadata and quality gates:

```bash
poetry run python -m alpha doctor
```

Use the research console:

```bash
poetry run python -m alpha research --help
```

## Development Principles

Project Alpha follows:

- Clean Architecture
- Strong typing
- Deterministic execution
- Immutable value objects where appropriate
- Composition over inheritance
- Stable public APIs
- Production-quality implementation
- Institutional-quality design
