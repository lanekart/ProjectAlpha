from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.historical_identity_bridge import (
    HistoricalIdentityAuditBundle,
    ProjectHistoricalIdentityAuditService,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.historical_source_evaluation_service import (
    build_project_historical_source_evaluation,
)
from alpha.historical_replay.nse_archive_proof import (
    NSE_ARCHIVE_PROOF_VERSION,
    NSE_CONTROL_SYMBOLS,
    NSE_RENAME_OR_INACTIVE_SYMBOLS,
    NSE_TRIAL_DATE_FROM,
    NSE_TRIAL_DATE_TO,
    NseArchiveAccessResult,
    NseArchiveCoverageConclusion,
    NseArchiveCoverageReport,
    NseArchiveFileEvidence,
    NseArchiveParser,
    NseArchiveProofBundle,
    NseArchiveReadinessReport,
    NseArchiveSourceDefinition,
    NseArchiveSourceDiscoveryReport,
    NseArchiveSourceType,
    NseCorporateActionProofEngine,
    NseCorporateActionRecord,
    NseIdentityEventRecord,
    NseIdentityProofEngine,
    NseIdentityProofRecord,
    NseSecurityFileInspection,
    NseSecuritySchemaVersion,
    build_security_inspect_report,
    official_bhavcopy_url,
    official_nse_source_catalog,
    validate_official_nse_url,
)
from alpha.historical_replay.upstox_historical_probe import (
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceRepository,
)
from alpha.market_truth.provider_transport import ReadOnlyProviderTransport

DEFAULT_NSE_ARCHIVE_PROOF_CACHE = Path(".alpha/diagnostic/nse_archive_proof")
DEFAULT_NSE_RAW_ARCHIVE = Path("data/raw")
DEFAULT_NSE_EXTRACTED_ARCHIVE = Path("data/extracted")

_LICENSE_NOTICE = (
    "NSE website terms prohibit systematic or automated collection. Downloadable "
    "content is limited by NSE copyright and data-usage terms; technical access is "
    "not treated as permission."
)
_RETENTION_RESTRICTION = (
    "Electronic retention for Alpha requires applicable NSE permission or a licensed "
    "historical-data agreement. This diagnostic reads existing local artifacts only."
)
_REDISTRIBUTION_RESTRICTION = (
    "No redistribution without applicable written NSE permission or contractual right."
)


class NseArchiveAuthorizationRequired(RuntimeError):
    pass


class NseArchiveAccessBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NseArchiveHttpResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        normalized = name.lower()
        for key, value in self.headers:
            if key.lower() == normalized:
                return value
        return None


class NseArchiveTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: int) -> NseArchiveHttpResponse: ...


class UrllibNseArchiveTransport:
    def __init__(self) -> None:
        self._transport = ReadOnlyProviderTransport()

    def get(self, url: str, *, timeout_seconds: int) -> NseArchiveHttpResponse:
        response = self._transport.get(
            url,
            headers={
                "Accept": "application/zip,application/gzip,text/csv,*/*;q=0.5",
                "Connection": "close",
                "User-Agent": "ProjectAlpha/1.0 NSEArchiveDiagnostic",
            },
            timeout_seconds=timeout_seconds,
        )
        return NseArchiveHttpResponse(
            status=response.status,
            headers=response.headers,
            body=response.body,
        )


class NseArchiveClient:
    def __init__(
        self,
        *,
        transport: NseArchiveTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        minimum_interval_seconds: float = 2.0,
        timeout_seconds: int = 20,
        max_attempts: int = 3,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self.transport = transport or UrllibNseArchiveTransport()
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.minimum_interval_seconds = minimum_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._last_request_at: float | None = None
        self.request_count = 0

    def fetch(
        self,
        url: str,
        *,
        authorization_reference: str | None,
    ) -> NseArchiveHttpResponse:
        validate_official_nse_url(url)
        if not authorization_reference or not authorization_reference.strip():
            raise NseArchiveAuthorizationRequired(
                "NSE automated retrieval requires an applicable authorization reference"
            )
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            response = self.transport.get(url, timeout_seconds=self.timeout_seconds)
            self.request_count += 1
            self._last_request_at = self.monotonic()
            if response.status in {401, 403}:
                raise NseArchiveAccessBlocked(
                    "official NSE endpoint blocked diagnostic access with HTTP "
                    f"{response.status}"
                )
            if response.status == 429:
                if attempt == self.max_attempts:
                    return response
                self.sleeper(_retry_after_seconds(response.header("Retry-After")))
                continue
            if response.status in {500, 502, 503, 504} and attempt < self.max_attempts:
                self.sleeper(float(attempt))
                continue
            return response
        raise AssertionError("bounded NSE fetch loop exhausted unexpectedly")

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.minimum_interval_seconds - (
            self.monotonic() - self._last_request_at
        )
        if remaining > 0:
            self.sleeper(remaining)


class NseArchiveProofRepository:
    def __init__(
        self,
        *,
        cache_root: Path | str = DEFAULT_NSE_ARCHIVE_PROOF_CACHE,
        raw_archive: Path | str = DEFAULT_NSE_RAW_ARCHIVE,
        extracted_archive: Path | str = DEFAULT_NSE_EXTRACTED_ARCHIVE,
        parser: NseArchiveParser | None = None,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.raw_archive = Path(raw_archive)
        self.extracted_archive = Path(extracted_archive)
        self.parser = parser or NseArchiveParser()

    def load_bhavcopy(
        self,
        value: date,
    ) -> tuple[NseArchiveFileEvidence, NseSecurityFileInspection | None]:
        path = self._bhavcopy_path(value)
        if path is None:
            evidence = _file_evidence(
                value,
                filename=f"cm{value:%d}{value.strftime('%b').upper()}{value:%Y}bhav.csv.zip",
                result=NseArchiveAccessResult.FILE_MISSING,
                checksum=None,
                timestamp=None,
                local_path=None,
                explanation="No bounded local NSE bhavcopy artifact is available.",
            )
            return evidence, None
        payload = path.read_bytes()
        checksum = _sha256(payload)
        evidence = _file_evidence(
            value,
            filename=path.name,
            result=NseArchiveAccessResult.LOCAL_CACHE_AVAILABLE,
            checksum=checksum,
            timestamp=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            local_path=str(path),
            explanation="Existing local artifact from the official NSE archive path.",
        )
        try:
            return evidence, self.parser.parse_security_file(
                payload,
                file_evidence=evidence,
            )
        except ValueError as exc:
            malformed = replace(
                evidence,
                access_result=NseArchiveAccessResult.MALFORMED_ARCHIVE,
                explanation=str(exc),
            )
            return malformed, None

    def store_bhavcopy(
        self,
        value: date,
        payload: bytes,
        *,
        source_url: str,
        retrieved_at: datetime,
    ) -> Path:
        validate_official_nse_url(source_url)
        target = self.cache_root / "bhavcopy" / f"bhavcopy_{value.isoformat()}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        metadata = {
            "archive_date": value.isoformat(),
            "checksum": _sha256(payload),
            "production_influence": False,
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            "source_url": source_url,
        }
        target.with_suffix(".metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def load_identity_events(self) -> tuple[NseIdentityEventRecord, ...]:
        records: list[NseIdentityEventRecord] = []
        for path in sorted(self.cache_root.glob("identity_events*")):
            if path.is_file() and not path.name.endswith(".json"):
                records.extend(
                    self.parser.parse_identity_events(
                        path.read_bytes(), filename=path.name
                    )
                )
        return tuple(
            sorted(
                records, key=lambda item: (item.effective_date, item.circular_reference)
            )
        )

    def load_corporate_actions(self) -> tuple[NseCorporateActionRecord, ...]:
        records: list[NseCorporateActionRecord] = []
        for path in sorted(self.cache_root.glob("corporate_actions*")):
            if path.is_file() and not path.name.endswith(".json"):
                records.extend(
                    self.parser.parse_corporate_actions(
                        path.read_bytes(), filename=path.name
                    )
                )
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.symbol,
                    item.event_date or date.min,
                    item.action_type.value,
                ),
            )
        )

    def _bhavcopy_path(self, value: date) -> Path | None:
        candidates = (
            self.cache_root / "bhavcopy" / f"bhavcopy_{value.isoformat()}.zip",
            self.raw_archive / f"bhavcopy_{value.isoformat()}.zip",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        month = value.strftime("%b").upper()
        legacy = self.extracted_archive / f"cm{value:%d}{month}{value:%Y}bhav.csv"
        if legacy.is_file():
            return legacy
        udiff = (
            self.extracted_archive / f"BhavCopy_NSE_CM_0_0_0_{value:%Y%m%d}_F_0000.csv"
        )
        return udiff if udiff.is_file() else None


class ProjectNseArchiveProofService:
    def __init__(
        self,
        *,
        repository: NseArchiveProofRepository | None = None,
        client: NseArchiveClient | None = None,
        upstox_repository: UpstoxHistoricalEvidenceRepository | None = None,
        identity_service: ProjectHistoricalIdentityAuditService | None = None,
    ) -> None:
        self.repository = repository or NseArchiveProofRepository()
        self.client = client or NseArchiveClient()
        self.upstox_repository = (
            upstox_repository or UpstoxHistoricalEvidenceRepository()
        )
        self.identity_service = (
            identity_service or ProjectHistoricalIdentityAuditService()
        )

    def build(
        self,
        *,
        date_from: date = NSE_TRIAL_DATE_FROM,
        date_to: date = NSE_TRIAL_DATE_TO,
        live: bool = False,
        authorization_reference: str | None = None,
    ) -> NseArchiveProofBundle:
        if date_to < date_from:
            raise ValueError("--date-to cannot precede --date-from")
        baseline = build_project_historical_source_evaluation(dry_run=True)
        manifest = baseline.manifest
        upstox = self.upstox_repository.load()
        identity_bundle = self.identity_service.build()
        proof_candidates = _proof_candidates(
            manifest,
            identity_bundle,
            date_from=date_from,
            date_to=date_to,
        )
        requested_dates = _weekdays(date_from, date_to)
        discovery_files = self._discover(
            requested_dates,
            live=live,
            authorization_reference=(
                authorization_reference
                or os.environ.get("ALPHA_NSE_ARCHIVE_AUTHORIZATION_REFERENCE")
            ),
        )
        candidate_dates = sorted({item.candidate_date for item in manifest.records})
        inspection_by_date: dict[date, NseSecurityFileInspection] = {}
        for value in candidate_dates:
            _, inspection = self.repository.load_bhavcopy(value)
            if inspection is not None:
                inspection_by_date[value] = inspection
        proof_date_set = {item.candidate_date for item in proof_candidates}
        proof_inspections = tuple(
            inspection_by_date[value]
            for value in sorted(proof_date_set)
            if value in inspection_by_date
        )
        events = self.repository.load_identity_events()
        actions = self.repository.load_corporate_actions()
        providers = _provider_index(upstox)
        proof_records = self._identity_records(
            proof_candidates,
            providers=providers,
            inspections=inspection_by_date,
            events=events,
        )
        population_records = self._identity_records(
            manifest.records,
            providers=providers,
            inspections=inspection_by_date,
            events=events,
        )
        identity_engine = NseIdentityProofEngine()
        identity_report = identity_engine.build_report(proof_records)
        population_report = identity_engine.build_report(population_records)
        corporate_report = NseCorporateActionProofEngine().build(
            proof_candidates,
            actions=actions,
            identity_records={item.candidate_id: item for item in proof_records},
        )
        discovery = _discovery_report(
            date_from=date_from,
            date_to=date_to,
            requested_dates=requested_dates,
            files=discovery_files,
            network_opt_in=live,
            network_requests=self.client.request_count,
        )
        security_report = build_security_inspect_report(proof_inspections)
        coverage = _coverage_report(
            proof=identity_report,
            population=population_report,
            identity_bundle=identity_bundle,
            population_security_files=len(inspection_by_date),
            corporate_action_records=actions,
        )
        readiness = _readiness_report(
            population_records,
            actual_readiness=build_project_breakout_source_gap_audit().ready_records,
        )
        return NseArchiveProofBundle(
            discovery=discovery,
            security=security_report,
            identity=identity_report,
            corporate_actions=corporate_report,
            coverage=coverage,
            readiness=readiness,
            population_identity_records=population_records,
        )

    def _discover(
        self,
        requested_dates: Sequence[date],
        *,
        live: bool,
        authorization_reference: str | None,
    ) -> tuple[NseArchiveFileEvidence, ...]:
        files: list[NseArchiveFileEvidence] = []
        catalog = official_nse_source_catalog()
        for value in requested_dates:
            bhavcopy, inspection = self.repository.load_bhavcopy(value)
            if (
                live
                and inspection is None
                and bhavcopy.access_result is NseArchiveAccessResult.FILE_MISSING
            ):
                bhavcopy = self._collect_bhavcopy(
                    value,
                    authorization_reference=authorization_reference,
                )
            files.append(bhavcopy)
            for source in catalog:
                if source.source_type is NseArchiveSourceType.CM_BHAVCOPY:
                    continue
                files.append(_uncollected_source_evidence(source, value))
        return tuple(
            sorted(files, key=lambda item: (item.archive_date, item.source_type.value))
        )

    def _collect_bhavcopy(
        self,
        value: date,
        *,
        authorization_reference: str | None,
    ) -> NseArchiveFileEvidence:
        url = official_bhavcopy_url(value)
        try:
            response = self.client.fetch(
                url,
                authorization_reference=authorization_reference,
            )
        except NseArchiveAuthorizationRequired as exc:
            return _file_evidence(
                value,
                filename=Path(url).name,
                result=NseArchiveAccessResult.TERMS_AUTHORIZATION_REQUIRED,
                checksum=None,
                timestamp=None,
                local_path=None,
                explanation=str(exc),
            )
        except NseArchiveAccessBlocked as exc:
            return _file_evidence(
                value,
                filename=Path(url).name,
                result=NseArchiveAccessResult.ACCESS_BLOCKED,
                checksum=None,
                timestamp=None,
                local_path=None,
                explanation=str(exc),
            )
        if response.status == 404:
            return _file_evidence(
                value,
                filename=Path(url).name,
                result=NseArchiveAccessResult.FILE_MISSING,
                checksum=None,
                timestamp=None,
                local_path=None,
                explanation="Official NSE archive returned HTTP 404.",
            )
        if response.status != 200:
            return _file_evidence(
                value,
                filename=Path(url).name,
                result=NseArchiveAccessResult.ACCESS_BLOCKED,
                checksum=None,
                timestamp=None,
                local_path=None,
                explanation=f"Official NSE archive returned HTTP {response.status}.",
            )
        if not response.body.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return _file_evidence(
                value,
                filename=Path(url).name,
                result=NseArchiveAccessResult.MALFORMED_ARCHIVE,
                checksum=_sha256(response.body),
                timestamp=datetime.now(tz=UTC),
                local_path=None,
                explanation="Official endpoint response is not a ZIP archive.",
            )
        retrieved = datetime.now(tz=UTC)
        path = self.repository.store_bhavcopy(
            value,
            response.body,
            source_url=url,
            retrieved_at=retrieved,
        )
        return _file_evidence(
            value,
            filename=path.name,
            result=NseArchiveAccessResult.RETRIEVED,
            checksum=_sha256(response.body),
            timestamp=retrieved,
            local_path=str(path),
            explanation="Retrieved from the bounded official NSE archive endpoint.",
        )

    @staticmethod
    def _identity_records(
        candidates: Sequence[HistoricalSourceEvaluationManifestRecord],
        *,
        providers: Mapping[str, UpstoxHistoricalCandidateEvidence],
        inspections: Mapping[date, NseSecurityFileInspection],
        events: Sequence[NseIdentityEventRecord],
    ) -> tuple[NseIdentityProofRecord, ...]:
        engine = NseIdentityProofEngine()
        return tuple(
            engine.resolve(
                candidate,
                provider=providers.get(candidate.candidate_id),
                inspection=inspections.get(candidate.candidate_date),
                identity_events=events,
            )
            for candidate in sorted(
                candidates, key=lambda item: (item.candidate_date, item.candidate_id)
            )
        )


def _proof_candidates(
    manifest: HistoricalSourceEvaluationManifest,
    identity_bundle: HistoricalIdentityAuditBundle,
    *,
    date_from: date,
    date_to: date,
) -> tuple[HistoricalSourceEvaluationManifestRecord, ...]:
    unresolved_symbols = {
        item.historical_symbol
        for item in identity_bundle.bridge.records
        if not item.authoritative
        and item.final_identity_status.value != "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    }
    explicit = unresolved_symbols | NSE_CONTROL_SYMBOLS | NSE_RENAME_OR_INACTIVE_SYMBOLS
    selected = tuple(
        item
        for item in manifest.records
        if date_from <= item.candidate_date <= date_to
        or item.historical_symbol.upper() in explicit
        or item.corporate_action_requirement
    )
    return tuple(
        sorted(selected, key=lambda item: (item.candidate_date, item.candidate_id))
    )


def _provider_index(
    dataset: UpstoxHistoricalEvidenceDataset | None,
) -> dict[str, UpstoxHistoricalCandidateEvidence]:
    return {item.candidate_id: item for item in (dataset.records if dataset else ())}


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    values: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _discovery_report(
    *,
    date_from: date,
    date_to: date,
    requested_dates: Sequence[date],
    files: Sequence[NseArchiveFileEvidence],
    network_opt_in: bool,
    network_requests: int,
) -> NseArchiveSourceDiscoveryReport:
    bhavcopies = tuple(
        item for item in files if item.source_type is NseArchiveSourceType.CM_BHAVCOPY
    )
    available = {
        NseArchiveAccessResult.LOCAL_CACHE_AVAILABLE,
        NseArchiveAccessResult.RETRIEVED,
    }
    return NseArchiveSourceDiscoveryReport(
        report_version=NSE_ARCHIVE_PROOF_VERSION,
        requested_date_from=date_from,
        requested_date_to=date_to,
        source_definitions=official_nse_source_catalog(),
        files=tuple(files),
        dates_requested=len(requested_dates),
        dates_with_local_bhavcopy=sum(
            item.access_result in available for item in bhavcopies
        ),
        dates_missing_bhavcopy=sum(
            item.access_result not in available for item in bhavcopies
        ),
        network_opt_in=network_opt_in,
        network_requests=network_requests,
        retention_or_license_blocking=True,
        limitations=(
            "MII security files were first disseminated on the public website in 2024; "
            "they cannot supply 2016 snapshots through that publication path.",
            (
                "No authorized local corporate-action or circular index package is "
                "present."
            ),
            "Local bhavcopy provenance is an official NSE URL pattern plus original "
            "archive member naming and checksum; no licensed retention grant is "
            "stored.",
        ),
    )


def _coverage_report(
    *,
    proof: object,
    population: object,
    identity_bundle: HistoricalIdentityAuditBundle,
    population_security_files: int,
    corporate_action_records: Sequence[NseCorporateActionRecord],
) -> NseArchiveCoverageReport:
    from alpha.historical_replay.nse_archive_proof import NseIdentityProofReport

    if not isinstance(proof, NseIdentityProofReport) or not isinstance(
        population, NseIdentityProofReport
    ):
        raise TypeError("NSE coverage requires identity proof reports")
    unresolved_ids = {
        item.candidate_id
        for item in identity_bundle.bridge.records
        if not item.authoritative
        and item.final_identity_status.value != "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    }
    provisional_ids = {
        item.candidate_id
        for item in identity_bundle.bridge.records
        if item.final_identity_status.value == "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    }
    proof_by_id = {item.candidate_id: item for item in proof.records}
    pct = (
        Decimal(population.authoritative_matches)
        * Decimal("100")
        / Decimal(population.proof_candidates)
        if population.proof_candidates
        else Decimal("0")
    ).quantize(Decimal("0.01"))
    return NseArchiveCoverageReport(
        report_version=NSE_ARCHIVE_PROOF_VERSION,
        proof_candidates=proof.proof_candidates,
        proof_authoritative_matches=proof.authoritative_matches,
        proof_unresolved_candidates=proof.unresolved_candidates,
        unresolved_upstox_candidates_tested=sum(
            candidate_id in proof_by_id for candidate_id in unresolved_ids
        ),
        unresolved_upstox_candidates_resolved=sum(
            proof_by_id[candidate_id].authoritative
            for candidate_id in unresolved_ids
            if candidate_id in proof_by_id
        ),
        provisional_upstox_candidates_tested=sum(
            candidate_id in proof_by_id for candidate_id in provisional_ids
        ),
        provisional_upstox_candidates_confirmed=sum(
            proof_by_id[candidate_id].authoritative
            for candidate_id in provisional_ids
            if candidate_id in proof_by_id
        ),
        full_population_candidates=population.proof_candidates,
        full_population_authoritative_matches=population.authoritative_matches,
        full_population_unresolved=population.unresolved_candidates,
        full_population_unique_symbols_resolved=len(
            {
                item.historical_symbol
                for item in population.records
                if item.authoritative
            }
        ),
        projected_657_candidate_identity_coverage_percent=pct,
        security_files_available=population_security_files,
        corporate_action_files_available=len(corporate_action_records),
        conclusion=NseArchiveCoverageConclusion.NSE_PUBLIC_ARCHIVE_PARTIALLY_SUFFICIENT,
        paid_nse_data_still_required=True,
        limitations=(
            "Exact dated bhavcopy proves candidate-date symbol, series, and ISIN but "
            "does not supply full listing, suspension, delisting, rename, or "
            "succession intervals.",
            "Corporate-action adjustment authority remains unavailable locally.",
            "Coverage counts are empirical local-artifact matches, not permission to "
            "integrate or redistribute NSE data.",
        ),
    )


def _readiness_report(
    records: Sequence[NseIdentityProofRecord],
    *,
    actual_readiness: int,
) -> NseArchiveReadinessReport:
    authority = tuple(item for item in records if item.authoritative)
    identity_and_price = tuple(item for item in authority if item.full_price_coverage)
    identity_price_ca_blocked = tuple(
        item for item in identity_and_price if item.corporate_action_required
    )
    ready_additions = len(identity_and_price) - len(identity_price_ca_blocked)
    return NseArchiveReadinessReport(
        report_version=NSE_ARCHIVE_PROOF_VERSION,
        missing_candidate_manifest=len(records),
        current_authoritative_readiness=actual_readiness,
        full_upstox_price_coverage=sum(item.full_price_coverage for item in records),
        candidates_receiving_nse_identity=len(authority),
        identity_and_price_ready=ready_additions,
        identity_ready_price_blocked=sum(
            item.authoritative and not item.full_price_coverage for item in records
        ),
        price_ready_identity_blocked=sum(
            item.full_price_coverage and not item.authoritative for item in records
        ),
        identity_and_price_ready_ca_blocked=len(identity_price_ca_blocked),
        candidates_still_identity_blocked=len(records) - len(authority),
        candidates_still_price_blocked=sum(
            not item.full_price_coverage for item in records
        ),
        maximum_readiness_after_identity_evidence=actual_readiness + ready_additions,
        maximum_readiness_after_identity_and_corporate_action_evidence=(
            actual_readiness + len(identity_and_price)
        ),
        actual_readiness_unchanged=actual_readiness,
        simulated_not_achieved=True,
        exact_next_step_conclusion="NSE_PAID_HISTORICAL_PACKAGE_REQUIRED",
    )


def _uncollected_source_evidence(
    source: NseArchiveSourceDefinition,
    value: date,
) -> NseArchiveFileEvidence:
    unavailable = (
        source.source_type is NseArchiveSourceType.CM_MII_SECURITY_FILE
        and value < date(2024, 2, 5)
    )
    return NseArchiveFileEvidence(
        source_type=source.source_type,
        official_url_pattern=source.official_url_pattern,
        archive_date=value,
        filename=_expected_filename(source.source_type, value),
        archive_category=source.archive_category,
        mime_type=source.mime_type,
        compression_format=source.compression_format,
        schema_version=source.schema_version,
        source_checksum=None,
        retrieval_timestamp=None,
        access_result=(
            NseArchiveAccessResult.NOT_AVAILABLE_FOR_DATE
            if unavailable
            else NseArchiveAccessResult.NOT_COLLECTED
        ),
        license_or_usage_notice=_LICENSE_NOTICE,
        retention_restriction=_RETENTION_RESTRICTION,
        redistribution_restriction=_REDISTRIBUTION_RESTRICTION,
        explanation=(
            "Public website dissemination began after this proof date."
            if unavailable
            else "No authorized local artifact was supplied for this source type."
        ),
    )


def _file_evidence(
    value: date,
    *,
    filename: str,
    result: NseArchiveAccessResult,
    checksum: str | None,
    timestamp: datetime | None,
    local_path: str | None,
    explanation: str,
) -> NseArchiveFileEvidence:
    return NseArchiveFileEvidence(
        source_type=NseArchiveSourceType.CM_BHAVCOPY,
        official_url_pattern=official_bhavcopy_url(value),
        archive_date=value,
        filename=filename,
        archive_category="NSE capital-market historical reports",
        mime_type=(
            "application/zip" if filename.lower().endswith(".zip") else "text/csv"
        ),
        compression_format=("ZIP" if filename.lower().endswith(".zip") else "NONE"),
        schema_version=(
            NseSecuritySchemaVersion.UDIFF_CM_BHAVCOPY_V1
            if "BhavCopy_NSE" in filename
            else NseSecuritySchemaVersion.LEGACY_CM_BHAVCOPY_V1
        ),
        source_checksum=checksum,
        retrieval_timestamp=timestamp,
        access_result=result,
        license_or_usage_notice=_LICENSE_NOTICE,
        retention_restriction=_RETENTION_RESTRICTION,
        redistribution_restriction=_REDISTRIBUTION_RESTRICTION,
        local_path=local_path,
        explanation=explanation,
    )


def _expected_filename(source: NseArchiveSourceType, value: date) -> str:
    if source is NseArchiveSourceType.CM_MII_SECURITY_FILE:
        return f"NSE_CM_security_{value:%d%m%Y}.csv.gz"
    if source is NseArchiveSourceType.CM_NEAT_SECURITY_FILE:
        return "security.gz"
    if source is NseArchiveSourceType.CORPORATE_ACTIONS:
        return f"corporate_actions_{value.isoformat()}.csv"
    return f"{source.value.lower()}_{value.isoformat()}"


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 2.0
    try:
        seconds = float(value)
    except ValueError:
        return 2.0
    return min(max(seconds, 0.0), 60.0)


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()
