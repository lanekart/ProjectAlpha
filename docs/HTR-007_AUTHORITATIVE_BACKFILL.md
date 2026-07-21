# HTR-007 Authoritative Historical Data Backfill

HTR-007 populates the governed Historical Truth Warehouse with official NSE cash-market archives and certifies the resulting replay window. It extends the existing historical-truth subsystem; it does not create a parallel downloader or commit downloaded market data to Git.

## Slice 1: Cross-era pilot

The first slice probes representative official NSE bhavcopy dates across the supported archive eras:

- `2016-01-04` — legacy archive and schema.
- `2020-01-02` — legacy archive and schema.
- `2023-01-02` — legacy archive and schema.
- `2026-01-02` — UDiFF archive and schema.

The date set is deliberately small. Its purpose is to prove URL planning, immutable retrieval, ZIP safety, schema detection, validation, DuckDB ingestion, point-in-time snapshot construction and deterministic evidence before a multi-year acquisition begins.

## Command

```bash
poetry run python -m alpha.historical_truth pilot \
  --root alpha_data \
  --output-dir artifacts/htr007_backfill_pilot
```

The main Project Alpha CLI exposes the same command under its historical-truth group.

Custom representative dates may be supplied by repeating `--date`:

```bash
poetry run python -m alpha.historical_truth pilot \
  --date 2016-01-04 \
  --date 2020-01-02 \
  --date 2023-01-02 \
  --date 2026-01-02
```

The command may access the official NSE archive when the immutable raw file is not already present locally. CI tests never perform live downloads; they use deterministic local ZIP fixtures.

## Official source boundary

The existing planner uses the NSE historical equity archive for legacy bhavcopies and the NSE UDiFF common cash-market bhavcopy archive from July 8, 2024 onward. NSE's current reports page identifies the UDiFF common bhavcopy as the replacement for the discontinued legacy current-report format. The raw archive URL, requested date and SHA-256 are retained in the append-only warehouse manifest.

HTR-007 does not bypass access controls, defeat anti-bot mechanisms or infer permission to redistribute exchange data. Raw archives remain local and immutable.

## Pilot artifact contract

The pilot writes:

- `htr007_backfill_pilot.json`
- `htr007_backfill_pilot.csv`
- `htr007_backfill_pilot.md`

Each date records:

- official source URL,
- immutable raw relative path,
- expected and detected schema,
- manifest status,
- archive SHA-256 and byte size,
- safe ZIP member name,
- archive row count,
- validation result,
- canonical availability state,
- ingested or available row count,
- snapshot relative path and verification result,
- checksum-drift flag,
- explicit error evidence.

`report_sha256` is computed from deterministic fields only. Wall-clock download and snapshot-generation timestamps are intentionally excluded.

## Fail-closed rules

A date is not certified by the pilot when any of the following occurs:

- the official archive is unavailable or retrieval fails,
- an existing immutable archive changes checksum,
- the ZIP is malformed,
- the ZIP contains zero, multiple, nested or unsafe CSV members,
- the detected schema is unsupported or inconsistent with the format era,
- source validation reports an error,
- canonical ingestion fails,
- the point-in-time snapshot is missing or fails checksum verification.

A partial snapshot may pass the candle-layer pilot because identity, corporate-action, delivery, index and VIX completeness belong to later HTR-007 slices. It cannot satisfy final HTR-006 replay readiness until those required datasets are certified.

## Next slices

After the pilot is green:

1. Run a checkpointed, bounded-concurrency backfill from `2016-01-01` through the selected cutoff.
2. Reconcile requests against an official trading calendar, including special sessions.
3. Populate corporate actions, security identity/listing history and benchmark history through governed adapters.
4. Rebuild annual inventory and snapshots.
5. Run `alpha replay readiness` for the intended research window.
6. Require a research-quality eligible-universe gate in addition to HTR-006's technical minimum.

## Governance

HTR-007 changes no strategy weights, recommendation thresholds, approval policy or portfolio policy. Data is not considered authoritative merely because it was downloaded. Final certification depends on integrity, lineage, coverage and replay-readiness evidence.
