import pytest

from alpha.release import ProjectAlphaRelease, current_release
from alpha.version import __version__


def test_current_release_exposes_v1_metadata() -> None:
    release = current_release()

    assert release.name == "Project Alpha"
    assert release.version == __version__
    assert release.stage == "v1.0"
    assert release.status == "release candidate"
    assert release.display_name == "Project Alpha v1.0.0"
    assert "deterministic backtesting" in release.capabilities
    assert "research CLI" in release.capabilities
    assert release.quality_gates == ("pytest", "ruff", "mypy")


def test_release_summary_lines_are_deterministic() -> None:
    release = current_release()

    assert release.as_lines() == (
        "Name: Project Alpha",
        "Version: 1.0.0",
        "Stage: v1.0",
        "Status: release candidate",
        "Capabilities:",
        "- deterministic backtesting",
        "- portfolio accounting",
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
    )


def test_release_value_object_validates_inputs() -> None:
    with pytest.raises(ValueError, match="release name"):
        ProjectAlphaRelease(
            name=" ",
            version="1.0.0",
            stage="v1.0",
            status="release candidate",
            capabilities=("research",),
            quality_gates=("pytest",),
        )
