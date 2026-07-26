# DSI-009 Governed Entry Timing and Stop-Loss Improvement

## Purpose

DSI-009 is an offline, candidate-independent research package that reconstructs
the accepted DSI-008 portfolio and evaluates whether executable entry timing or
stop placement can improve benchmark-relative wealth.

It does not change recommendation, approval, portfolio, execution, learning, or
live behavior. `PRODUCTION_INFLUENCE=false`.

## Source Boundary

DSI-009 requires:

1. The accepted DSI-008 certificate and all hash-bound support artifacts.
2. The accepted DSI-007 certificate and its signed fold/regime strategy
   selection ledger.
3. The governed adjusted historical market database.

The DSI-008 signal ledger contains the complete outer-fold strategy population.
It is not itself the selected portfolio population. DSI-009 therefore applies
the signed DSI-007 fold/regime selection policy, including explicit `NO_TRADE`
cells, before reconstructing the incumbent. The reconstructed incumbent must
match the signed 56-trade portfolio, ending capital, CAGR, and drawdown within
the frozen reconciliation tolerances. The certificate preserves the signed
DSI-008 incumbent summary unchanged and stores the reconstructed metrics in a
separate audit field so numerical reconciliation cannot rewrite the baseline.

## A-I Workflow

### A: Trade paths

Reconstructs every incumbent entry, exit, target, stop, holding period, MFE,
MAE, post-stop path, and benchmark-relative excursion. Signal-path diagnostics
are stored separately from executed portfolio trades.

### B: Diagnostic attribution

Assigns one mutually exclusive primary label and retains overlapping diagnostic
labels. These labels describe mechanical historical paths; they are not causal
claims.

### C: Bounded entry registry

The registry contains a small set of interpretable, pre-registered mechanisms:

- incumbent next-session open;
- close confirmation;
- retest and hold;
- 0.5 ATR pullback limit;
- maximum 1 ATR extension;
- maximum 2% positive gap;
- non-unknown regime confirmation.

Every fill obeys point-in-time eligibility. Delayed entries execute no earlier
than the next eligible open after confirmation. A limit that is never touched
does not fill. A stop breached before a delayed trigger invalidates the trade.
Stops and targets remain frozen while entry mechanisms are compared.

### D: Entry tournament

All non-entry mechanisms remain fixed. Results are reported by outer fold.
Because DSI-008 has already consumed the comparison period and no fresh unused
holdout exists, descriptive improvements cannot become accepted champions.

### E: Stop value

Incumbent stopped trades receive mechanical no-stop and post-stop diagnostics,
including later loss, later gain, target recovery, additional drawdown, and
capital tie-up. No-stop paths remain counterfactual diagnostics.

### F: Stop tournament

Stop variants are evaluated only after the entry policy is frozen. The bounded
registry includes incumbent, ATR, structural, volatility-adjusted structural,
and maximum-risk alternatives. Position-size basis and frozen entry lineage are
reported explicitly.

### G: Wealth comparison

The report compares the frozen incumbent, accepted entry or stop champions when
available, the sequential champion when valid, and Nifty 500 TRI. The benchmark
cannot be mistaken for an improved Alpha portfolio.

### H: Accuracy and robustness

Standard, High-Conviction, and newly defined Elite populations report their
accuracy definition, Wilson interval, expectancy, sample, concentration, and
wealth contribution. The rejected DSI-008 Elite tier is not reused. A tiny
sample or high accuracy with negative expectancy cannot establish the 75%
target.

### I: Certification

The final certificate binds source hashes, all 24 support artifacts, the
executive report, readiness, blockers, governance flags, and automatic
promotion count.

## CLI

Run:

```text
poetry run python -m alpha benchmark \
  decision-superiority-entry-stop-improvement \
  --dsi008-certificate <PATH> \
  --dsi007-certificate <PATH> \
  --database <PATH> \
  --output <PATH>
```

Verify:

```text
poetry run python -m alpha benchmark \
  decision-superiority-entry-stop-improvement-verify \
  --certificate <PATH> \
  --require-ready
```

`--require-ready` verifies structural research readiness. It does not imply
economic superiority, forward-paper eligibility, or production promotion.

## Artifact Integrity

The package contains 24 CSV ledgers, one Markdown report, and one JSON
certificate. CSV schemas and ordering are deterministic. The certificate stores
the SHA-256 of every support artifact and a canonical payload hash. Validation
rejects missing files, path traversal, machine-local paths, modified bytes,
governance changes, and nonzero automatic promotion.

## Interpretation Limits

- DSI-009 is not a causal study.
- No best historical entry is selected trade by trade.
- Unfilled orders remain unfilled.
- Skipped winners and opportunity cost remain visible.
- Entry and stop selection are not performed jointly.
- A fresh unused final holdout is unavailable after DSI-008.
- Descriptive improvements cannot activate live or default mechanisms.
- The Nifty 500 comparison is the governed total-return benchmark.

## Governance

All production-influence flags are false. DSI-009 permits only offline research
and, when every stated condition is met, a future human-approved forward-paper
experiment. It never promotes a mechanism automatically.
