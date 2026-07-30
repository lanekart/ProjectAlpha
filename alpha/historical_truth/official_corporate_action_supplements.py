"""Hash-bound official term supplements for incomplete historical NSE actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.corporate_action_price_models import (
    AdjustmentFactorState,
    CorporateActionEvent,
)

SUPPLEMENT_CONTRACT_VERSION = "DSI-010B5-OFFICIAL-TERMS-v1.0.0"
SUPPLEMENT_PARSER_VERSION = "dsi010b5_governed_terms_v1"
PRODUCTION_INFLUENCE = False


@dataclass(frozen=True, slots=True)
class OfficialCorporateActionSupplement:
    """An exact event-bound set of official terms and immutable provenance."""

    supplement_id: str
    symbol: str
    series: str
    effective_date: date
    source_filename: str
    source_url: str
    source_sha256: str
    official_raw_wording: str
    ratio_numerator: float | None
    ratio_denominator: float | None
    rights_price: float | None
    face_value: float | None
    record_date: date | None = None
    event_isin: str | None = None
    amendment_state: str = "ORIGINAL_FINAL_TERMS"
    new_face_value: float | None = None
    old_quantity: float | None = None
    new_quantity: float | None = None
    adjustment_factor: float | None = None
    price_adjustment_required: bool | None = None

    @property
    def relative_path(self) -> Path:
        return (
            Path("raw")
            / "official"
            / "corporate_action_supplements"
            / "dsi010b5"
            / self.source_filename
        )

    def payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["effective_date"] = self.effective_date.isoformat()
        payload["record_date"] = (
            self.record_date.isoformat() if self.record_date is not None else None
        )
        payload["contract_version"] = SUPPLEMENT_CONTRACT_VERSION
        payload["parser_version"] = SUPPLEMENT_PARSER_VERSION
        payload["production_influence"] = PRODUCTION_INFLUENCE
        return payload


@dataclass(frozen=True, slots=True)
class AppliedCorporateActionSupplement:
    """The verified result of applying a supplement to one canonical raw event."""

    action_id: str
    supplement: OfficialCorporateActionSupplement
    immutable_path: str

    def payload(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "immutable_path": self.immutable_path,
            **self.supplement.payload(),
        }


@dataclass(frozen=True, slots=True)
class RejectedCorporateActionSupplement:
    """A fail-closed supplement that did not satisfy its source/event contract."""

    supplement_id: str
    reason: str
    action_ids: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "supplement_id": self.supplement_id,
            "reason": self.reason,
            "action_ids": list(self.action_ids),
            "contract_version": SUPPLEMENT_CONTRACT_VERSION,
            "production_influence": PRODUCTION_INFLUENCE,
        }


@dataclass(frozen=True, slots=True)
class OfficialSecurityIdentitySupplement:
    """An official effective-dated listing interval omitted from HTR-009A2."""

    supplement_id: str
    symbol: str
    series: str
    isin: str
    valid_from: date
    source_filename: str
    source_url: str
    source_sha256: str
    official_raw_wording: str

    @property
    def identity_key(self) -> str:
        return f"nse:isin:{self.isin}"

    @property
    def relative_path(self) -> Path:
        return (
            Path("raw")
            / "official"
            / "corporate_action_supplements"
            / "dsi010b5"
            / self.source_filename
        )


@dataclass(frozen=True, slots=True)
class OfficialSupplementSource:
    """One immutable official document supporting a supplement."""

    source_id: str
    relative_path: Path
    source_url: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class OfficialSecurityTransitionSupplement:
    """An exact official predecessor/successor trading transition."""

    supplement_id: str
    predecessor_symbol: str
    predecessor_series: str
    predecessor_isin: str
    successor_symbol: str
    successor_series: str
    successor_isin: str
    effective_date: date
    sources: tuple[OfficialSupplementSource, ...]
    official_raw_wording: str


_SUPPLEMENTS = (
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-tatasteel-2007",
        "TATASTEEL",
        "EQ",
        date(2007, 10, 29),
        "tatasteel_2007_official_press.html",
        (
            "https://www.tatasteel.com/media/newsroom/press-releases/india/2007/"
            "funding-of-corus-transaction/"
        ),
        "27f83c81ff900588c6bbcceab2ae4269ae9a6fa414b75d8fd7e402656650ff6d",
        ("One ordinary share for every five ordinary shares held at Rs.300 per share."),
        1.0,
        5.0,
        300.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-tmpv-2008",
        "TMPV",
        "EQ",
        date(2008, 9, 9),
        "tmpv_2008_tatamotors_20f.pdf",
        "https://www.tatamotors.com/wp-content/uploads/2023/12/20F-2008.pdf",
        "1c8ff28023f9b59e9baa6d9a93e7ae3a57762e01984d47940b06119abcfb8ed5",
        (
            "One ordinary share for every six ordinary shares held at Rs.340 "
            "per share; the separately described DVR right is not this event."
        ),
        1.0,
        6.0,
        340.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-lakshmivilas-2014",
        "LAKSHVILAS",
        "EQ",
        date(2014, 7, 25),
        "lakshmivilas_2014_bse_lof.pdf",
        (
            "https://www.bseindia.com/downloads/ipo/"
            "Lakshmi%20Vilas%20Bank%20-%20LOF_070820141241.pdf"
        ),
        "a73148f4bef9016aaaf79c5ba2958489c4f8a55f8b3c1545f8a22865e35a05fb",
        (
            "Five equity shares for every six equity shares held at Rs.50 per "
            "equity share."
        ),
        5.0,
        6.0,
        50.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-ocl-2006",
        "OCL",
        "EQ",
        date(2006, 8, 29),
        "ocl_2006_sebi_lof.pdf",
        "https://www.sebi.gov.in/sebi_data/attachdocs/1292478628241.pdf",
        "f00439f3c803e1273c29d0435c4838e9a5ec95bd7498587100871b30d9d6a949",
        (
            "One equity share for every six equity shares held at Rs.120 per "
            "equity share."
        ),
        1.0,
        6.0,
        120.0,
        2.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-uniwestbnk-2006",
        "UNIWESTBNK",
        "EQ",
        date(2006, 1, 17),
        "uniwestbnk_2006_sebi_caf.pdf",
        "https://www.sebi.gov.in/sebi_data/attachdocs/1292399175191.pdf",
        "413df458096f73e906170b2bfc311e5f74ef4cef7a3def4c6d98c74e1ab14d40",
        (
            "One equity share for every two equity shares held at Rs.24 per "
            "share, comprising Rs.10 face value and Rs.14 premium."
        ),
        1.0,
        2.0,
        24.0,
        10.0,
        record_date=date(2006, 1, 25),
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-bajfinance-2006",
        "BAJFINANCE",
        "EQ",
        date(2006, 11, 13),
        "bajajfinance_2006_annual_report.pdf",
        (
            "https://cms-assets.bajajfinserv.in/is/content/bajajfinance/"
            "bajaj-finserv-limited-2008pdf?fmt=pdf&scl=1"
        ),
        "816892c7dcedc65ad773e1aff54091400474627278ee9a18e6e7184f980b970e",
        (
            "Six equity shares for every ten equity shares held at Rs.325 per "
            "share; the NCD component is separately described."
        ),
        6.0,
        10.0,
        325.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-cholafin-2007",
        "CHOLAFIN",
        "EQ",
        date(2007, 9, 11),
        "cholafin_2007_sebi_lof.pdf",
        "https://www.sebi.gov.in/sebi_data/attachdocs/1291892791087.pdf",
        "461becd4db41c860b5694c817649029b205a3374af0d874a3ea72158ff56fa4a",
        (
            "Three equity shares for every eight equity shares held at Rs.140 "
            "per share; one detachable warrant accompanies each rights share."
        ),
        3.0,
        8.0,
        140.0,
        10.0,
        record_date=date(2007, 9, 18),
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-andhrapap-2010",
        "ANDHRAPAP",
        "EQ",
        date(2010, 2, 23),
        "andhrapaper_2010_sebi_lof.pdf",
        "https://www.sebi.gov.in/sebi_data/attachdocs/1288348223615.pdf",
        "5b21cb8a5b78cd6f322aa43957099c75fd03496064e9f879c6e437c5a79a7620",
        (
            "Three equity shares for every eleven equity shares held at Rs.50 "
            "per share; one warrant accompanies each rights share."
        ),
        3.0,
        11.0,
        50.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-orientppr-2007",
        "ORIENTPPR",
        "EQ",
        date(2007, 6, 8),
        "orientpaper_2007_lof.pdf",
        (
            "https://orientpaper.in/wp-content/assets/investors/"
            "other-disclosures/right-issue-LOF-June_8_2007.pdf"
        ),
        "53e0c174c161ab044cce7382a5d387c900a12086333cbb72006e03cbeed585b4",
        (
            "Three equity shares for every ten equity shares held at Rs.360 "
            "per equity share."
        ),
        3.0,
        10.0,
        360.0,
        10.0,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-hindmotor-2011",
        "HINDMOTOR",
        "EQ",
        date(2011, 1, 27),
        "hindmotor_2010_11_bse_annual_report.pdf",
        "https://www.bseindia.com/bseplus/AnnualReport/500500/5005000311.pdf",
        "56c07a82b95e72049fc22111de2763f9ad9c5438fb4fa07f86d57b7604f1aa92",
        (
            "The official annual report records the High Court-confirmed "
            "reduction of the paid-up value of each existing equity share from "
            "Rs.10 to Rs.5 effective January 11, 2011, with the number of "
            "shares unchanged; trading was suspended from January 27 and "
            "resumed from February 21, 2011."
        ),
        None,
        None,
        None,
        10.0,
        record_date=date(2011, 1, 28),
        event_isin="INE253A01017",
        amendment_state="AUTHORITATIVE_TERMS_SELECTED_WITH_SUPERSESSION_PROOF",
        new_face_value=5.0,
        old_quantity=1.0,
        new_quantity=1.0,
        adjustment_factor=1.0,
        price_adjustment_required=False,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-kwality-2010",
        "KWALITY",
        "EQ",
        date(2010, 6, 15),
        "kwality_2009_10_bse_annual_report.pdf",
        "https://www.bseindia.com/bseplus/AnnualReport/531882/5318820310.pdf",
        "2ea760fc23053236b96be8d4e55d22811ac4b80aaaf4a7df10fea521338e69ca",
        (
            "The BSE-hosted annual report states that promoters voluntarily "
            "forewent the bonus. Five shares for every seven were allotted only "
            "to non-promoter holders, increasing total shares from 182,000,000 "
            "to 203,186,434. The governed adjustment therefore follows the "
            "official whole-share-class capitalization change, not 7/12."
        ),
        5.0,
        7.0,
        None,
        1.0,
        record_date=date(2010, 6, 16),
        event_isin="INE775B01025",
        amendment_state="AUTHORITATIVE_NON_UNIFORM_BONUS_TERMS",
        old_quantity=182_000_000.0,
        new_quantity=203_186_434.0,
        adjustment_factor=(182_000_000.0 / 203_186_434.0),
        price_adjustment_required=True,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-gulfpetro-2013",
        "GULFPETRO",
        "EQ",
        date(2013, 7, 9),
        "gppetrol_2012_13_bse_annual_report.pdf",
        "https://www.bseindia.com/bseplus/AnnualReport/532543/5325430313.pdf",
        "502c7ae71bec6da2c100cb9cbc329b9b3ece6a1ec31a69ffcd4bdf5cb4c2db90",
        (
            "The BSE-hosted annual report states that the 23:19 bonus was "
            "allotted only to non-promoter shareholders to meet minimum public "
            "shareholding. It records 44,000,000 shares before the issue and "
            "6,984,383 shares allotted. The governed adjustment therefore uses "
            "the official whole-share-class capitalization change rather than "
            "applying 19/42 uniformly to every share."
        ),
        23.0,
        19.0,
        None,
        5.0,
        record_date=date(2013, 7, 10),
        event_isin="INE586G01017",
        amendment_state="AUTHORITATIVE_NON_UNIFORM_BONUS_TERMS",
        old_quantity=44_000_000.0,
        new_quantity=50_984_383.0,
        adjustment_factor=(44_000_000.0 / 50_984_383.0),
        price_adjustment_required=True,
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-centext-2005",
        "CENTEXT",
        "EQ",
        date(2005, 8, 17),
        "centext_2005_annual_report.pdf",
        (
            "https://www.centuryextrusions.com/financials/annual-report/"
            "images/ar032005.pdf"
        ),
        "f0ad855e924c15c54a54570d6321f2d5b37b5cfcd1753ebdb98027fcb1fe4fbe",
        (
            "The company-hosted 2004-05 annual report states that the record "
            "book closure also determined eligibility for a 35:12 equity "
            "rights issue for cash at par. The equity share face value was "
            "Re.1, proving the issue price was Re.1."
        ),
        35.0,
        12.0,
        1.0,
        1.0,
        amendment_state="AUTHORITATIVE_HISTORICAL_CAPITAL_RECORD",
    ),
    OfficialCorporateActionSupplement(
        "dsi010b5-terms-lakshvilas-2006",
        "LAKSHVILAS",
        "EQ",
        date(2006, 11, 17),
        "lakshmivilas_2014_bse_lof.pdf",
        (
            "https://www.bseindia.com/downloads/ipo/"
            "Lakshmi%20Vilas%20Bank%20-%20LOF_070820141241.pdf"
        ),
        "a73148f4bef9016aaaf79c5ba2958489c4f8a55f8b3c1545f8a22865e35a05fb",
        (
            "The BSE-hosted 2014 letter of offer records a 1:2 bonus allotted "
            "November 25, 2006 followed by a 1:1 rights issue at Rs.50 per "
            "share, with rights shares allotted February 10, 2007."
        ),
        1.0,
        1.0,
        50.0,
        10.0,
        record_date=date(2006, 11, 24),
        amendment_state="AUTHORITATIVE_HISTORICAL_CAPITAL_RECORD",
    ),
)

_IDENTITY_SUPPLEMENTS = (
    OfficialSecurityIdentitySupplement(
        "dsi010b5-identity-mmtc-2010",
        "MMTC",
        "EQ",
        "INE123F01011",
        date(2010, 1, 8),
        "nse_press_20100106.htm",
        "https://nsearchives.nseindia.com/content/press/06012010.htm",
        "ca522747d2a180da57c25be8b1aa7e89f974f78ef26b4b012d55d58fa12da185",
        (
            "MMTC Limited, symbol MMTC, ISIN INE123F01011, admitted to "
            "dealings from January 8, 2010."
        ),
    ),
    OfficialSecurityIdentitySupplement(
        "dsi010b5-identity-kwality-2010",
        "KWALITY",
        "EQ",
        "INE775B01025",
        date(2010, 1, 8),
        "nse_press_20100106.htm",
        "https://nsearchives.nseindia.com/content/press/06012010.htm",
        "ca522747d2a180da57c25be8b1aa7e89f974f78ef26b4b012d55d58fa12da185",
        (
            "Kwality Dairy (India) Limited, symbol KWALITY, ISIN "
            "INE775B01025, admitted to dealings from January 8, 2010."
        ),
    ),
    OfficialSecurityIdentitySupplement(
        "dsi010b5-identity-vipul-2010",
        "VIPUL",
        "EQ",
        "INE946H01029",
        date(2010, 1, 8),
        "nse_press_20100106.htm",
        "https://nsearchives.nseindia.com/content/press/06012010.htm",
        "ca522747d2a180da57c25be8b1aa7e89f974f78ef26b4b012d55d58fa12da185",
        (
            "Vipul Limited, symbol VIPUL, ISIN INE946H01029, admitted to "
            "dealings from January 8, 2010."
        ),
    ),
)

_TRANSITION_SUPPLEMENTS = (
    OfficialSecurityTransitionSupplement(
        supplement_id="dsi010b5-transition-hindmotor-2011",
        predecessor_symbol="HINDMOTOR",
        predecessor_series="EQ",
        predecessor_isin="INE253A01017",
        successor_symbol="HINDMOTORS",
        successor_series="BE",
        successor_isin="INE253A01025",
        effective_date=date(2011, 2, 21),
        sources=(
            OfficialSupplementSource(
                source_id="bse-hindmotor-annual-report-2010-11",
                relative_path=(
                    Path("raw")
                    / "official"
                    / "corporate_action_supplements"
                    / "dsi010b5"
                    / "hindmotor_2010_11_bse_annual_report.pdf"
                ),
                source_url=(
                    "https://www.bseindia.com/bseplus/AnnualReport/"
                    "500500/5005000311.pdf"
                ),
                source_sha256=(
                    "56c07a82b95e72049fc22111de2763f9ad9c5438fb4fa07f86d57b7604f1aa92"
                ),
            ),
            OfficialSupplementSource(
                source_id="nse-hindmotor-recommencement-20110217",
                relative_path=(
                    Path("raw")
                    / "official"
                    / "company_identity"
                    / "HINDMOTOR"
                    / "nse_press_20110217.htm"
                ),
                source_url=(
                    "https://nsearchives.nseindia.com/content/press/17022011.htm"
                ),
                source_sha256=(
                    "a874ce997f384fedc21e74506775da58d1017b402e4c6aa2add87b1aa869d52f"
                ),
            ),
        ),
        official_raw_wording=(
            "The BSE-hosted annual report records suspension from January 27 "
            "and resumption from February 21 after the capital reduction. The "
            "NSE recommencement notice identifies the successor trading "
            "security as HINDMOTORS, series BE, ISIN INE253A01025, effective "
            "February 21, 2011."
        ),
    ),
)


def official_corporate_action_supplements(
    data_root: Path,
) -> tuple[
    tuple[AppliedCorporateActionSupplement, ...],
    tuple[RejectedCorporateActionSupplement, ...],
]:
    """Validate immutable official bytes before making any supplement available."""

    applied: list[AppliedCorporateActionSupplement] = []
    rejected: list[RejectedCorporateActionSupplement] = []
    for supplement in _SUPPLEMENTS:
        path = data_root / supplement.relative_path
        if not path.is_file():
            rejected.append(
                RejectedCorporateActionSupplement(
                    supplement.supplement_id,
                    "IMMUTABLE_OFFICIAL_SOURCE_MISSING",
                    (),
                )
            )
            continue
        observed = sha256(path.read_bytes()).hexdigest()
        if observed != supplement.source_sha256:
            rejected.append(
                RejectedCorporateActionSupplement(
                    supplement.supplement_id,
                    "IMMUTABLE_OFFICIAL_SOURCE_HASH_MISMATCH",
                    (),
                )
            )
            continue
        applied.append(AppliedCorporateActionSupplement("", supplement, str(path)))
    return tuple(applied), tuple(rejected)


def apply_official_corporate_action_supplements(
    actions: tuple[CorporateActionEvent, ...],
    verified: tuple[AppliedCorporateActionSupplement, ...],
) -> tuple[
    tuple[CorporateActionEvent, ...],
    tuple[AppliedCorporateActionSupplement, ...],
    tuple[RejectedCorporateActionSupplement, ...],
]:
    """Apply each verified supplement to exactly one matching official event."""

    by_key: dict[tuple[str, str, date], list[CorporateActionEvent]] = {}
    for action in actions:
        key = (action.symbol.upper(), action.series.upper(), action.effective_date)
        by_key.setdefault(key, []).append(action)

    replacements: dict[str, CorporateActionEvent] = {}
    applied: list[AppliedCorporateActionSupplement] = []
    rejected: list[RejectedCorporateActionSupplement] = []
    for record in verified:
        supplement = record.supplement
        key = (
            supplement.symbol.upper(),
            supplement.series.upper(),
            supplement.effective_date,
        )
        candidates = tuple(sorted(by_key.get(key, ()), key=lambda item: item.action_id))
        if len(candidates) != 1:
            rejected.append(
                RejectedCorporateActionSupplement(
                    supplement.supplement_id,
                    "OFFICIAL_EVENT_MATCH_NOT_UNIQUE",
                    tuple(item.action_id for item in candidates),
                )
            )
            continue
        action = candidates[0]
        if (
            supplement.event_isin is not None
            and str(action.isin or "").upper() != supplement.event_isin.upper()
        ):
            rejected.append(
                RejectedCorporateActionSupplement(
                    supplement.supplement_id,
                    "OFFICIAL_EVENT_ISIN_MISMATCH",
                    (action.action_id,),
                )
            )
            continue
        replacements[action.action_id] = replace(
            action,
            ratio_numerator=(
                supplement.ratio_numerator
                if supplement.ratio_numerator is not None
                else action.ratio_numerator
            ),
            ratio_denominator=(
                supplement.ratio_denominator
                if supplement.ratio_denominator is not None
                else action.ratio_denominator
            ),
            rights_price=(
                supplement.rights_price
                if supplement.rights_price is not None
                else action.rights_price
            ),
            old_face_value=(
                supplement.face_value
                if supplement.face_value is not None
                else action.old_face_value
            ),
            new_face_value=(
                supplement.new_face_value
                if supplement.new_face_value is not None
                else action.new_face_value
            ),
            old_quantity=(
                supplement.old_quantity
                if supplement.old_quantity is not None
                else action.old_quantity
            ),
            new_quantity=(
                supplement.new_quantity
                if supplement.new_quantity is not None
                else action.new_quantity
            ),
            record_date=supplement.record_date or action.record_date,
            price_adjustment_required=(
                supplement.price_adjustment_required
                if supplement.price_adjustment_required is not None
                else action.price_adjustment_required
            ),
            adjustment_factor_state=(
                AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS
                if supplement.adjustment_factor is not None
                else action.adjustment_factor_state
            ),
            adjustment_factor=(
                supplement.adjustment_factor
                if supplement.adjustment_factor is not None
                else action.adjustment_factor
            ),
        )
        applied.append(
            AppliedCorporateActionSupplement(
                action.action_id,
                supplement,
                record.immutable_path,
            )
        )
    return (
        tuple(replacements.get(item.action_id, item) for item in actions),
        tuple(sorted(applied, key=lambda item: item.supplement.supplement_id)),
        tuple(sorted(rejected, key=lambda item: item.supplement_id)),
    )


def official_security_identity_supplements(
    data_root: Path,
) -> tuple[OfficialSecurityIdentitySupplement, ...]:
    """Return only identity intervals backed by exact immutable source bytes."""

    verified: list[OfficialSecurityIdentitySupplement] = []
    for supplement in _IDENTITY_SUPPLEMENTS:
        path = data_root / supplement.relative_path
        if not path.is_file():
            continue
        if sha256(path.read_bytes()).hexdigest() != supplement.source_sha256:
            continue
        verified.append(supplement)
    return tuple(sorted(verified, key=lambda item: item.supplement_id))


def official_security_transition_supplements(
    data_root: Path,
) -> tuple[OfficialSecurityTransitionSupplement, ...]:
    """Return transitions only when every supporting official byte is intact."""

    verified: list[OfficialSecurityTransitionSupplement] = []
    for supplement in _TRANSITION_SUPPLEMENTS:
        if all(
            (data_root / source.relative_path).is_file()
            and sha256((data_root / source.relative_path).read_bytes()).hexdigest()
            == source.source_sha256
            for source in supplement.sources
        ):
            verified.append(supplement)
    return tuple(sorted(verified, key=lambda item: item.supplement_id))


__all__ = [
    "AppliedCorporateActionSupplement",
    "OfficialCorporateActionSupplement",
    "OfficialSecurityIdentitySupplement",
    "OfficialSecurityTransitionSupplement",
    "OfficialSupplementSource",
    "PRODUCTION_INFLUENCE",
    "RejectedCorporateActionSupplement",
    "SUPPLEMENT_CONTRACT_VERSION",
    "SUPPLEMENT_PARSER_VERSION",
    "apply_official_corporate_action_supplements",
    "official_corporate_action_supplements",
    "official_security_identity_supplements",
    "official_security_transition_supplements",
]
