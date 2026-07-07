from alpha.release import ProjectAlphaRelease, current_release
from alpha.version import __version__


def test_current_release_exposes_v1_2_metadata() -> None:
    release = current_release()

    assert release.name == "Project Alpha"
    assert release.version == __version__
    assert release.stage == "v1.2"
    assert release.status == "engineering"
    assert release.display_name == f"Project Alpha v{__version__}"
    assert "deterministic backtesting" in release.capabilities
    assert "financial accounting model" in release.capabilities
    assert "explainable JSON exports" in release.capabilities
    assert "poetry build" in release.quality_gates


def test_release_summary_lines_are_deterministic() -> None:
    release = current_release()

    assert release.as_lines() == (
        "Name: Project Alpha",
        "Version: 1.2.0",
        "Stage: v1.2",
        "Status: engineering",
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
        "Quality Gates:",
        "- pytest",
        "- ruff",
        "- mypy",
        "- poetry build",
    )


def test_release_rejects_invalid_metadata() -> None:
    try:
        ProjectAlphaRelease(
            name=" ",
            version="1.2.0",
            stage="v1.2",
            status="engineering",
            capabilities=("deterministic backtesting",),
            quality_gates=("pytest",),
        )
    except ValueError as exc:
        assert str(exc) == "release name cannot be empty"
    else:
        raise AssertionError("Expected invalid release metadata to fail")
