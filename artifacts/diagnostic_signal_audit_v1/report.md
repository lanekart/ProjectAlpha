# Diagnostic Signal Audit

**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**

- Dataset: HISTORICAL_TRUTH_SNAPSHOT_V1
- Raw BUY/STRONG BUY signals: 78
- Horizons: 1, 5, 10, 20 sessions

## Horizon Outcomes

| Horizon | Observed | Censored | Median forward return |
|---:|---:|---:|---:|
| 1 | 77 | 1 | 0.2946% |
| 5 | 74 | 4 | 0.3744% |
| 10 | 70 | 8 | -1.3717% |
| 20 | 65 | 13 | -2.6753% |

## Scientific Boundary

- Signals failed complete-history eligibility and are diagnostic only.
- Future observations are used only for retrospective outcome evaluation.
- Right-boundary and missing observations are censored, never fabricated.
- No threshold, approval gate, or portfolio policy was changed.

**PRODUCTION_INFLUENCE=false**
