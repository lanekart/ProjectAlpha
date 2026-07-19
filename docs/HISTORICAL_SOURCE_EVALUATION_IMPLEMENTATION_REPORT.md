# Historical Source Evaluation Implementation Report

## 1. Files Changed

- `alpha/historical_replay/historical_source_evaluation.py`
- `alpha/historical_replay/historical_source_evaluation_service.py`
- `alpha/historical_replay/__init__.py`
- `alpha/cli.py`
- `tests/historical_replay/test_historical_source_evaluation.py`
- `docs/HISTORICAL_SOURCE_EVALUATION.md`
- `docs/BREAKOUT_SOURCE_GAP_AUDIT.md`
- `docs/HISTORICAL_SOURCE_EVALUATION_IMPLEMENTATION_REPORT.md`

## 2. Architecture Added

The milestone adds immutable typed requirements, provider documents/capabilities,
identity and corporate-action evidence models, license assessments, candidate
observations, per-dimension scorecards, coverage results, a versioned manifest,
deterministic sample, recommendation report, evaluation engine, and project service.
The service consumes the existing source-gap audit; it does not register or call a
production provider.

## 3. Tests Added

Seventy-one deterministic tests cover requirements, exact project manifest counts,
ordering, checksum and sampling stability, documented versus observed evidence,
credentials, partial responses, identity, current-symbol-only rejection, delisted
measurement, lookback, corporate actions, raw/adjusted consistency, timezone,
duplicates, revisions, response conflicts, licensing, recommendation precedence,
CLI commands/options/exports/redaction, and policy isolation.

## 4. Validation Results

- `poetry run pytest`: 1,379 passed in 116.73 seconds.
- `poetry run ruff check .`: passed.
- `poetry run mypy alpha`: passed across 362 source files.
- `poetry build`: built `alpha-1.3.0.dev0.tar.gz` and
  `alpha-1.3.0.dev0-py3-none-any.whl`.

## 5. Exact CLI Commands

```bash
poetry run python -m alpha replay historical-source-requirements
poetry run python -m alpha replay historical-source-manifest
poetry run python -m alpha replay historical-source-evaluate --sample
poetry run python -m alpha replay historical-source-coverage
poetry run python -m alpha replay historical-source-license-audit
poetry run python -m alpha replay historical-source-recommendation
```

## 6. Exact Data Requirements

There are 24 mandatory requirements: daily OHLCV, trading date, exchange session,
historical symbol, permanent identifier, listing/delisting dates, symbol-change
history, split/bonus history, corporate-action effective dates, adjustment mode, raw
series, suspension/zero-trade evidence, provenance, revision policy, publication
timing, availability start, local-storage permission, and derived-use permission.
Five fields are strongly preferred, dividend history is optional, and delivery
volume, adjusted prices, and redistribution are not required.

## 7. Evaluation Manifest Counts

- manifest: `breakout_external_source_evaluation_manifest_v1`
- checksum: `929a183a0f374a838887a391cb6bbe3395449512d649eef526971318f4b6cfe9`
- total: 657
- source required: 608
- recovery uncertain: 49
- unique historical symbols: 158
- query range: 2015-12-23 to 2026-07-09
- minimum completed bars: 121 each
- causes: 563 pre-candidate, 45 corporate-action, 24 multi-session, 15 partial,
  and 10 locally short-history records

## 8. Deterministic Sample Composition

- rows: 30; historical symbols: 27
- checksum: `2b702336ab8408ff63a6fa0309f7abe3ab046f90e1f3c9ed62256e09664e0a54`
- years: 2016=16, 2017=1, 2018=2, 2019=2, 2020=1, 2021=1, 2022=1,
  2023=1, 2024=1, 2025=2, 2026=2
- causes: pre-candidate=13, corporate-action=8, multi-session=5, partial=3,
  locally short=1
- setups: Momentum Continuation=24, Trend Failure=4, Distribution=2
- regimes: Neutral=29, Negative=1
- continuity: active-to-end=21, ended-before-source-end=9
- identity uncertainty: 30; corporate-action cases: 8
- liquidity-proxy range: 0.0000 to 1.0000

Renamed status is unavailable and ended continuity is only an inactive/delisted
proxy. Sector is unknown. Liquidity extremes are not market-cap labels.

## 9. Providers Evaluated

NSE public archives; NSE Data & Analytics licensed data; Upstox Historical V3;
Zerodha Kite; Dhan Historical V2; Global Datafeeds; TrueData; LSEG DataScope Select;
and FactSet Symbology.

## 10. Official Documentation Reviewed

Official NSE all-reports, securities/symbol-change, market-report description, data
policy, terms, historical-subscription, and historical-data-framework documents;
official Upstox historical, instrument, analytics-token, and rate-limit documents;
official Kite historical and terms documents; official Dhan historical and instrument
documents; official Global Datafeeds, TrueData, LSEG DataScope Select, FactSet
Symbology, and FactSet third-party terms. Links and claim-level context are in
`docs/HISTORICAL_SOURCE_EVALUATION.md`.

## 11. Credentials By Provider

The recorded process status was `NOT_REQUIRED` for NSE public archives and
`SUBSCRIPTION_REQUIRED` for the other eight providers. Values were never read into a
report, logged, exported, or printed. No live call was made.

## 12. Documented Capability Matrix

| Provider | Supported | Partial | Unknown | Unsupported |
| --- | ---: | ---: | ---: | ---: |
| NSE licensed | 22 | 6 | 5 | 0 |
| NSE public | 16 | 9 | 6 | 2 |
| LSEG | 20 | 7 | 6 | 0 |
| FactSet | 5 | 3 | 20 | 5 |
| Upstox | 10 | 3 | 13 | 7 |
| Kite | 7 | 4 | 13 | 9 |
| Dhan | 8 | 3 | 15 | 7 |
| Global Datafeeds | 8 | 1 | 24 | 0 |
| TrueData | 8 | 3 | 22 | 0 |

These are documented claims, not measured candidate coverage. All mandatory gates
remain failed.

## 13. Observed Sample Coverage

Zero providers were empirically sampled. Candidate and symbol coverage are
unavailable for every provider. No response was fabricated.

## 14. Historical-Symbol Coverage

Unavailable for every provider. Current-symbol documentation is not counted.

## 15. Renamed-Symbol Coverage

Unavailable for every provider; authoritative renamed labels are absent from the
current manifest.

## 16. Delisted-Symbol Coverage

Unavailable for every provider; continuity-ended is retained only as a sampling
proxy and not called proof of delisting.

## 17. 2016 Coverage

The sample contains 16 2016 candidates and the full population contains 583. No
provider has observed 2016 coverage.

## 18. Sufficient-Lookback Coverage

Unavailable for every provider. Documentation is not converted into a 121-bar
success rate.

## 19. Corporate-Action Evidence Coverage

Unavailable for every provider. The sample contains eight corporate-action cases.

## 20. Raw-Versus-Adjusted Findings

Alpha's unchanged policy is raw unadjusted price and volume. NSE bhavcopy/report
documentation is the best documented fit. Broker candles do not, from the reviewed
evidence, satisfy the complete raw/adjusted/factor/effective-date/revision test.
Smooth adjusted prices are not accepted as corporate-action proof.

## 21. Point-In-Time Suitability

NSE licensed data has the strongest documented exchange/publication fit, but exact
correction versions, retention rights, and field delivery require a contract. LSEG
has strong maintained identity documentation but has not proven original-publication
timing for this population. No source is approved as point-in-time complete.

## 22. Licensing And Permitted Use

NSE licensed, LSEG, and FactSet require commercial licenses. NSE public is classified
personal-research-only for this use. Kite is permitted with conditions but prohibits
the required permanent database. Dhan, Upstox, Global Datafeeds, and TrueData have
terms-not-found status for the required retention and derived use. This is an
evidence classification, not legal advice.

## 23. Storage And Caching

NSE public requires written permission for storage, caching, and derived use and
prohibits the proposed automation under reviewed terms. Licensed NSE, LSEG, and
FactSet are conditional on contract. Kite storage is prohibited. Storage, caching,
and derived use are unknown for Dhan, Upstox, Global Datafeeds, and TrueData.

## 24. Rate Limits

Upstox documents standard limits of 50/second, 500/minute, and 2,000/30 minutes.
Dhan documents 5 data requests/second and 100,000/day. Kite is provider-controlled;
the exact historical limit was not established on the endpoint page. NSE licensed
uses subscribed SFTP/online delivery. LSEG and FactSet are entitlement dependent.
Global Datafeeds and TrueData are plan specific or unresolved. No rate was consumed.

## 25. Cost Findings

NSE licensed, LSEG, FactSet, Global Datafeeds, and TrueData require a commercial
tariff, subscription, or quote. Broker access requires an account or paid API where
applicable. Exact current cost was not used to rank a provider.

## 26. Provider-Specific Risks

- NSE public: anti-automation and retention restrictions.
- NSE licensed: commercial and contractual field dependency.
- Upstox: active BOD master excludes delisted equities; corporate actions absent.
- Kite: unstable/current instrument-token dependency and storage restriction.
- Dhan: active-instrument wording and no proven corporate-action feed.
- Global Datafeeds/TrueData: depth, identity, revision, and terms unresolved.
- LSEG: cost, entitlements, and third-party field restrictions.
- FactSet: separate price source required and third-party terms.

## 27. Projected Readiness By Provider

Unavailable for all providers because no approved full-population observations exist.

## 28. Projected Readiness Using Source Combinations

Unavailable. The proposed NSE-plus-LSEG architecture is a hypothesis awaiting
contract and candidate-level proof.

## 29. Projected Remaining Unavailable Candidates

Unavailable. The existing 889/657 reconstruction counts remain unchanged.

## 30. Projected Selection-Bias Reduction

`NOT_ESTIMABLE_WITHOUT_OBSERVED_CANDIDATE_COVERAGE`.

## 31. Recommended Primary Price Source

`NSE_DATA_ANALYTICS_LICENSED`, as a candidate only, subject to commercial rights and
sample/full-population proof.

## 32. Recommended Identity Source

`LSEG_DATASCOPE_SELECT`, as a contracted identity candidate only.

## 33. Recommended Corporate-Action Source

`NSE_DATA_ANALYTICS_LICENSED`, as an exchange-authoritative candidate only.

## 34. Recommended Architecture

Licensed NSE prices and corporate data as the authoritative base, contracted LSEG
historical identity for inactive/renamed continuity, and broker APIs only for overlap
validation. No component is approved for integration yet.

## 35. Overall Conclusion

`MULTI_SOURCE_ARCHITECTURE_REQUIRED`; `SOURCE_EVIDENCE_INSUFFICIENT`;
`REQUIRES_COMMERCIAL_LICENSE`.

## 36. Policy Integrity Confirmation

No permanent provider, historical record, reconstruction, classifier,
recommendation, approval, entry timing, stop, target, or production policy changed.
`PRODUCTION_INFLUENCE=false`.

## Complete Historical Source Coverage Output

```text
Historical Source Coverage Proof
Population: 657
Source Required / Recovery Uncertain: 608 / 49
Observed Coverage:
- DHAN_HISTORICAL_V2: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- FACTSET_SYMBOLOGY: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- GLOBAL_DATAFEEDS: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- LSEG_DATASCOPE_SELECT: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- NSE_DATA_ANALYTICS_LICENSED: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- NSE_PUBLIC_ARCHIVES: evidence=DOCUMENTED; status=NOT_EVALUATED_TERMS_RESTRICT_CACHING; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- TRUEDATA: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- UPSTOX_HISTORICAL_V3: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
- ZERODHA_KITE_HISTORICAL: evidence=DOCUMENTED; status=NOT_EVALUATED_CREDENTIALS_REQUIRED; target=30; returned=unavailable; sufficient=unavailable; symbols=unavailable; 2016=unavailable/16; projected-readiness=unavailable
  identity: historical=unavailable; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; unresolved=unavailable
  integrity: OHLC=unavailable; volume=unavailable; multi-session-gaps=unavailable; duplicates=unavailable; timezone=unavailable; adjustment=unavailable; covered=unavailable
Projected Combined Readiness: unavailable; no approved full-population coverage exists.
Projected Selection-Bias Reduction: NOT_ESTIMABLE_WITHOUT_OBSERVED_CANDIDATE_COVERAGE
PRODUCTION_INFLUENCE=false
```

## Complete License Audit Output

```text
Historical Source License and Permitted-Use Audit
Providers Assessed: 9
- DHAN_HISTORICAL_V2: TERMS_NOT_FOUND; automation=PERMITTED_WITH_CONDITIONS; storage=UNKNOWN; derived-use=UNKNOWN; caching=UNKNOWN; terms=not found
- FACTSET_SYMBOLOGY: REQUIRES_COMMERCIAL_LICENSE; automation=PERMITTED_WITH_CONDITIONS; storage=PERMITTED_WITH_CONDITIONS; derived-use=PERMITTED_WITH_CONDITIONS; caching=PERMITTED_WITH_CONDITIONS; terms=https://www.factset.com/third-party-terms
- GLOBAL_DATAFEEDS: TERMS_NOT_FOUND; automation=PERMITTED_WITH_CONDITIONS; storage=UNKNOWN; derived-use=UNKNOWN; caching=UNKNOWN; terms=not found
- LSEG_DATASCOPE_SELECT: REQUIRES_COMMERCIAL_LICENSE; automation=PERMITTED_WITH_CONDITIONS; storage=PERMITTED_WITH_CONDITIONS; derived-use=PERMITTED_WITH_CONDITIONS; caching=PERMITTED_WITH_CONDITIONS; terms=https://www.lseg.com/en/data-analytics/products/datascope-plus-securities-database
- NSE_DATA_ANALYTICS_LICENSED: REQUIRES_COMMERCIAL_LICENSE; automation=PERMITTED_WITH_CONDITIONS; storage=PERMITTED_WITH_CONDITIONS; derived-use=PERMITTED_WITH_CONDITIONS; caching=PERMITTED_WITH_CONDITIONS; terms=https://www.nseindia.com/static/market-data/nse-data-policy
- NSE_PUBLIC_ARCHIVES: PERSONAL_RESEARCH_ONLY; automation=PROHIBITED; storage=REQUIRES_WRITTEN_PERMISSION; derived-use=REQUIRES_WRITTEN_PERMISSION; caching=REQUIRES_WRITTEN_PERMISSION; terms=https://www.nseindia.com/static/nse-terms-of-use
- TRUEDATA: TERMS_NOT_FOUND; automation=PERMITTED_WITH_CONDITIONS; storage=UNKNOWN; derived-use=UNKNOWN; caching=UNKNOWN; terms=not found
- UPSTOX_HISTORICAL_V3: TERMS_NOT_FOUND; automation=PERMITTED_WITH_CONDITIONS; storage=UNKNOWN; derived-use=UNKNOWN; caching=UNKNOWN; terms=not found
- ZERODHA_KITE_HISTORICAL: PERMITTED_WITH_CONDITIONS; automation=PERMITTED_WITH_CONDITIONS; storage=PROHIBITED; derived-use=UNKNOWN; caching=PERMITTED_WITH_CONDITIONS; terms=https://kite.trade/terms/
Overall Licensing Conclusion: REQUIRES_COMMERCIAL_LICENSE
This is an evidence classification, not legal advice.
PRODUCTION_INFLUENCE=false
```

## Complete Historical Source Recommendation Output

```text
Authoritative Historical Source Recommendation
Total Missing Candidates Evaluated: 657
Source Required Candidates: 608
Recovery-Uncertain Candidates: 49
Providers Assessed: 9
Providers Sampled: 0
Providers Requiring Credentials: 8
Providers Excluded for Licensing or Terms: 5
Best Price-History Source: NSE_DATA_ANALYTICS_LICENSED
Best Historical-Identity Source: LSEG_DATASCOPE_SELECT
Best Corporate-Action Source: NSE_DATA_ANALYTICS_LICENSED
Best Exchange-Authoritative Source: NSE_DATA_ANALYTICS_LICENSED
Provider Status:
- DHAN_HISTORICAL_V2: SECONDARY_VALIDATION_SOURCE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=TERMS_NOT_FOUND
- FACTSET_SYMBOLOGY: IDENTITY_SOURCE_ONLY; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=REQUIRES_COMMERCIAL_LICENSE
- GLOBAL_DATAFEEDS: INSUFFICIENT_EVIDENCE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=TERMS_NOT_FOUND
- LSEG_DATASCOPE_SELECT: IDENTITY_SOURCE_ONLY; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=REQUIRES_COMMERCIAL_LICENSE
- NSE_DATA_ANALYTICS_LICENSED: PRIMARY_SOURCE_CANDIDATE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=REQUIRES_COMMERCIAL_LICENSE
- NSE_PUBLIC_ARCHIVES: RESEARCH_ONLY; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=PERSONAL_RESEARCH_ONLY
- TRUEDATA: INSUFFICIENT_EVIDENCE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=TERMS_NOT_FOUND
- UPSTOX_HISTORICAL_V3: SECONDARY_VALIDATION_SOURCE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=TERMS_NOT_FOUND
- ZERODHA_KITE_HISTORICAL: SECONDARY_VALIDATION_SOURCE; candidate coverage=unavailable/30; symbol coverage=unavailable/27; 2016 coverage=unavailable/16; renamed=unavailable; delisted=unavailable; corporate-actions=unavailable; evidence=DOCUMENTED; license=PERMITTED_WITH_CONDITIONS
Projected Readiness by Provider: unavailable without full-population observations and approved rights.
Projected Readiness Using Approved Combination: unavailable
Remaining Unresolved Candidates: unavailable
Estimated Selection-Bias Reduction: NOT_ESTIMABLE_WITHOUT_OBSERVED_CANDIDATE_COVERAGE
Licensing Conclusion: REQUIRES_COMMERCIAL_LICENSE
Operational-Risk Conclusion: CONTRACT_ENTITLEMENT_AND_FULL_POPULATION_SAMPLE_REQUIRED
Recommended Architecture: Licensed NSE historical/EOD prices and corporate data as the authoritative base; a contracted LSEG identity feed for delisted and renamed continuity; broker APIs only for secondary overlap validation.
Architecture Conclusion: MULTI_SOURCE_ARCHITECTURE_REQUIRED
Next-Step Conclusion: SOURCE_EVIDENCE_INSUFFICIENT
No permanent provider, historical record, reconstruction, classifier, recommendation, approval, timing, stop, target, or production policy changed.
PRODUCTION_INFLUENCE=false
```
