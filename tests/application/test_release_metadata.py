from alpha.release import ProjectAlphaRelease, current_release
from alpha.version import __version__


def test_current_release_exposes_v1_3_product_validation_metadata() -> None:
    release = current_release()

    assert release.name == "Project Alpha"
    assert release.version == __version__
    assert release.stage == "v1.3-production-validation"
    assert release.status == "production validation"
    assert release.display_name == f"Project Alpha v{__version__}"
    assert "deterministic backtesting" in release.capabilities
    assert "recommendation intelligence" in release.capabilities
    assert "portfolio intelligence" in release.capabilities
    assert "capital allocation engine" in release.capabilities
    assert "runtime validation" in release.quality_gates
    assert "user acceptance testing" in release.quality_gates
    assert "poetry build" in release.quality_gates


def test_release_summary_lines_are_deterministic() -> None:
    release = current_release()

    assert release.as_lines() == (
        "Name: Project Alpha",
        "Version: 1.3.0-dev",
        "Stage: v1.3-production-validation",
        "Status: production validation",
        "Capabilities:",
        "- deterministic market data engine",
        "- NSE providers",
        "- UDiFF integration",
        "- deterministic backtesting",
        "- financial accounting model",
        "- execution ledger",
        "- position accounting",
        "- portfolio reconciliation",
        "- explainable backtest results",
        "- equity curve builder",
        "- equity-driven performance analytics",
        "- explainable JSON exports",
        "- explainable text reports",
        "- portfolio optimization",
        "- objective and constraint evaluation",
        "- walk-forward research",
        "- parameter sweep research",
        "- experiment persistence",
        "- research sessions",
        "- strategy comparison",
        "- professional research reports",
        "- research CLI",
        "- trading signal intelligence",
        "- market digital twin",
        "- market intelligence engines",
        "- historical probability engine",
        "- recommendation intelligence",
        "- portfolio intelligence",
        "- capital allocation engine",
        "- explainable allocation reports",
        "Quality Gates:",
        "- pytest",
        "- ruff",
        "- mypy",
        "- poetry build",
        "- runtime validation",
        "- user acceptance testing",
    )


def test_release_rejects_invalid_metadata() -> None:
    try:
        ProjectAlphaRelease(
            name=" ",
            version="1.3.0-dev",
            stage="v1.3-production-validation",
            status="production validation",
            capabilities=("deterministic backtesting",),
            quality_gates=("pytest",),
        )
    except ValueError as exc:
        assert str(exc) == "release name cannot be empty"
    else:
        raise AssertionError("Expected invalid release metadata to fail")
