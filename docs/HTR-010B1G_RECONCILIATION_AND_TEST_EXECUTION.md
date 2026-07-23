# HTR-010B1G Reconciliation and Test Execution

## Scope

HTR-010B1G consumes B1F official bridge certifications and reconciles them against downstream validation and admission artifacts. It does not enable adjusted replay or production influence.

## Expected B1F input

- 24 bridge-case decisions
- 23 certified continuous identities
- 1 governed exclusion (MCX unless separately resolved)
- zero silent assumptions

## B1G outputs

- `htr010b1g_reconciliation_report.json`
- `htr010b1g_propagation_directives.json`
- `htr010b1g_governed_exclusions.json`
- `htr010b1g_executive_report.md`

Each bridge case receives an explicit reconciliation state. Certified cases may require downstream admission-state rebuild. Unresolved cases must remain quarantined.

## Test execution policy

Development loops should use the smallest safe gate:

- `make validate-fast`: Ruff plus conservatively selected affected tests
- `make test-b1g`: B1G unit, CLI and integration tests
- `make test-historical-truth`: full historical-truth subsystem
- `make validate-milestone`: Ruff, MyPy and historical-truth subsystem
- `make test-full`: complete repository suite, required once at milestone completion and again in CI before merge

The affected-test selector fails conservatively to the full suite when shared contracts, CLI registration, configuration, unknown source paths or other high-blast-radius files change.

## CI policy

CI retains full repository coverage but shards tests into independent jobs:

1. historical truth
2. historical replay and recovery
3. decision and market intelligence
4. portfolio, backtest, execution and costs
5. research and trading signals
6. remaining tests

Lint and strict type checking run independently from test shards.

## Guardrails

- no benchmark replay
- no adjusted replay activation
- no production policy change
- MCX remains excluded until official pre-identity evidence is available
- `PRODUCTION_INFLUENCE=false`
