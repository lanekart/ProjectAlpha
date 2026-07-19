# Alpha Pine Research Suite v1.0

This directory contains a secondary TradingView validation suite for the
Pine-compatible portion of Project Alpha. Alpha's Python implementation and
Market Truth Engine remain authoritative.

## Boundary

- `PRODUCTION_INFLUENCE=false`
- `BROKER_ORDERING=false`
- `AUTONOMOUS_DEPLOYMENT=false`
- `TRADINGVIEW_EXECUTION=false`
- `NO_LOOKAHEAD=true`
- `NO_REPAINTING=true`
- `ALPHA_SOURCE_OF_TRUTH=true`
- `TRADINGVIEW_IS_SECONDARY_VALIDATOR=true`

No script may be described as `ALPHA_EXACT`. TradingView cannot reproduce
Alpha's point-in-time universe, cross-sectional ranking, sector history,
adaptive ledger state, capacity, live-feed health, portfolio constraints, or
warehouse lineage.

## Layout

- `libraries/` contains modular, publishable Pine v6 source components.
- `strategies/` contains six self-contained research scripts.
- `indicators/` contains a component dashboard and trade-plan overlay.
- `manifests/` records extracted Alpha definitions and parity classifications.
- `fixtures/` contains synthetic source-to-Pine parity cases.
- `generated/` receives deterministic CLI exports.
- `labs/` contains the four TradingView Research Laboratory v2.0 experiments.

## Commands

```text
poetry run python -m alpha pine audit
poetry run python -m alpha pine manifest
poetry run python -m alpha pine export --strategy institutional-composite
poetry run python -m alpha pine validate
poetry run python -m alpha pine report
poetry run python -m alpha trl scripts
poetry run python -m alpha trl baseline
```

TRL operating instructions and promotion rules are in
`docs/pine/TRADINGVIEW_RESEARCH_LABORATORY_V2.md`.

Pine static validation does not compile scripts. Each generated source still
requires manual compilation and fixture verification in TradingView.

## Permanent Data Warning

DATA SOURCE: TRADINGVIEW  
NOT ALPHA MARKET TRUTH ENGINE  
CORPORATE-ACTION AND SYMBOL-HISTORY SEMANTICS MAY DIFFER  
RESULTS ARE INDEPENDENT VALIDATION, NOT AUTHORITATIVE ALPHA REPLAY
