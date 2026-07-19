# Upstox Historical Evidence Trial Implementation Report

1. **Files changed:** `.env.example`, `alpha/cli.py`,
   `alpha/historical_replay/__init__.py`,
   `alpha/historical_replay/upstox_historical_probe.py`,
   `alpha/historical_replay/upstox_historical_probe_service.py`,
   `docs/UPSTOX_HISTORICAL_EVIDENCE_TRIAL.md`, and
   `tests/historical_replay/test_upstox_historical_probe.py`.
2. **Architecture:** an isolated typed probe composes the immutable source
   manifest, exact identity resolver, GET-only client, point-in-time candle
   validator, cautious adjustment audit, sanitized evidence repository, and
   aggregate report engine. It is not a production provider.
3. **Endpoints used:** the transport permits only Instrument Search GET
   `/v2/instruments/search` and Historical Candle V3 GET
   `/v3/historical-candle/{instrument_key}/days/1/{to_date}/{from_date}`.
4. **Credential security:** only `UPSTOX_ANALYTICS_TOKEN` is read. There is no
   fallback to the trading token. The credential is hidden from repr, errors,
   hashes, persistence, exports, and diagnostics. Non-live mode makes no network
   call.
5. **Tests added:** 46 deterministic tests cover authentication and redaction,
   endpoint restriction, exact identity hierarchy, renamed/inactive/current-only
   cases, 121-bar cutoffs, 2016 depth, invalid data, retries, adjustment cases,
   sanitized resume, CLI safeguards, exports, manifest integrity, and production
   isolation.
6. **Validation:** `poetry run pytest` passed 1,425 tests in 140.73 seconds;
   `poetry run ruff check .` passed; `poetry run mypy alpha` passed across 364
   source files; `poetry build` produced the source and wheel distributions.
7. **CLI commands:** `upstox-auth-probe`, `upstox-historical-sample`,
   `upstox-historical-coverage`, `upstox-identity-coverage`,
   `upstox-adjustment-audit`, and `upstox-evidence-report` are available under
   `alpha replay` with explicit live, sample/full, filters, resume, dry-run, and
   text/JSON/CSV controls.
8. **Authentication result:** `UPSTOX_ANALYTICS_TOKEN` was not configured.
   Status is `TOKEN_NOT_CONFIGURED`; no provider request was made.
9. **Trial sample composition:** the deterministic 30-row plan contains 16
   candidates from 2016; later years through 2026; 8 corporate-action, 13
   insufficient-lookback, 1 short-history, 5 multi-gap, and 3 partial-lookback
   cases; 24 momentum, 4 trend-failure, and 2 distribution setups; 29 neutral
   and 1 negative regimes; 14 late, 12 forming, and 4 preferred-entry states.
10. **Symbols tested:** zero, because the dedicated credential was absent. The
    full 657-candidate trial was not run.
11. **Identity-resolution results:** zero resolved and zero unresolved empirical
    observations. Mock tests prove the hierarchy, but are not presented as
    provider evidence.
12. **Historical-symbol results:** unavailable empirically. Current-symbol-only
    matching is rejected by policy.
13. **Inactive and renamed-symbol results:** unavailable empirically. Both are
    represented separately and require continuity evidence.
14. **Candidates with 121 usable bars:** zero tested; no coverage rate is
    fabricated.
15. **2016 coverage:** 0/0 tested.
16. **Later-year coverage:** 0/0 tested.
17. **Missing-session findings:** unavailable without observed bars and an
    authoritative exchange-session calendar. Weekday gaps are not mislabeled as
    provider gaps.
18. **Adjustment findings:** `INSUFFICIENT_EVIDENCE`. Smooth prices are not
    treated as proof of adjustment.
19. **Corporate-action findings:** `INSUFFICIENT_EVIDENCE`; an independent
    effective-dated authoritative source remains required.
20. **Price-coverage result:** unavailable; observed and projected rates are not
    reported without empirical observations.
21. **Full-readiness result:**
    `BLOCKED_IDENTITY_CORPORATE_ACTION_OR_COVERAGE_INCOMPLETE`.
22. **Selection-bias implication:** the difficult stratified sample is not a
    probability sample, so even a future sample rate must not be projected to
    the 657-row population.
23. **Recommended Upstox source role:** `EMPIRICAL_TRIAL_ONLY` until a live sample
    supplies evidence; authentication alone will not justify integration.
24. **Exact conclusion:** `UPSTOX_CREDENTIALS_NOT_CONFIGURED`.
25. **Secret confirmation:** no Analytics Token was printed, logged, persisted,
    exported, or hashed. No token was present to expose in this run.
26. **Policy confirmation:** no production provider, historical archive,
    breakout reconstruction, classifier, recommendation, approval, entry timing,
    stop, target, order API, or production policy was changed.

## Authentication Evidence

```text
Upstox Read-Only Authentication Probe
Credential Status: CREDENTIALS_NOT_CONFIGURED
Authentication Status: TOKEN_NOT_CONFIGURED
Instrument Search: NOT_TESTED
Historical Candle V3: NOT_TESTED
Analytics Token Only: yes
Account Endpoint Called: no
Order Endpoint Called: no
Static IP Required for Selected Endpoints: no
HTTP Status: unavailable
Provider Error Code: unavailable
Reason: UPSTOX_ANALYTICS_TOKEN is not configured.
PRODUCTION_INFLUENCE=false
```

## Historical Evidence

```text
Upstox Historical Evidence Trial Report
Credential Status: CREDENTIALS_NOT_CONFIGURED
API Authentication Status: PROBE_NOT_RUN
Manifest Candidates: 657
Trial Candidates: 0
Historical Symbols Tested: 0
Instruments Resolved / Unresolved: 0 / 0
Active / Historical / Inactive / Renamed Resolution: 0 / 0 / 0 / 0
Candidates with 121 Usable Bars: 0
Partial / No History: 0 / 0
2016 Coverage: 0/0
Later-Year Coverage: 0/0
Missing-Session Rate: unavailable
Invalid-Series Count: 0
Adjustment Conclusion: INSUFFICIENT_EVIDENCE
Corporate-Action Conclusion: INSUFFICIENT_EVIDENCE
Observed Price-Coverage Rate: unavailable
Projected Price Coverage: unavailable
Full Reconstruction Readiness: BLOCKED_IDENTITY_CORPORATE_ACTION_OR_COVERAGE_INCOMPLETE
Selection-Bias Implication: The deterministic stratified sample includes difficult historical cases, but it is not a probability sample; do not project its coverage unless the full manifest is tested.
Recommended Upstox Source Role: EMPIRICAL_TRIAL_ONLY
Exact Conclusion: UPSTOX_CREDENTIALS_NOT_CONFIGURED
Sample Composition: entry_timing=LATE_ENTRY=14, entry_timing=PREFERRED_ENTRY=4, entry_timing=SETUP_FORMING=12, gap=CORPORATE_ACTION_AMBIGUITY=8, gap=INSUFFICIENT_PRE_CANDIDATE_LOOKBACK=13, gap=LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY=1, gap=MULTI_SESSION_GAP=5, gap=PARTIAL_LOOKBACK_AVAILABLE=3, regime=NEGATIVE=1, regime=NEUTRAL=29, setup=DISTRIBUTION=2, setup=MOMENTUM CONTINUATION=24, setup=TREND FAILURE=4, year=2016=16, year=2017=1, year=2018=2, year=2019=2, year=2020=1, year=2021=1, year=2022=1, year=2023=1, year=2024=1, year=2025=2, year=2026=2
Limitations:
- Price coverage is separate from identity and corporate-action readiness.
- Missing-session rates are unavailable without an authoritative exchange calendar.
- Response rows and checksums are not persisted because storage terms remain unverified.
- PRODUCTION_INFLUENCE=false; Upstox is not registered as a production provider.
PRODUCTION_INFLUENCE=false
```
