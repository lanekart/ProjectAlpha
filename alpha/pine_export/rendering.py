"""Human-readable output for Pine research commands."""

from __future__ import annotations

from alpha.pine_export.models import PineValidationReport, ValidationSeverity
from alpha.pine_export.parity_audit import build_parity_audit, parity_counts


def render_audit() -> str:
    components = build_parity_audit()
    counts = parity_counts(components)
    lines = [
        "Alpha Pine Parity Audit",
        f"Components audited: {len(components)}",
    ]
    lines.extend(f"{parity.value}: {counts[parity]}" for parity in counts)
    lines.extend(
        (
            "",
            "Boundary: TradingView is a secondary validator using chart data.",
            "ALPHA_EXACT: prohibited for this suite.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return "\n".join(lines) + "\n"


def render_validation(report: PineValidationReport, *, strict: bool = False) -> str:
    errors = sum(issue.severity is ValidationSeverity.ERROR for issue in report.issues)
    warnings = len(report.issues) - errors
    lines = [
        "Alpha Pine Static Validation",
        f"Files checked: {report.files_checked}",
        f"Errors: {errors}",
        f"Warnings: {warnings}",
        f"Strict mode: {'Yes' if strict else 'No'}",
    ]
    lines.extend(
        f"{issue.severity.value} {issue.path}"
        f"{f':{issue.line}' if issue.line is not None else ''}: "
        f"{issue.code} - {issue.message}"
        for issue in report.issues
    )
    validation_passed = report.strict_passed if strict else report.passed
    lines.extend(
        (
            f"PINE_STATIC_VALIDATION={'PASS' if validation_passed else 'FAIL'}",
            "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED",
            "TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED",
        )
    )
    return "\n".join(lines) + "\n"


def render_report(report: PineValidationReport) -> str:
    validation = render_validation(report).rstrip()
    return (
        "Alpha Pine Research Suite v1.0.1\n"
        "Purpose: independent validation of Pine-compatible Alpha logic\n"
        "Dataset: TradingView chart data\n"
        "ALPHA_SOURCE_OF_TRUTH=true\n"
        "TRADINGVIEW_IS_SECONDARY_VALIDATOR=true\n"
        "PRODUCTION_INFLUENCE=false\n"
        "NO_LOOKAHEAD=true\n"
        "NO_REPAINTING=true\n"
        "PYTHON_GENERATION_TESTS=NOT_RUN\n"
        "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED\n"
        "TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED\n\n"
        f"{validation}\n"
    )


def render_compilation_checklist() -> str:
    return (
        "Alpha Pine v6 Compilation Checklist\n"
        "1. Run: poetry run python -m alpha pine regenerate\n"
        "2. Run: poetry run python -m alpha pine validate --all --strict\n"
        "3. Compile each generated .pine file in TradingView Pine Editor.\n"
        "4. Smoke test Institutional Composite on NSE:RELIANCE, 1D.\n"
        "5. Use trend 1W, structural 1M, 2017-01-01 through 2021-12-31.\n"
        "6. Keep long-only, pyramiding 0, confirmed bars, regime/sector proxies off.\n"
        "PYTHON_GENERATION_TESTS=NOT_RUN\n"
        "PINE_STATIC_VALIDATION=NOT_RUN\n"
        "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED\n"
        "TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED\n"
        "PRODUCTION_INFLUENCE=false\n"
    )
