# TRL Candidate Promotion Example

## Unmeasured Candidate

```text
TRL Candidate Promotion
Experiment ID: trl-example-unmeasured
Decision: REJECT
Promote: NO
Failed Gates: MISSING_DEVELOPMENT, MISSING_VALIDATION, MISSING_HOLDOUT,
MISSING_COMPARABLE_METRICS
Reject. The configuration remains research evidence and cannot enter Alpha
replay until every declared gate passes.
PRODUCTION_INFLUENCE=false
```

## Meaning Of A Pass

When all gates pass, the only possible positive decision is:

```text
Decision: PROMOTE_TO_ALPHA_REPLAY
```

That decision does not mean `PROMOTE_TO_PRODUCTION`, does not modify any Alpha
weight or threshold, and does not approve a trade. It means the frozen
configuration has earned a more authoritative test using Alpha's replay,
walk-forward, point-in-time identity, corporate-action, and Market Truth Engine
controls.

## Rejection Is Useful

Rejected variants remain registered so selection bias can be audited. A
configuration that improves a single chart, one sector, development only, or
expectancy at the cost of worse drawdown is not an Alpha candidate.

`PRODUCTION_INFLUENCE=false`

