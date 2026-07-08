from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from alpha.product.artifacts import ProductArtifact, ProductExportManifest
from alpha.product.reports import ProductReport
from alpha.product.serialization import ProductJsonSerializer, ProductTextSerializer


@dataclass(frozen=True, slots=True)
class ProductExportResult:
    """Immutable result describing a product report export operation."""

    json_path: Path | None = None
    text_path: Path | None = None
    manifest: ProductExportManifest = field(
        default_factory=lambda: ProductExportManifest(())
    )

    def __post_init__(self) -> None:
        artifacts: list[ProductArtifact] = []

        if self.json_path is not None:
            artifacts.append(ProductArtifact(kind="json", path=self.json_path))

        if self.text_path is not None:
            artifacts.append(ProductArtifact(kind="text", path=self.text_path))

        object.__setattr__(self, "manifest", ProductExportManifest(tuple(artifacts)))

    @property
    def wrote_any(self) -> bool:
        return not self.manifest.is_empty


@dataclass(frozen=True, slots=True)
class ProductExportService:
    """Shared deterministic export pipeline for product reports."""

    json_serializer: ProductJsonSerializer = ProductJsonSerializer()
    text_serializer: ProductTextSerializer = ProductTextSerializer()

    def export(
        self,
        report: ProductReport,
        *,
        json_path: Path | None = None,
        text_path: Path | None = None,
    ) -> ProductExportResult:
        written_json_path: Path | None = None
        written_text_path: Path | None = None

        if json_path is not None:
            self._ensure_supported_path(path=json_path, expected_suffix=".json")
            self._ensure_parent_directory(json_path)
            json_path.write_text(
                self.json_serializer.serialize(report),
                encoding="utf-8",
            )
            written_json_path = json_path

        if text_path is not None:
            self._ensure_supported_path(path=text_path, expected_suffix=".txt")
            self._ensure_parent_directory(text_path)
            text_path.write_text(
                self.text_serializer.serialize(report),
                encoding="utf-8",
            )
            written_text_path = text_path

        return ProductExportResult(
            json_path=written_json_path,
            text_path=written_text_path,
        )

    def _ensure_supported_path(self, *, path: Path, expected_suffix: str) -> None:
        if path.suffix.lower() != expected_suffix:
            raise ValueError(f"expected {expected_suffix} output path")

    def _ensure_parent_directory(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)


__all__ = ["ProductExportResult", "ProductExportService"]
