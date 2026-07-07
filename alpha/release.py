"""Project Alpha release metadata and platform health primitives."""

from __future__ import annotations

from dataclasses import dataclass

from alpha.version import __version__


@dataclass(frozen=True, slots=True)
class ProjectAlphaRelease:
    """Immutable public release metadata for Project Alpha."""

    name: str
    version: str
    stage: str
    status: str
    capabilities: tuple[str, ...]
    quality_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_version = self.version.strip()
        normalized_stage = self.stage.strip()
        normalized_status = self.status.strip()

        if not normalized_name:
            raise ValueError("release name cannot be empty")
        if not normalized_version:
            raise ValueError("release version cannot be empty")
        if not normalized_stage:
            raise ValueError("release stage cannot be empty")
        if not normalized_status:
            raise ValueError("release status cannot be empty")
        if len(self.capabilities) == 0:
            raise ValueError("release requires at least one capability")
        if len(self.quality_gates) == 0:
            raise ValueError("release requires at least one quality gate")

        normalized_capabilities = tuple(
            capability.strip() for capability in self.capabilities
        )
        normalized_quality_gates = tuple(gate.strip() for gate in self.quality_gates)

        if any(not capability for capability in normalized_capabilities):
            raise ValueError("release capability cannot be empty")
        if any(not gate for gate in normalized_quality_gates):
            raise ValueError("release quality gate cannot be empty")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "stage", normalized_stage)
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "capabilities", normalized_capabilities)
        object.__setattr__(self, "quality_gates", normalized_quality_gates)

    @property
    def display_name(self) -> str:
        """Return stable human-readable release name."""

        return f"{self.name} v{self.version}"

    def as_lines(self) -> tuple[str, ...]:
        """Return deterministic release summary lines."""

        return (
            f"Name: {self.name}",
            f"Version: {self.version}",
            f"Stage: {self.stage}",
            f"Status: {self.status}",
            "Capabilities:",
            *(f"- {capability}" for capability in self.capabilities),
            "Quality Gates:",
            *(f"- {gate}" for gate in self.quality_gates),
        )


def current_release() -> ProjectAlphaRelease:
    """Return immutable metadata for the current Project Alpha release."""

    return ProjectAlphaRelease(
        name="Project Alpha",
        version=__version__,
        stage="v1.0",
        status="release candidate",
        capabilities=(
            "deterministic backtesting",
            "portfolio accounting",
            "portfolio optimization",
            "objective and constraint evaluation",
            "walk-forward research",
            "parameter sweep research",
            "experiment persistence",
            "research sessions",
            "strategy comparison",
            "professional research reports",
            "research CLI",
        ),
        quality_gates=(
            "pytest",
            "ruff",
            "mypy",
        ),
    )


__all__ = ["ProjectAlphaRelease", "current_release"]
