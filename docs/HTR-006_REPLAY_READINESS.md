# HTR-006 — Historical Replay Readiness

HTR-006 prevents governed historical replay from executing when historical truth is incomplete, uncertified, or insufficient for the requested research window.

## Execution boundary

Executable replay requires all of the following:

- At least one governed replay date.
- No skipped governed replay dates.
- Complete annual inventory evidence for every requested calendar year.
- Every blocking and required dataset certified ready.
- At least 200 warm-up sessions on or before the earliest replay date.
- At least 60 forward outcome sessions strictly after the latest replay date.
- At least one security satisfying both warm-up and outcome requirements.

These thresholds are part of the versioned readiness contract and cannot be lowered by callers.

## Diagnostic command

The diagnostic readiness command builds canonical observations, inventory evidence, coverage evidence, and a readiness certificate without invoking the replay executor:

```bash
poetry run python -m alpha replay readiness \
  --from-date 2026-01-01 \
  --to-date 2026-07-20 \
  --identity-artifact artifacts/identities.csv \
  --corporate-action-artifact artifacts/corporate_actions.csv \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --output artifacts/historical_replay_readiness
```

A blocked assessment is a successful diagnostic result. The command reports blockers and exits without calling the replay executor.

## Diagnostic artifacts

The assessment command writes:

- `historical_replay_readiness_assessment.json`
- `historical_replay_readiness.json`
- `governed_replay_inputs.json`
- `governed_replay_reads.csv`
- `historical_replay_readiness_assessment.md`
- Canonical consumer-attestation JSON, CSV, and Markdown files when reads occurred.

The assessment JSON always contains `executor_invoked: false`.

## Executable replay artifacts

When readiness is `READY`, governed execution embeds the exact readiness certificate and SHA-256 into `governed_historical_replay_run.json`. The standalone `historical_replay_readiness.json` artifact is exported alongside the run.

## Integrity mapping

Existing historical-truth integrity failures are represented through governed inventory readiness:

- Missing expected trading sessions make `trading_calendar` uncertified, which produces `BLOCKING_DATASETS_NOT_READY` and `REQUIRED_DATASETS_NOT_READY`.
- Invalid source files, invalid snapshots, or warehouse/snapshot mismatches make `daily_ohlcv` uncertified and produce the same blockers.
- Date-level observation failures produce `SKIPPED_REPLAY_DATES`.

## Blockers

Stable blocker codes are:

- `NO_REPLAY_DATES`
- `SKIPPED_REPLAY_DATES`
- `MISSING_HISTORICAL_TRUTH_INVENTORY`
- `BLOCKING_DATASETS_NOT_READY`
- `REQUIRED_DATASETS_NOT_READY`
- `MISSING_REPLAY_COVERAGE_EVIDENCE`
- `INSUFFICIENT_WARMUP_SESSIONS`
- `INSUFFICIENT_OUTCOME_SESSIONS`
- `ZERO_ELIGIBLE_SECURITIES`

## Tamper resistance

`readiness_sha256` covers the complete serialized readiness manifest except the digest field itself. `verify_historical_replay_readiness_manifest()` rejects missing, malformed, or mismatched digests.

## Governance boundary

HTR-006 does not acquire data, tune strategies, alter recommendations, relax approval gates, or modify portfolio policy. Diagnostic partial output is never deployable evidence.
