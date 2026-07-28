# DSI-010B1 Governed Legacy ISIN Bridge

## Purpose

DSI-010B1 determines whether a pre-2016 rights factor may use a canonical prior
close when that candle has no ISIN. It does not fill the candle ISIN. It
certifies a separate effective-dated official identity bridge and retains that
bridge as factor provenance.

The governed population is fixed:

- 105 rights factors;
- 37 factors already certified through a same-ISIN canonical prior close;
- 39 complete-term factors whose prior candle ISIN is missing;
- one explicit prior-ISIN mismatch, TATAPOWER;
- 28 factors whose official rights terms remain incomplete.

The 39 missing-ISIN cases are the bridge population. TATAPOWER is retained as a
non-bridgeable mismatch control. Missing terms are outside this milestone.

## Evidence Hierarchy

Certification requires all of the following:

1. An admitted HTR-010A3 identity join.
2. A valid event ISIN that exactly equals the governed identity.
3. A canonical prior candle with a positive close and source SHA-256.
4. One exact event series.
5. One compatible HTR-009A2 membership interval on the prior candle date.
6. One high-confidence symbol interval for the same identity and symbol.
7. An official event-derived series and ISIN state for that date.
8. Immutable source-event and source-document lineage.
9. No overlapping same-symbol and same-series identity.
10. No unresolved symbol reuse, symbol-change boundary, or series transition.
11. No explicit incompatible tradability state.

Legacy HTR-009A2 tradability rows marked
`UNRESOLVED_NO_TERMINATION_EVIDENCE` do not certify tradability and do not
certify suspension. They are retained as partial evidence. The independently
governed membership, exact symbol/series/ISIN state, immutable source lineage,
and actual canonical candle must still agree. An explicitly suspended,
pre-listing, post-delisting, reused-symbol, or conflicting state fails closed.

Observed price continuity, symbol equality, company-name similarity, future
candles, and current-master projection are not identity evidence.

## Signed Source Contract

The bridge is pinned to the signed HTR-009A2 foundation:

- workflow run: `30335669653`;
- artifact ID: `8679067292`;
- artifact: `dsi010-a3-b-repaired-rerun`;
- artifact digest:
  `sha256:b7c1ec98424ba0db12994213d615f5c187de6198e852315e9deab705bce948f7`;
- source head: `ce2dceb1a2755b68f373b80fbc3184a5fbe87faa`.

Every used HTR-009A2 file has a version-pinned SHA-256 in the bridge contract.
The loader rejects missing files, duplicate interval IDs, malformed dates,
invalid ISINs, inconsistent report hashes, path escapes, substituted files, and
lineage that cannot be traced to an immutable official source.

## Bridge Decisions

The sole accepted state is:

`CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE`

All other states reject factor promotion. Rejections distinguish missing
intervals, identity/symbol/series mismatch, confidence and lineage defects,
membership incompatibility, overlapping identity, symbol reuse, unresolved
symbol or series transitions, and insufficient official evidence.

`PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE` is separate from missing ISIN. The missing
ISIN contract cannot override an explicit different candle ISIN.

## Factor Integration

The HTR-010B rights-reference order is:

1. same candle ISIN and event ISIN:
   `CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE`;
2. missing candle ISIN:
   evaluate DSI-010B1;
3. different candle ISIN:
   remain `PRIOR_ISIN_MISMATCH`.

An accepted bridge uses the provenance state:

`CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE_PRIOR_CLOSE`

The factor records the original missing-ISIN state, interval IDs, membership
state, confidence, official event IDs, official source IDs, evidence hashes,
conflict checks, source contract, and report hash. The canonical candle remains
unchanged.

Rejected bridge factors remain provisional. They do not enter cumulative
factors, adjusted price basis, or replay admission.

## CLI

The complete corporate-action rebuild accepts the signed identity evidence:

```bash
poetry run python -m alpha historical-truth \
  complete-corporate-action-dataset \
  --database <HISTORICAL_TRUTH_DUCKDB> \
  --root <ALPHA_DATA_ROOT> \
  --htr010a3-output <HTR010A3_OUTPUT> \
  --htr009a2-output <HTR009A2_OUTPUT> \
  --start 2005-01-01 \
  --end 2015-12-31 \
  --output <HTR010B_OUTPUT> \
  --verify-only
```

After HTR-010B1E2:

```bash
poetry run python -m alpha historical-truth \
  legacy-rights-reference-bridge-certify \
  --htr009a2-output <HTR009A2_OUTPUT> \
  --htr010a3-output <HTR010A3_OUTPUT> \
  --htr010b-output <HTR010B_OUTPUT> \
  --htr010b1e2-output <HTR010B1E2_OUTPUT> \
  --output artifacts/dsi010b1_legacy_rights_reference_bridge
```

## Artifacts

The certification command writes:

- `legacy_rights_reference_bridge_cases.json`;
- `legacy_rights_reference_bridge_cases.csv`;
- `legacy_rights_reference_bridge_summary.json`;
- `legacy_rights_reference_bridge_rejections.json`;
- `legacy_rights_reference_bridge_source_manifest.json`;
- `legacy_rights_reference_bridge_report.md`;
- `legacy_rights_reference_bridge_certificate.json`.

The case ledger contains all 39 missing-ISIN factors. The rejection ledger also
contains the explicit TATAPOWER mismatch control.

## Empirical Result

The genuine signed-source rebuild certified 18 of the 39 complete-term
missing-ISIN cases:

`TTML`, `GTLINFRA`, `DICIND`, `HINDOILEXP`, `EXIDEIND`, `DHANBANK`,
`GODREJCP`, `FMGOETZE`, `CUB`, `INFOMEDIA`, `RELIGARE`, `ADANIENT`, `SUZLON`,
`MURUDCERA`, `EIHOTEL`, `KTKBANK`, `CENTRALBK`, and `ASAL`.

The remaining outcomes were:

- 21 `NO_MATCHING_OFFICIAL_INTERVAL`;
- one `PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE` control (`TATAPOWER`).

The rights-factor boundary changed from `37 / 40 / 28` to `55 / 22 / 28` for
certified-reference / provisional-reference / missing-terms states. Validation
outcomes changed from `235 / 3 / 399 / 68` to `235 / 3 / 417 / 50` for
confirmed-market-gap / conflicting-official-evidence /
insufficient-evidence / requires-reference-price. The 18 promoted factors
entered cumulative factors but remain outside replay where the independent
validation contract still reports insufficient evidence.

Implementation defects and unresolved admission intervals are both zero.
Deterministic duplicate runs produced byte-identical artifacts. The governed
report SHA-256 is
`b8c1b8b99c13a7a3e740f5e8c1731fa497e1d1ec42d24cbdf6da8c57d7ac54cc`;
the certificate file SHA-256 is
`4a204ead7417d68187bcaf0c8c8330a82054641ff740c4659cd6404cc1e37e41`.

## Readiness and Governance

The 18 certifications partially reduce only the rights-reference blocker. They
do not resolve:

- 28 rights events with incomplete official terms;
- 417 insufficient-evidence validation cases after bridge propagation;
- three conflicting-official-evidence cases.

The final state remains `NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION`, with
`FACTOR_INSUFFICIENT_EVIDENCE_REMAINS` as the blocker.

```text
FULL_BENCHMARK_REPLAYS=0
STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false
ADJUSTED_REPLAY_READY=false
PRODUCTION_INFLUENCE=false
```
