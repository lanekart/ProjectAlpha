# DSI-001 Governed Decision Superiority and Gate Value Audit

DSI-001 is a diagnostic-only audit that measures the observed economic value of institutional rejection gates without changing any production policy.

## Inputs

The first implementation slice consumes three immutable ledgers:

- HTR-010B5 candidate gate forensics;
- HTR-010B5 gate event ledger;
- HTR-010B7 outcome coverage ledger.

Candidates are joined to outcomes by `price_view`, `observed_on`, and `symbol`.

## Attribution

For each rejected candidate, the audit records all failed stable gate codes. A gate is a unique blocker when it is the only observed failed gate. Co-blocked candidates remain explicitly separated.

The single-gate counterfactual asks only whether treating one observed gate as passed would clear all observed failures. It does not rerun or mutate the production decision engine.

## Gate value

For resolved unique-blocker outcomes:

- negative returns contribute avoided-loss benefit;
- positive returns contribute profitable-rejection opportunity cost;
- net gate value equals avoided-loss benefit minus profitable-rejection cost.

Co-blocked outcomes are reported but do not receive unique economic attribution. The audit does not claim causality.

## Governance

The audit never changes thresholds, gate order, recommendation semantics, fingerprint matching, allocation, portfolio policy, execution policy, adaptive runtime publication, or production ledgers.

All recommendation, execution, active-replay, and production influence flags remain false.

## Current boundary

This first slice establishes the gate inventory, immutable candidate and counterfactual ledgers, unique/co-blocked attribution, co-occurrence/Jaccard diagnostics, deterministic artifacts, and focused fixtures. Signed certificate validation, benchmark-relative evidence, confidence intervals, and full real-data acceptance remain required before DSI-001 completion.
