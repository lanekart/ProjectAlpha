# Historical Truth Risk Register

**Register version:** `HISTORICAL_TRUTH_RISKS_1.0`  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

Severity and likelihood are qualitative design assessments. They are not measured
failure probabilities.

| ID | Risk | Failure mechanism | Impact | Severity | Detection | Required control | Promotion gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HT-001 | Survivorship bias | Today's securities or constituents are projected into earlier dates | Inflated replay quality and missing failed/delisted names | Critical | PIT universe audit and future-constituent leak test | Effective-dated listings, index membership, delistings, and explicit unknowns | Zero unexplained future-constituent leaks |
| HT-002 | Symbol reuse | Same ticker maps to different securities across time | Joins unrelated histories and outcomes | Critical | Effective-interval overlap and ISIN/security-code checks | Permanent Alpha security ID; ticker is an alias only | Zero ambiguous promoted identities |
| HT-003 | Symbol/name changes | History fragments at rename or uses future alias | False missing history and wrong feature windows | High | Change-event reconciliation | Official effective-dated alias history | All promoted rows resolve to valid alias on session |
| HT-004 | ISIN changes | Split, consolidation, merger, or scheme replaces ISIN | Broken lineage and double-counted securities | Critical | Exchange/depository/action cross-check | Effective-dated ISIN and predecessor/successor graph | No unresolved action-related identity change |
| HT-005 | Merger/demerger ambiguity | Complex consideration or multiple successors incompletely modeled | Invalid return continuity and universe lineage | Critical | Action-term completeness and lineage-cycle tests | Preserve raw event; manual reconciliation; no factor until complete | Complex unresolved events excluded from adjusted views |
| HT-006 | Corporate-action omission | Price jumps are treated as returns | Distorted features, stops, targets, and outcomes | Critical | Exchange/depository event coverage around discontinuities | Versioned action ledger; raw and adjusted modes | Mandatory action coverage passes for adjusted release |
| HT-007 | Wrong adjustment timing | Later-known action applied before announcement/effective date | Point-in-time leakage | Critical | Knowledge-time replay test | Bitemporal event and factor tables | Zero future action leakage |
| HT-008 | Delisting/suspension gaps | Missing bars interpreted as no signal or security removed early | Survivorship and liquidity bias | Critical | Listing-state vs missing-observation attribution | Official status intervals and unresolved state | Unknown intervals disclosed; no fabricated eligibility |
| HT-009 | Current-only backfill | Current sectors, types, or index members copied backward | Hidden hindsight in research cohorts | Critical | Truth-class and effective-date validation | `CURRENT_ONLY` truth class with historical-use veto | Zero current-only historical promotions |
| HT-010 | Source format drift | UDiFF/legacy schema change parsed under old rules | Silent column shift or unit corruption | Critical | Schema fingerprint and row/domain tests | Parser per source/era; unknown schema quarantine | Every object matches an approved schema version |
| HT-011 | Partial file accepted | Network or provider returns truncated report | Missing securities misread as market state | High | Size, checksum, trailer, row count, and source totals | Atomic downloads and finalization watermark | No partial object marked complete |
| HT-012 | Duplicate/revision confusion | Corrected file overwrites or coexists without lineage | Non-reproducible replays | High | Content and natural-key duplicate checks | Immutable raw objects and supersession graph | One selected revision per knowledge cutoff |
| HT-013 | NSE/BSE conflation | Venue prices combined before modeling venue | False mismatch or fabricated consolidated close | High | Venue-key completeness test | Keep venue facts separate; derived consolidation only | No canonical fact without venue |
| HT-014 | Volume unit mismatch | Shares, lots, deliverables, and auction quantities mixed | False liquidity/volume signals | High | Unit/schema and report-total reconciliation | Typed measures and market/series scope | Zero unresolved unit conversion in promoted fields |
| HT-015 | Calendar error | Weekends, holidays, special/muhurat sessions inferred incorrectly | Missing-day errors and shifted returns | High | Official calendar vs report-presence audit | Versioned venue/segment session calendar | All expected sessions classified |
| HT-016 | Publication-time uncertainty | Retrieval time used as if it were availability time | Look-ahead leakage | Critical | Source publication SLA and knowledge-time completeness | Exact time where available; bounded approximation truth/reason code | PIT-certified views have documented knowledge time |
| HT-017 | Identity overmatching | Fuzzy names or ticker similarity auto-link entities | Catastrophic history contamination | Critical | Candidate multiplicity and manual gold cases | Fuzzy matches remain inferred/quarantined | No fuzzy-only canonical identity |
| HT-018 | Exchange/depository disagreement | Venue and depository publish different ISIN/action state | Wrong permanent mapping | Critical | Field-authority reconciliation case | Preserve both; resolve effective times and event terms | No unresolved official identity conflict |
| HT-019 | Missing historical sector | Current industry taxonomy used as history | Regime/sector attribution leakage | High | Effective-date coverage report | Unknown sector or licensed PIT classification | Historical sector use requires evidence window |
| HT-020 | Missing index history | Current Nifty members assumed historical | Biased benchmarks and universe | Critical | Constituent effective-date audit | Licensed historical constituents plus release cross-check | Index-conditioned replay blocked until coverage passes |
| HT-021 | Legal/rights uncertainty | Public files retained or automated beyond permission | Contract, exchange, and operational risk | Critical | Source authorization audit | Written rights and no-redistribution controls | Every raw object links to valid authorization |
| HT-022 | Source outage/rate limit | Incremental acquisition silently falls behind | Stale warehouse and incomplete latest session | High | Freshness and expected-object monitor | Fail closed; bounded retries; explicit stale state | No incomplete session published as final |
| HT-023 | Legacy mismatch hidden by aggregate rate | Small mismatch share contains material events/names | False confidence | High | Stratify by action, delisting, year, and security | Critical-event vetoes plus row-rate metrics | No critical unresolved case regardless of aggregate match |
| HT-024 | Inference presented as fact | Derived listing date/factor loses method label | Users over-trust synthetic history | High | Field truth-envelope validation | Closed truth classes and inference version | No inferred field labeled official |
| HT-025 | Restatement erases prior knowledge | Correction rewrites old replay evidence | Non-reproducible decisions | Critical | Release lineage and bitemporal tests | Immutable releases and knowledge cutoff | Prior release remains addressable |
| HT-026 | Security type contamination | Debt, ETF, preference, warrants treated as common equity | Invalid universe and signals | High | Instrument/series eligibility audit | Official type history and versioned universe policy | Unknown type excluded from equity-eligible universe |
| HT-027 | Stale mapping interval | Open-ended identity/sector interval survives a known change | Incorrect post-change classification | High | Change-event boundary and interval-overlap checks | Close intervals when events arrive; revision release | No overlapping or contradicted active intervals |
| HT-028 | False confidence aggregation | Millions of price rows mask absent identity/index/action history | Premature institutional certification | Critical | Component-level release confidence | Worst mandatory component controls release grade | Required components individually pass |
| HT-029 | Corrupt backup | Raw vault cannot be reconstructed after loss | Irrecoverable provenance and release failure | Critical | Periodic checksum restore drill | Encrypted versioned backups and tested restore | Successful clean-room restore before certification |
| HT-030 | Vendor exit lock-in | Rights end or export is incomplete | History becomes unusable or non-reproducible | High | Contract/expiry register and exit test | Retention/export/deletion terms before purchase | Exit plan approved with each source |

## Highest-Priority Unknowns

1. Exact earliest and continuous coverage for official bulk NSE/BSE products.
2. Complete inactive-security, listing, suspension, relisting, and delisting history.
3. Effective-dated Nifty constituent and sector history.
4. Full merger/demerger and old/new ISIN lineage.
5. Written retention and internal derived-research rights for each selected source.

These unknowns block institutional certification but do not invalidate the existing
warehouse for clearly labeled diagnostic research.

## Ownership Model for Future Implementation

| Risk family | Accountable function |
| --- | --- |
| Source rights and vendor exit | CTO + legal/procurement owner |
| Identity, listings, and corporate actions | Data engineering + research data steward |
| Point-in-time and survivorship | Research methodology owner |
| Reconciliation and confidence | Data quality owner |
| Release promotion | Independent data-release approver |
| Production selection | Separate investment/risk governance; outside this milestone |

No single engineer should both waive a critical exception and approve the resulting
canonical release.
