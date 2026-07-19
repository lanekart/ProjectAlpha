"""Application service for Pine strategy export."""

from __future__ import annotations

from pathlib import Path

from alpha.pine_export.models import PineExportConfig
from alpha.pine_export.pine_renderer import STRATEGY_FILES, PineRenderer
from alpha.pine_export.validation import PineStaticValidator


class PineStrategyExporter:
    """Export a deterministic, self-contained Pine strategy."""

    def __init__(
        self,
        repository_root: Path | None = None,
        renderer: PineRenderer | None = None,
    ) -> None:
        self.repository_root = repository_root or Path(__file__).resolve().parents[2]
        self.renderer = renderer or PineRenderer(self.repository_root)

    def export(
        self,
        config: PineExportConfig,
        output: Path | None = None,
    ) -> Path:
        filename = STRATEGY_FILES.get(config.strategy)
        if filename is None:
            self.renderer.render(config)
            raise RuntimeError("renderer accepted an unknown strategy")
        output_path = output or (
            self.repository_root / "tradingview" / "generated" / filename
        )
        source = self.renderer.render(config)
        validation = PineStaticValidator().validate_source_result(output_path, source)
        if not validation.passed(strict=True):
            details = "; ".join(
                f"{issue.code}: {issue.message}" for issue in validation.issues
            )
            raise ValueError(f"refusing to export invalid Pine source: {details}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(source.encode("utf-8"))
        return output_path
