# Known Pine Limitations

## Platform Limits

The static validator performs conservative preflight counts for source size,
plot calls, tables, request calls, and declarations. TradingView remains the
authority because several limits depend on plan, compiled tokens, scope, and
runtime behavior.

Official limits currently include:

- 64 plot counts per script;
- up to nine table locations;
- 40 unique `request.*()` calls on most plans and 64 on Ultimate;
- 100,000 compiled tokens per script;
- 1,000 variables per scope;
- a 5 MB compilation request;
- finite compile, execution, loop, and historical-buffer limits.

See TradingView's [Pine limits documentation](https://www.tradingview.com/pine-script-docs/writing/limitations/)
for the current authoritative definitions.

## Static Validation Limits

Static validation can reject known malformed source but cannot prove that
TradingView will compile or run a script. It does not have access to:

- TradingView's parser and type checker;
- compiled-token count;
- account-specific request limits;
- chart-specific history availability;
- runtime memory and execution timing;
- exchange feed entitlements.

The validator's plot-call count is a conservative source count, not the exact
TradingView plot-count calculation. Its declaration count is whole-file, while
TradingView's variable limit is per scope.

## Research Boundary

TradingView chart data can differ from Alpha's Market Truth Engine in symbol
history, corporate actions, point-in-time identity, and historical corrections.
The Pine suite remains an independent secondary validator and must never be
labelled `ALPHA_EXACT`.

`PRODUCTION_INFLUENCE=false`

## TRL Batch And Sector Limits

TradingView cannot authoritatively reconstruct Alpha's point-in-time NIFTY
membership, historical sector classifications, identity continuity, or
corporate-action lineage. TRL therefore executes one declared symbol and
partition at a time. Alpha's typed batch planner and registry perform the
cross-symbol, cross-sector, and distribution analysis.

The four TRL scripts use at most eight explicit `request.security()` calls per
script, below the documented 40 unique-call limit on most plans. Expanding a
single Pine script to request NIFTY 50/100/200 constituents would exceed or
approach plan-dependent request and execution budgets and would still lack
authoritative historical membership. It is intentionally not implemented.

TradingView provides strategy statistics for the chart data it loads, but TRL
has no automated provider export API in this repository. Measured observations
must be transferred through the immutable experiment intake and independently
reviewed. Missing observations remain unavailable.
