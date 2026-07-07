============================================================
# Project Alpha

Project Alpha is an enterprise-grade quantitative research platform for the Indian equity market.

## Status

Project Alpha is in the v1.0 release-candidate hardening phase.

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

## Quality Gates

Every milestone must pass:

```bash
poetry run pytest
poetry run ruff check .
poetry run mypy alpha
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