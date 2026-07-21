# HTR-007 Historical NSE Session Evidence

## Purpose

This slice acquires immutable official NSE Capital Market annual trading-holiday
circulars for 2016–2025 and converts them into governed calendar evidence.
It extends the current-year API reconciliation without treating missing bhavcopies
as inferred holidays.

## Official-source chain

For each year the engine:

1. Retrieves the official NSE annual holiday landing page.
2. Resolves the `Capital Market (Equities) Trade` PDF attachment.
3. Persists the landing-page HTML and circular PDF immutably.
4. Records SHA-256 evidence for both documents.
5. Extracts the official CM holiday table and Muhurat trading date.
6. Writes normalized JSON accepted by the governed session-calendar engine.
7. Stores a restart-safe yearly checkpoint.

A missing or ambiguous attachment, non-PDF response, unreadable PDF, invalid holiday
count, or ambiguous Muhurat date fails that year closed.

## Runtime command

```bash
poetry run python -m alpha.historical_truth.historical_session_evidence_cli run \
  --start-year 2016 \
  --end-year 2025 \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --root alpha_data \
  --output-dir artifacts/htr007_historical_session_evidence
```

The command shows progress for annual evidence acquisition, source loading, and
full-window reconciliation.

## Runtime paths

- Historical source evidence:
  `alpha_data/raw/nse/calendar/historical/<year>/`
- Year checkpoints:
  `alpha_data/manifests/htr007_historical_session_evidence_<year>.json`
- Deterministic reports:
  `artifacts/htr007_historical_session_evidence/`

All runtime paths remain ignored by Git.

## Governance

- No third-party holiday list is authoritative evidence.
- No missing archive is classified as a holiday without an official source.
- Annual circulars do not automatically prove later amendments or exceptional
  sessions; residual unresolved dates remain explicit.
- Holiday/candle conflicts and missing official special sessions fail the command.
- No strategy, scoring, recommendation, approval, portfolio, or execution policy
  is modified.
