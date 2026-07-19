"""Project Alpha Data Value and ROI Audit (DVRA v1.0)."""

from alpha.data_value_audit.dataset_registry import default_dataset_registry
from alpha.data_value_audit.exports import DEFAULT_DVRA_OUTPUT, DataValueAuditExporter
from alpha.data_value_audit.models import (
    DVRA_VERSION,
    PRODUCTION_INFLUENCE,
    BudgetPlan,
    CostAssessment,
    DatasetCandidate,
    DatasetReportCard,
    DataValueAuditReport,
    DependencyEdge,
    InformationGainAssessment,
    ROIClass,
)
from alpha.data_value_audit.roi_engine import DataValueROIEngine


def build_default_audit() -> DataValueAuditReport:
    """Build the complete deterministic audit from the governed registry."""

    return DataValueROIEngine().report(default_dataset_registry())


__all__ = [
    "DEFAULT_DVRA_OUTPUT",
    "DVRA_VERSION",
    "PRODUCTION_INFLUENCE",
    "BudgetPlan",
    "CostAssessment",
    "DataValueAuditExporter",
    "DataValueAuditReport",
    "DataValueROIEngine",
    "DatasetCandidate",
    "DatasetReportCard",
    "DependencyEdge",
    "InformationGainAssessment",
    "ROIClass",
    "build_default_audit",
    "default_dataset_registry",
]
