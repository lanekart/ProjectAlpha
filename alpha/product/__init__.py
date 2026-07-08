"""Product-facing reporting and export infrastructure.

The product package owns presentation primitives only. It must remain independent
from trading, market, recommendation, and portfolio domain engines.
"""

from __future__ import annotations

from alpha.product.artifacts import ProductArtifact, ProductExportManifest
from alpha.product.export import ProductExportResult, ProductExportService
from alpha.product.rendering import ProductTextRenderer
from alpha.product.reports import (
    ProductReport,
    ProductReportMetadata,
    ProductReportSection,
)
from alpha.product.serialization import ProductJsonSerializer, ProductTextSerializer

__all__ = [
    "ProductArtifact",
    "ProductExportManifest",
    "ProductExportResult",
    "ProductExportService",
    "ProductJsonSerializer",
    "ProductReport",
    "ProductReportMetadata",
    "ProductReportSection",
    "ProductTextRenderer",
    "ProductTextSerializer",
]
