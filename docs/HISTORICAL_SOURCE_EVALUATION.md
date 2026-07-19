# Authoritative Historical Market Data Source Evaluation

## Decision

No external source is approved for permanent integration yet.

The documented evidence supports a **multi-source evaluation path**:

1. licensed NSE historical/EOD prices and corporate-action data as the proposed
   exchange-authoritative base;
2. a contracted historical-identity source, currently LSEG DataScope Select, for
   renamed, inactive, and delisted continuity;
3. a broker candle API only as a secondary price-overlap check.

This is not achieved coverage. No provider was empirically sampled because the
current process had no approved combination of credentials, subscription rights,
storage permission, and derived-use permission. Candidate coverage, projected
readiness, remaining unresolved records, and selection-bias reduction therefore
remain unavailable. `PRODUCTION_INFLUENCE=false`.

## Missing Population

The immutable `breakout_external_source_evaluation_manifest_v1` contains:

- 657 unresolved candidates;
- 608 requiring a new authoritative source;
- 49 recovery-uncertain candidates;
- 158 unique historical symbols;
- 121 required completed daily bars per candidate;
- conservative provider query dates from 2015-12-23 through 2026-07-09;
- 563 pre-candidate lookback gaps;
- 45 corporate-action ambiguities;
- 24 multi-session gaps;
- 15 partial-lookback cases; and
- 10 locally short histories without authoritative listing-date proof.

The request start is a deterministic provider-query floor: 121 weekdays including
the cutoff plus 30 calendar days for exchange holidays. Reconstruction still takes
the latest 121 valid completed exchange sessions. It does not invent holiday,
suspension, or zero-trade bars.

`current_symbol` is intentionally unavailable where the repository has no
authoritative effective-dated mapping. The historical symbol and existing permanent
point-in-time identifier are retained. A present-day symbol is never substituted as
historical fact.

## Data Contract

### Mandatory

- daily open, high, low, close, and traded volume;
- trading date and exchange-session identity;
- historical symbol and a permanent instrument identifier;
- listing date, delisting date, and effective-dated symbol changes;
- split/bonus history and corporate-action effective dates;
- explicit adjustment mode and raw unadjusted price/volume;
- suspended-session and zero-trade-session evidence;
- provenance, revision policy, publication timing, and availability start;
- local-storage permission and derived analytical-use permission.

OHLC supports the existing breakout reference, while traded volume supports its
20-session confirmation baseline. Identity and listing metadata prevent present-day
symbol mappings from creating survivorship or look-ahead bias. Corporate actions are
needed to explain raw-series discontinuities without inferring correctness from a
smooth adjusted chart. Publication timing, revisions, checksums, and permissions are
required for reproducible point-in-time evidence.

### Strongly Preferred

- price/volume adjustment consistency;
- ISIN;
- EQ/BE series history;
- relisting history; and
- the originally published archive.

### Optional Or Not Required

Dividend history is optional under the unchanged raw-series policy. Delivery volume,
retrospectively adjusted prices, and redistribution rights are not classifier inputs.
Internal storage and derived-use rights remain mandatory even though redistribution
is not required.

## Official Evidence Reviewed

### NSE

- [NSE All Reports](https://www.nseindia.com/all-reports) documents daily reports,
  bhavcopy/UDiFF material, security files, delivery data, and corporate-action files.
- [Securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading)
  links official company-name and symbol-change files.
- [Market activity report descriptions](https://www.nseindia.com/static/market-data/description-of-market-activity-reports)
  describes corporate-action details in exchange reports.
- [NSE Data Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
  defines market-data scope and makes the governing agreement material to permitted
  use.
- [NSE Terms of Use](https://www.nseindia.com/static/nse-terms-of-use) restricts
  automated collection and retained use without permission. Public availability is
  therefore not permission for Alpha to automate and retain a production dataset.
- [NSE EOD and historical subscriptions](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
  describes licensed EOD/historical delivery.
- [NSE historical data framework](https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf)
  describes exchange data products including bhavcopy, masters, trades, snapshots,
  circulars, and historical availability.

### Broker APIs

- [Upstox Historical Candle Data V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
  documents daily OHLCV from January 2000 and bounded date requests.
- [Upstox instrument files](https://upstox.com/developer/api-documentation/instruments/)
  document instrument keys and ISINs, but the main BOD equity file excludes delisted
  instruments. Current-master availability is not historical identity proof.
- [Upstox rate limits](https://upstox.com/developer/api-documentation/rate-limiting/)
  documents standard API limits of 50 requests/second, 500/minute, and 2,000 per
  30 minutes.
- [Kite historical candles](https://kite.trade/docs/connect/v3/historical/) documents
  OHLCV by instrument token for historical ranges.
- [Kite terms](https://kite.trade/terms/) restrict permanent databases and
  redistribution. This blocks Alpha's required retained source evidence unless a
  separate permission applies.
- [Dhan historical data](https://dhanhq.co/docs/v2/historical-data/) documents daily
  OHLCV from instrument inception, while [Dhan instrument masters](https://dhanhq.co/docs/v2/instruments/)
  describe current security identifiers. The reviewed pages do not prove a
  survivorship-safe inactive-security master or the required retained-use rights.

Broker endpoints are useful secondary price checks. None is treated as an
authoritative source for listing/delisting, symbol reuse, effective-dated identity,
corporate actions, and original-publication timing.

### Specialist Vendors

- [Global Datafeeds](https://globaldatafeeds.in/) advertises authorized NSE market
  data and historical/EOD APIs. Exact depth, delisted identity, retained-use rights,
  and revision lineage were not established from public terms.
- [TrueData APIs](https://www.truedata.in/market-data-apis) advertise historical/EOD
  and corporate feeds. Exact historical identity and contractual storage/derived-use
  rights remain unresolved.
- [LSEG DataScope Select](https://www.lseg.com/en/data-analytics/products/datascope-plus-securities-database)
  documents broad active/delisted security, reference, pricing, and corporate-action
  coverage. Exact NSE candidate coverage and Alpha's permitted fields/retention still
  require a contract and sample.
- [FactSet Symbology](https://developer.factset.com/api-catalog/symbology-api)
  documents effective-dated symbol mappings and permanent identifiers. It is an
  identity candidate, not a proven price source for this population.
- [FactSet third-party terms](https://www.factset.com/third-party-terms) show that
  licensed content restrictions depend on the applicable agreement.

## Documented Capability Scorecard

Scores are separate diagnostic dimensions from 0 to 100. They are not an unexplained
overall rank and they are not observed coverage. Candidate coverage is zero until a
deterministic response is observed.

| Provider | Documented role | Supported / partial / unknown / unsupported | License status |
| --- | --- | ---: | --- |
| NSE Data & Analytics licensed | Primary source candidate | 22 / 6 / 5 / 0 | Requires commercial license |
| NSE public archives | Research only | 16 / 9 / 6 / 2 | Personal research only |
| LSEG DataScope Select | Identity source candidate | 20 / 7 / 6 / 0 | Requires commercial license |
| FactSet Symbology | Identity source candidate | 5 / 3 / 20 / 5 | Requires commercial license |
| Upstox Historical V3 | Secondary validation | 10 / 3 / 13 / 7 | Terms not found for required retention/use |
| Zerodha Kite | Secondary validation | 7 / 4 / 13 / 9 | Permitted with conditions; storage blocked |
| Dhan Historical V2 | Secondary validation | 8 / 3 / 15 / 7 | Terms not found |
| Global Datafeeds | Insufficient evidence | 8 / 1 / 24 / 0 | Terms not found |
| TrueData | Insufficient evidence | 8 / 3 / 22 / 0 | Terms not found |

The machine-readable scorecard separately records authority, depth, candidate
coverage, identity, delisted coverage, corporate actions, point-in-time suitability,
quality, reproducibility, reliability, rate limits, licensing, storage, derived use,
cost, complexity, and dependency risk.

## Deterministic Sample

The 30-row sample is selected by stable candidate ID and required strata. It covers:

- 16 rows from 2016 and later replay years through 2026;
- 13 pre-boundary lookback gaps;
- 8 corporate-action ambiguities;
- 5 multi-session gaps;
- 3 partial-lookback cases;
- 1 locally short-history case;
- both observed continuity states;
- all available market regimes and setup types; and
- repeated-symbol cases.

Limitations are explicit. The current manifest has no authoritative renamed-symbol
labels and only a continuity proxy for inactive/delisted cases. Sector is `UNKNOWN`
throughout this missing population. Large/small-cap strata cannot be asserted from
the normalized liquidity proxy. A deterministic sample does not prove the 657-row
population.

## Coverage And Identity Proof Status

Observed coverage is zero for all nine providers. Therefore these values are
unavailable rather than estimated:

- exact candidate and unique-symbol coverage;
- 2016 coverage;
- historical-, renamed-, and delisted-symbol success rates;
- sufficient-lookback and corporate-action success rates;
- earliest/latest covered candidate;
- unresolved count after acquisition;
- projected reconstruction readiness; and
- projected selection-bias reduction.

An acceptable identity test must query current symbol, historical symbol, ISIN,
exchange/provider key, and permanent identifier separately. It must include renamed,
merged, demerged, suspended, delisted, relisted, symbol-reuse, and EQ/BE cases. A
current-symbol success cannot satisfy this test.

## Corporate Actions And Point-In-Time Use

The repository policy remains raw, unadjusted price and volume. Evaluation must test
known corporate-action windows for separately available raw/adjusted series,
effective dates, factors, consistent price/volume treatment, and retrospective
revision behavior. Smooth adjusted prices alone are not evidence of correctness.

A source can reconstruct price history yet still fail point-in-time suitability.
The final gate requires original-publication timing or versioned revisions,
effective-dated metadata, an unchanged previous-completed-session cutoff, and
permitted retained checksums. Later-known mappings or adjustments may not enter an
earlier candidate.

## Credentials, Cost, And Operations

The diagnostic process reports only credential status, never values. On the recorded
run, NSE public archives required no credentials; the other eight sources reported
`SUBSCRIPTION_REQUIRED`. No secret, account identifier, token, or cookie is exported.

NSE licensed data, LSEG, FactSet, Global Datafeeds, and TrueData require commercial
access or a quote. Exact current broker API prices were not established from the
linked endpoint documentation and are not used in the provider decision. Broker
access still does not solve identity or permission gaps. Exact commercial costs and
field entitlements require vendor quotations and contract review.

Operational blockers include account entitlement, instrument-identity continuity,
field-level licensing, rate limits, corrections/revisions, retention rights,
corporate-action normalization, and a full-population verification run. Terms must
permit caching before raw responses are retained. Otherwise evaluation stores only
sanitized metadata and permitted checksums.

## Rejected Shortcuts

- Public NSE downloads are not automated because the reviewed terms prohibit that
  use without permission.
- Broker candles are not promoted to primary because active/current instrument
  success is not survivorship-safe.
- Adjusted price smoothness is not used to infer a corporate action.
- Blogs, scraped websites, unofficial mirrors, GitHub datasets, and Yahoo-style
  feeds are excluded as authoritative evidence.
- Price-only vendors with unclear identity or retained-use rights are not selected
  because they appear cheap or convenient.
- No readiness or bias-reduction projection is fabricated from documentation.

## Commands

```bash
poetry run python -m alpha replay historical-source-requirements
poetry run python -m alpha replay historical-source-manifest
poetry run python -m alpha replay historical-source-evaluate --sample
poetry run python -m alpha replay historical-source-coverage
poetry run python -m alpha replay historical-source-license-audit
poetry run python -m alpha replay historical-source-recommendation
```

The commands support provider and candidate filtering, deterministic sample mode,
explicit full-population mode, dry run, credential-status overrides, and text/JSON/CSV
exports. `--sample` and `--full-population` are mutually exclusive. `--refresh` fails
explicitly because no approved live evaluation adapter exists. No command silently
falls back to another source.

## Next Evidence Gate

Before permanent integration:

1. obtain written NSE field, storage, revision, and derived-use terms;
2. obtain LSEG or equivalent effective-dated identity field entitlements;
3. run the 30-row sample through isolated read-only adapters;
4. reconcile raw OHLCV and corporate actions around known cases;
5. test renamed/delisted/inactive identity separately;
6. expand only a passing, lawfully retained source combination to all 657 rows; and
7. rerun source-gap and selection-bias diagnostics without changing the existing
   889/657 baseline until reconstruction is separately approved.

Current conclusion: `MULTI_SOURCE_ARCHITECTURE_REQUIRED` and
`SOURCE_EVIDENCE_INSUFFICIENT`.
