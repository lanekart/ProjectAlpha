# HTR-010B1E1 Contract Consistency Repair

HTR-010B1E1 repairs interval and reporting inconsistencies discovered after the
bridge-aware B1E audit. It remains diagnostic-only and does not change official
factors, raw candles, event boundaries, candidate logic, or production policy.

## Problems repaired

1. B1E converted a missing validation outcome to the literal string `"None"`.
   Certified non-material factor rows therefore fell through to `UNRESOLVED`,
   producing 641 false unresolved intervals in the 2026 audit.
2. The final integrity wrapper recomputed augmented quarantine populations but
   retained pre-augmentation identity counts in `replay_readiness`.
3. The executive report inherited B1C residual labels even after B1E replaced
   the underlying validation outcomes.
4. The readiness JSON exposed `bridge_uncertified_count` but not the stable
   consumer-facing alias `bridge_uncertified_case_count`.

## Contract

- Missing validation outcomes are represented by `None`, never by the string
  `"None"`.
- Certified factor rows without a validation result use an explicit governed
  factor-state fallback. They do not become unresolved merely because the
  event is outside the material continuity-validation population.
- Unknown, ambiguous, and non-multiplicative factor states remain fail-closed.
- A genuinely unresolved admission interval adds
  `UNRESOLVED_ADMISSION_INTERVALS` to readiness blockers.
- Readiness identity counts are refreshed after admission-interval quarantine
  augmentation and must equal quarantine population reconciliation counts.
- Residual attribution is recomputed from the final B1E validation rows. The
  original B1C attribution is retained only as pre-reconciliation evidence.
- `bridge_uncertified_count` and `bridge_uncertified_case_count` must agree.

## Governance

- Official factors remain immutable.
- Raw OHLCV remains immutable.
- Uncertified ISIN and series bridges remain quarantined.
- No benchmark replay is executed.
- `PRODUCTION_INFLUENCE=false`.
