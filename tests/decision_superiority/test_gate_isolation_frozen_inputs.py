from __future__ import annotations

from dataclasses import replace

import pytest

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputContractValidator,
    FrozenInputReadiness,
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


def _candidate() -> FrozenCandidateKey:
    return FrozenCandidateKey(
        price_view="RAW",
        observed_on="2026-01-02",
        symbol="AAA",
        input_fingerprint="fp-a",
    )


def _section(
    section: FrozenInputSection,
    *,
    observed_on: str = "2026-01-02",
    post_observation: bool = False,
) -> FrozenInputSectionSnapshot:
    return FrozenInputSectionSnapshot.from_mapping(
        section=section,
        payload={"value": section.value},
        source_version=f"{section.value}-v1",
        observed_on=observed_on,
        contains_post_observation_data=post_observation,
    )


def _complete_sections() -> tuple[FrozenInputSectionSnapshot, ...]:
    return tuple(_section(section) for section in FrozenInputSection)


def test_complete_snapshot_is_replay_ready() -> None:
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=_complete_sections(),
    )

    result = FrozenInputContractValidator().validate(snapshot)

    assert result.readiness is FrozenInputReadiness.READY
    assert result.replay_ready is True
    assert result.missing_sections == ()
    assert result.invalid_sections == ()


def test_snapshot_build_is_deterministic() -> None:
    sections = _complete_sections()
    first = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=sections,
    )
    second = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=tuple(reversed(sections)),
    )

    assert first == second
    assert first.snapshot_sha256 == second.snapshot_sha256


def test_missing_section_fails_closed() -> None:
    sections = tuple(
        item
        for item in _complete_sections()
        if item.section is not FrozenInputSection.PORTFOLIO_STATE
    )
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=sections,
    )

    result = FrozenInputContractValidator().validate(snapshot)

    assert result.readiness is FrozenInputReadiness.INCOMPLETE
    assert result.replay_ready is False
    assert result.missing_sections == (FrozenInputSection.PORTFOLIO_STATE,)


def test_future_dated_section_fails_closed() -> None:
    sections = tuple(
        _section(section, observed_on="2026-01-03")
        if section is FrozenInputSection.ENTRY_POLICY
        else _section(section)
        for section in FrozenInputSection
    )
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=sections,
    )

    result = FrozenInputContractValidator().validate(snapshot)

    assert result.readiness is FrozenInputReadiness.POST_OBSERVATION_INPUT
    assert result.invalid_sections == (FrozenInputSection.ENTRY_POLICY,)


def test_explicit_post_observation_marker_fails_closed() -> None:
    sections = tuple(
        _section(section, post_observation=True)
        if section is FrozenInputSection.OUTCOME_POLICY
        else _section(section)
        for section in FrozenInputSection
    )
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=sections,
    )

    result = FrozenInputContractValidator().validate(snapshot)

    assert result.readiness is FrozenInputReadiness.POST_OBSERVATION_INPUT
    assert result.invalid_sections == (FrozenInputSection.OUTCOME_POLICY,)


def test_payload_hash_tampering_is_rejected() -> None:
    section = _section(FrozenInputSection.CANDIDATE_FEATURES)

    with pytest.raises(ValueError, match="payload_sha256"):
        replace(section, payload_sha256="0" * 64)


def test_snapshot_hash_tampering_is_rejected() -> None:
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=_complete_sections(),
    )

    with pytest.raises(ValueError, match="snapshot_sha256"):
        replace(snapshot, snapshot_sha256="0" * 64)


def test_duplicate_sections_are_rejected() -> None:
    sections = _complete_sections()
    duplicate = tuple(sorted((*sections, sections[0]), key=lambda item: item.section.value))

    with pytest.raises(ValueError, match="sections must be unique"):
        FrozenCandidateInputSnapshot.build(
            candidate=_candidate(),
            sections=duplicate,
        )


def test_non_object_payload_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        FrozenInputSectionSnapshot(
            section=FrozenInputSection.CANDIDATE_FEATURES,
            payload_json="[]",
            payload_sha256=(
                "4f53cda18c2baa0c0354bb5f9a3ecbe5"
                "ed12ab4d8e0152c8f880fedc6a7b845"
            ),
            source_version="v1",
            observed_on="2026-01-02",
        )


def test_production_influence_is_rejected() -> None:
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=_candidate(),
        sections=_complete_sections(),
    )

    with pytest.raises(ValueError, match="diagnostic-only"):
        replace(snapshot, production_influence=True)
