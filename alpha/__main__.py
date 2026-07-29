from __future__ import annotations

import sys

import typer


def _historical_truth_app() -> typer.Typer:
    from alpha.historical_truth import (
        official_bridge_evidence_certification_bundle_cli as bridge_evidence_bundle_cli,
    )
    from alpha.historical_truth.adjustment_replay_admission_cli import (
        adjustment_replay_admission_certify,
    )
    from alpha.historical_truth.bridge_aware_admission_reconciliation_cli import (
        bridge_aware_admission_reconcile,
    )
    from alpha.historical_truth.bridge_aware_factor_validation_repair_cli import (
        bridge_aware_factor_validation_repair,
    )
    from alpha.historical_truth.cli import historical_truth_app
    from alpha.historical_truth.factor_transformation_bridge_forensics_cli import (
        factor_transformation_bridge_forensics,
    )
    from alpha.historical_truth.factor_transformation_forensics_cli import (
        factor_transformation_forensics,
    )
    from alpha.historical_truth.final_official_evidence_closure_cli import (
        final_official_evidence_closure_certify,
    )
    from alpha.historical_truth.final_pre2016_adjusted_history_closure_cli import (
        final_pre2016_adjusted_history_closure_certify,
    )
    from alpha.historical_truth.official_bridge_certification_cli import (
        official_bridge_certify,
        official_bridge_evidence_acquire,
        official_bridge_evidence_discovery_registry,
        official_bridge_evidence_dossiers,
        official_bridge_evidence_manifest,
        official_bridge_evidence_materialize,
    )
    from alpha.historical_truth.official_bridge_completion_cli import (
        official_bridge_complete,
    )
    from alpha.historical_truth.official_bridge_document_downloader_cli import (
        official_bridge_document_download,
    )
    from alpha.historical_truth.official_bridge_evidence_population_cli import (
        official_bridge_evidence_populate,
    )
    from alpha.historical_truth.residual_corporate_action_closure_cli import (
        residual_corporate_action_closure_certify,
    )
    from alpha.historical_truth.session_calendar_extension_cli import (
        session_calendar_extend_certify,
    )

    registered = {command.name for command in historical_truth_app.registered_commands}
    if "adjustment-replay-admission-certify" not in registered:
        historical_truth_app.command("adjustment-replay-admission-certify")(
            adjustment_replay_admission_certify
        )
    if "session-calendar-extend-certify" not in registered:
        historical_truth_app.command("session-calendar-extend-certify")(
            session_calendar_extend_certify
        )
    if "factor-transformation-forensics" not in registered:
        historical_truth_app.command("factor-transformation-forensics")(
            factor_transformation_forensics
        )
    if "factor-transformation-bridge-forensics" not in registered:
        historical_truth_app.command("factor-transformation-bridge-forensics")(
            factor_transformation_bridge_forensics
        )
    if "bridge-aware-factor-validation-repair" not in registered:
        historical_truth_app.command("bridge-aware-factor-validation-repair")(
            bridge_aware_factor_validation_repair
        )
    if "bridge-aware-admission-reconcile" not in registered:
        historical_truth_app.command("bridge-aware-admission-reconcile")(
            bridge_aware_admission_reconcile
        )
    if "residual-corporate-action-closure-certify" not in registered:
        historical_truth_app.command("residual-corporate-action-closure-certify")(
            residual_corporate_action_closure_certify
        )
    if "final-pre2016-adjusted-history-closure-certify" not in registered:
        historical_truth_app.command("final-pre2016-adjusted-history-closure-certify")(
            final_pre2016_adjusted_history_closure_certify
        )
    if "final-official-evidence-closure-certify" not in registered:
        historical_truth_app.command("final-official-evidence-closure-certify")(
            final_official_evidence_closure_certify
        )
    if "official-bridge-evidence-manifest" not in registered:
        historical_truth_app.command("official-bridge-evidence-manifest")(
            official_bridge_evidence_manifest
        )
    if "official-bridge-evidence-dossiers" not in registered:
        historical_truth_app.command("official-bridge-evidence-dossiers")(
            official_bridge_evidence_dossiers
        )
    if "official-bridge-evidence-discovery-registry" not in registered:
        historical_truth_app.command("official-bridge-evidence-discovery-registry")(
            official_bridge_evidence_discovery_registry
        )
    if "official-bridge-evidence-populate" not in registered:
        historical_truth_app.command("official-bridge-evidence-populate")(
            official_bridge_evidence_populate
        )
    if "official-bridge-document-download" not in registered:
        historical_truth_app.command("official-bridge-document-download")(
            official_bridge_document_download
        )
    if "official-bridge-evidence-acquire" not in registered:
        historical_truth_app.command("official-bridge-evidence-acquire")(
            official_bridge_evidence_acquire
        )
    if "official-bridge-evidence-materialize" not in registered:
        historical_truth_app.command("official-bridge-evidence-materialize")(
            official_bridge_evidence_materialize
        )
    if "official-bridge-evidence-certify-all" not in registered:
        historical_truth_app.command("official-bridge-evidence-certify-all")(
            bridge_evidence_bundle_cli.official_bridge_evidence_certify_all
        )
    if "official-bridge-complete" not in registered:
        historical_truth_app.command("official-bridge-complete")(
            official_bridge_complete
        )
    if "official-bridge-certify" not in registered:
        historical_truth_app.command("official-bridge-certify")(official_bridge_certify)
    return historical_truth_app


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "historical-truth":
        historical_truth_app = _historical_truth_app()
        sys.argv.pop(1)
        historical_truth_app()
        return

    from alpha.cli import app

    app()


if __name__ == "__main__":
    main()
