# Alpha Pine Suite v1.0.1 Compilation Hardening

## Scope

This milestone changes Pine generation safety only. It does not change Alpha's
recommendation, approval, allocation, learning, risk, or execution logic.

`PRODUCTION_INFLUENCE=false`

`NO_NEW_STRATEGY_LOGIC=true`

`NO_MANUAL_POST_GENERATION_PATCHING=true`

## Reproduced Failures

The reported Institutional Composite failures are preserved as deterministic
regression fixtures:

- `range = high - low` is rejected because `range` is reserved in Pine.
- a detached `>=` is rejected as a bare expression fragment.
- an assignment ending after `aggressiveAccumulationSignal =` is rejected as a
  dangling expression.

The checked-in v1.0 Institutional source already used `swingRange`, so the exact
old `range` output could not be reconstructed from the current file alone. The
failure was nevertheless possible because v1.0 copied source text without a
reserved-name rewrite or strict pre-write syntax gate. The new generator fixes
that system defect instead of patching generated output.

## Generator Boundary

Before configuration overrides are applied, the renderer now:

1. normalizes source to UTF-8-compatible LF text;
2. extracts Alpha-owned variables, functions, parameters, and loop variables;
3. maps unsafe names to deterministic readable names, including
   `range -> priceRange`;
4. rewrites matching code references outside strings and comments;
5. rejects collisions rather than choosing an ambiguous suffix;
6. applies configuration overrides; and
7. sends the complete result through strict static validation before writing.

Generated output starts with `//@version=6` at byte zero, has no BOM, uses LF,
contains no Markdown fence, and is always self-contained.

## Pine v6 Corrections

- `input.time()` defaults now use the constant-string `timestamp()` overload.
- setup-comparison strategies use fixed order IDs and retain the dynamic setup
  name as the order comment.
- Institutional and Component Audit use `priceRange` consistently.
- the complete aggressive-accumulation assignment remains on one line.
- `na`-initialized persistent values retain explicit types.
- every `request.security()` call explicitly uses
  `barmerge.lookahead_off` and is emitted on one line.

These choices follow TradingView's official documentation for
[identifiers](https://www.tradingview.com/pine-script-docs/language/identifiers/),
[time inputs](https://www.tradingview.com/pine-script-docs/concepts/inputs/), and
[Pine v6 migration](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/).

## Validation Status Model

The suite reports four independent statuses:

- `PYTHON_GENERATION_TESTS`
- `PINE_STATIC_VALIDATION`
- `TRADINGVIEW_MANUAL_COMPILATION`
- `TRADINGVIEW_RUNTIME_SMOKE_TEST`

Static validation is not presented as TradingView compilation. Manual compile
or runtime status remains `USER_VERIFICATION_REQUIRED` until that exact action
has been completed in TradingView.

The latest recorded results are in `PINE_COMPILATION_REPORT.md`.
