# HTR-008 Replay Eligibility Integrity

## Purpose

HTR-008 certifies whether the observed historical population is suitable for
diagnostic replay. It does not change the benchmark's eligibility calculation,
the 200-session threshold, recommendations, approvals, or production policy.

HTR-007C proved canonical-session and immutable-snapshot parity. HTR-008 asks a
different question: whether each apparent security history represents one stable,
point-in-time identity with adequate continuity, lineage, corporate-action, and
survivorship evidence.

## Evidence Boundary

HTR-008 uses only:

- canonical `daily_candle` rows;
- canonical `security_identity` effective intervals;
- canonical `candle_ingestion_lineage` rows;
- canonical `corporate_action` rows;
- the certified HTR-007 calendar;
- immutable point-in-time snapshots; and
- the frozen CABR benchmark artifacts supplied to the command.

No network access, current listed-security universe, current sector mapping, or
third-party data is used. Unknown evidence remains unknown.

## Identity Model

The strongest available key is `exchange + ISIN`. This allows a supported symbol
change to retain one identity. When ISIN is unavailable, the fallback key is
`exchange + symbol + series`, and the identity is classified as ambiguous.

An identity is governed only when every observed candle maps to exactly one active
`security_identity` interval and the candle ISIN is compatible. Symbol equality
alone never merges histories. Overlaps, interval gaps, symbol reuse, unsupported
renames, multiple active mappings, and candles outside effective intervals remain
fail-visible.

## Point-in-Time Depth

Depth uses only valid `EQ` candles on certified official sessions. A row receives
history count `N` only after its first `N` valid observations. Future rows cannot
satisfy an earlier date. HTR-008 records the first dates reaching 20, 50, 100,
150, 200, 500, and 1,000 sessions. The canonical minimum remains exactly 200.

The CLI rejects any explicit `--minimum-history-sessions` value other than 200.

## Missing Sessions and Continuity

Expected sessions come from the certified HTR-007 calendar, including official
special sessions and excluding weekends and official holidays. Continuity is
measured inside the best supported active interval. In the absence of governed
listing intervals, the observed first-to-last interval is used only as an
explicitly provisional diagnostic boundary.

Missing sessions are explained only when authoritative evidence supports a
taxonomy such as before listing, after delisting, or official suspension. The
current warehouse has no suspension-history table, so HTR-008 does not infer a
suspension from missing candles. Unsupported absences inside an active interval
are `UNEXPLAINED_INTERNAL_GAP`.

## Candle Quality

The audit reports impossible OHLC relationships, negative or zero prices,
negative volume, duplicate keys, conflicting identity/date rows, unsupported
exchanges and series, missing source hashes, missing detailed lineage, and
snapshot mismatch. It never repairs or replaces canonical candles.

## Source Lineage

Source SHA-256 coverage and detailed ingestion-lineage coverage are separate.
Legacy rows with a source hash but no newer lineage record are classified as
`LEGACY_DETAILED_INGESTION_LINEAGE_UNAVAILABLE`, not corrupted. Contradictory
lineage remains blocking. Snapshot evidence is reloaded, checksum-verified, and
compared with canonical candle content one official session at a time.

## Corporate Actions

Only official events already represented in `corporate_action` are evaluated.
The report records surrounding raw prices, discontinuity, known ratio, replay
price basis, possible false-signal effects, and deterministic severity. HTR-008
does not introduce an adjustment policy. An empty event table is reported as an
evidence limitation rather than proof that no actions occurred.

## Survivorship Safeguards

The replay population is derived from historically observed candles, not today's
listed universe. HTR-008 detects candles before or after governed identity
intervals, future identity mappings, and unresolved point-in-time universe
evidence. Historical sector history is not available and current sectors are not
substituted. Delisted securities are not removed merely because they are absent
today.

## Candidate Attribution

HTR-008 maps the frozen benchmark's technical, BUY, and STRONG BUY candidates to
the identity classification active on the candidate date. It does not recompute
signals, scores, verdicts, approvals, or outcomes.

## Certification Rules

The default diagnostic policy is explicit:

- minimum valid history: 200 sessions;
- minimum continuity ratio: 95%;
- maximum unexplained internal gap: 5 sessions;
- governed identity required;
- point-in-time universe support required;
- source hash required;
- detailed lineage required for full certification;
- corporate-action evidence required for full certification; and
- complete immutable snapshot parity required.

Primary certification follows deterministic blocker precedence. Partial usability
does not become full certification, while bounded non-material limitations remain
visible as secondary issues.

## CLI

```bash
poetry run python -m alpha historical-truth \
  replay-eligibility-integrity-audit \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report \
    artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --snapshot-root alpha_data/snapshots \
  --benchmark-output .alpha/benchmark/PRE_HTR008_2016_2025 \
  --start 2016-01-01 \
  --end 2025-12-31 \
  --minimum-history-sessions 200 \
  --output artifacts/htr008_replay_eligibility_integrity
```

Focused output supports repeatable `--symbol`, `--isin`, `--year`,
`--classification`, and `--issue-code` filters plus `--only-not-ready`.

## Artifacts

Stable JSON and CSV views cover identity, depth, continuity, candle quality,
lineage, corporate actions, survivorship, daily eligibility, candidate exposure,
certification, and blockers. The primary report and certification are also
rendered as Markdown. Baseline JSON and Markdown are written under `baseline/`.
Rows and keys use deterministic ordering and the report carries a content hash.

## Performance Design

DuckDB performs population aggregation, validity checks, identity joins, windowed
history counts, streaks, gaps, annual coverage, daily funnels, and candidate joins.
Python retains only bounded per-identity, per-session, corporate-action, and
candidate-summary objects. Snapshots are processed one date at a time. There is no
quadratic security-by-date Python matrix.

## Known Limitations

The current local warehouse may lack authoritative security-identity intervals,
listing/delisting/suspension history, corporate-action coverage metadata,
historical sectors, and detailed lineage for legacy rows. HTR-008 reports those
limitations and must not infer them from price behavior or current mappings.

`PRODUCTION_INFLUENCE=false`
