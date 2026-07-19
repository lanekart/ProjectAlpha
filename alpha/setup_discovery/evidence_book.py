# ruff: noqa: E501 - PDF operators and fixed page labels are intentionally atomic.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alpha.setup_discovery.models import EvidenceChart, SetupDiscoveryReport
from alpha.setup_discovery.rendering import wrapped_lines

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


@dataclass(frozen=True, slots=True)
class PdfPage:
    commands: str


class TopMissedOpportunityEvidenceBook:
    """Write a deterministic, dependency-free vector evidence book."""

    def write(self, report: SetupDiscoveryReport, path: Path) -> Path:
        chart_by_case = {item.case_id: item for item in report.charts}
        pages = [_cover_page(report)]
        top_case_ids = {item.case_id for item in report.top_opportunities}
        for item in report.top_opportunities:
            pages.append(_opportunity_page(item, chart_by_case.get(item.case_id)))
        representatives = tuple(
            dict.fromkeys(
                case_id
                for cluster in report.clusters
                for case_id in cluster.representative_case_ids
                if case_id not in top_case_ids
            )
        )
        if representatives:
            cluster_by_case = {
                case_id: cluster
                for cluster in report.clusters
                for case_id in cluster.representative_case_ids
            }
            for case_id in representatives:
                chart = chart_by_case.get(case_id)
                cluster = cluster_by_case[case_id]
                pages.append(_representative_page(cluster.family_name, case_id, chart))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_encode_pdf(tuple(pages)))
        return path


def _cover_page(report: SetupDiscoveryReport) -> PdfPage:
    commands = [
        _text(54, 770, 22, "Project Alpha Setup Discovery & Evidence Engine"),
        _text(
            54, 738, 15, "Top 100 Missed Opportunities - Point-in-Time Evidence Book"
        ),
        _line(54, 722, 541, 722, 0.5, (0.18, 0.30, 0.40)),
        _text(54, 680, 11, f"Report ID: {report.report_id}"),
        _text(54, 658, 11, f"Unsupported cases: {report.summary.unsupported_cases}"),
        _text(54, 636, 11, f"Distinct families: {report.summary.clusters_selected}"),
        _text(
            54,
            614,
            11,
            f"Lookback proofs retained: {report.summary.lookback_cases_confirmed} / {report.summary.lookback_cases_claimed}",
        ),
        _text(
            54,
            572,
            10,
            "Charts end on the frozen onset date. No future bar is displayed.",
        ),
        _text(
            54,
            550,
            10,
            "Future outcomes rank pages retrospectively but never create cluster labels.",
        ),
        _text(54, 510, 10, "Research only. No production setup or policy is modified."),
        _text(54, 484, 11, "PRODUCTION_INFLUENCE=false"),
    ]
    return PdfPage("\n".join(commands))


def _opportunity_page(item: object, chart: EvidenceChart | None) -> PdfPage:
    commands = [
        _text(
            40,
            806,
            17,
            f"#{getattr(item, 'rank')} {getattr(item, 'symbol')} - {getattr(item, 'onset_date')}",
        ),
        _text(
            40,
            783,
            10,
            f"Evidence page {getattr(item, 'evidence_book_page')} | {getattr(item, 'event_family').replace('_', ' ').title()}",
        ),
        _line(40, 770, 555, 770, 0.5, (0.18, 0.30, 0.40)),
    ]
    commands.extend(_chart(chart, 40, 430, 515, 310))
    details = (
        ("Canonical detection", getattr(item, "canonical_detection_state")),
        ("Detected setup", getattr(item, "cluster_name")),
        (
            "Lookback",
            f"canonical {getattr(item, 'canonical_lookback')}; required {_available(getattr(item, 'required_lookback'))}",
        ),
        ("Reward / risk at onset", f"{getattr(item, 'prospective_rr'):.2f}"),
        ("Candidate blocker", getattr(item, "candidate_blocker")),
        (
            "Classification confidence",
            f"{getattr(item, 'classification_confidence'):.1%}",
        ),
        ("Retrospective forward outcome", f"{getattr(item, 'forward_outcome'):.2%}"),
    )
    y = 395.0
    for label, value in details:
        commands.append(_text(40, y, 9, f"{label}: {value}"))
        y -= 18
    y -= 3
    commands.append(_text(40, y, 9, "Unsupported pattern description:"))
    y -= 15
    for line in wrapped_lines(getattr(item, "unsupported_pattern_description"), 92):
        commands.append(_text(50, y, 9, line))
        y -= 14
    commands.append(
        _text(
            40,
            28,
            8,
            "Point-in-time chart | Research only | PRODUCTION_INFLUENCE=false",
        )
    )
    return PdfPage("\n".join(commands))


def _representative_page(
    family_name: str, case_id: str, chart: EvidenceChart | None
) -> PdfPage:
    commands = [
        _text(40, 806, 17, f"Cluster Representative - {family_name}"),
        _text(40, 783, 9, f"Case: {case_id}"),
        _line(40, 770, 555, 770, 0.5, (0.18, 0.30, 0.40)),
    ]
    commands.extend(_chart(chart, 40, 360, 515, 380))
    commands.append(
        _text(
            40,
            330,
            9,
            "Representative selected by causal feature proximity to the family centroid.",
        )
    )
    commands.append(_text(40, 28, 8, "Appendix | PRODUCTION_INFLUENCE=false"))
    return PdfPage("\n".join(commands))


def _chart(
    chart: EvidenceChart | None,
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[str]:
    commands = [_rect(x, y, width, height, 0.5, (0.72, 0.76, 0.79))]
    if chart is None or len(chart.bars) < 2:
        commands.append(
            _text(x + 15, y + height / 2, 10, "Point-in-time chart unavailable")
        )
        return commands
    bars = chart.bars
    closes = [float(item.close) for item in bars]
    ema_20 = [None if item.ema_20 is None else float(item.ema_20) for item in bars]
    ema_50 = [None if item.ema_50 is None else float(item.ema_50) for item in bars]
    prices = closes + [item for item in ema_20 + ema_50 if item is not None]
    low = min(prices)
    high = max(prices)
    spread = max(high - low, max(high * 0.01, 0.01))
    volume_height = height * 0.20
    price_y = y + volume_height + 18
    price_height = height - volume_height - 34
    maximum_volume = max(float(item.volume) for item in bars) or 1.0
    step = width / max(len(bars) - 1, 1)
    for index, bar in enumerate(bars):
        volume = float(bar.volume) / maximum_volume * volume_height
        bar_width = max(0.8, width / len(bars) * 0.55)
        commands.append(
            _filled_rect(
                x + index * step - bar_width / 2,
                y + 8,
                bar_width,
                volume,
                (0.55, 0.65, 0.72),
            )
        )
    commands.extend(
        _series(
            closes,
            x,
            price_y,
            width,
            price_height,
            low,
            spread,
            (0.06, 0.18, 0.26),
            1.3,
        )
    )
    commands.extend(
        _optional_series(
            ema_20,
            x,
            price_y,
            width,
            price_height,
            low,
            spread,
            (0.05, 0.55, 0.36),
            0.9,
        )
    )
    commands.extend(
        _optional_series(
            ema_50,
            x,
            price_y,
            width,
            price_height,
            low,
            spread,
            (0.78, 0.35, 0.12),
            0.9,
        )
    )
    commands.append(
        _text(
            x + 5,
            y + height - 13,
            8,
            f"Close {closes[-1]:.2f} | onset {chart.onset_date}",
        )
    )
    commands.append(
        _text(
            x + 5,
            y + 3,
            7,
            f"{bars[0].observed_on} to {bars[-1].observed_on} | volume bars",
        )
    )
    commands.append(_text(x + width - 137, y + height - 13, 7, "Close | EMA20 | EMA50"))
    return commands


def _series(
    values: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    low: float,
    spread: float,
    color: tuple[float, float, float],
    line_width: float,
) -> list[str]:
    points = [
        (
            x + index * width / max(len(values) - 1, 1),
            y + (value - low) / spread * height,
        )
        for index, value in enumerate(values)
    ]
    return [_polyline(points, line_width, color)]


def _optional_series(
    values: list[float | None],
    x: float,
    y: float,
    width: float,
    height: float,
    low: float,
    spread: float,
    color: tuple[float, float, float],
    line_width: float,
) -> list[str]:
    points = [
        (
            x + index * width / max(len(values) - 1, 1),
            y + (value - low) / spread * height,
        )
        for index, value in enumerate(values)
        if value is not None
    ]
    return [] if len(points) < 2 else [_polyline(points, line_width, color)]


def _encode_pdf(pages: tuple[PdfPage, ...]) -> bytes:
    page_ids = tuple(4 + index * 2 for index in range(len(pages)))
    content_ids = tuple(item + 1 for item in page_ids)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Count {len(pages)} /Kids "
            f"[{' '.join(f'{item} 0 R' for item in page_ids)}] >>"
        ).encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, content_id, page in zip(page_ids, content_ids, pages, strict=True):
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {PAGE_HEIGHT:.0f}] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        content = page.commands.encode("latin-1", errors="replace")
        objects[content_id] = (
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, max(objects) + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def _text(x: float, y: float, size: float, value: str) -> str:
    escaped = _escape(value)
    return f"0 0 0 rg BT /F1 {size:.1f} Tf {x:.1f} {y:.1f} Td ({escaped}) Tj ET"


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: float,
    color: tuple[float, float, float],
) -> str:
    return f"{_color(color)} RG {width:.1f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S"


def _polyline(
    points: list[tuple[float, float]],
    width: float,
    color: tuple[float, float, float],
) -> str:
    first, *rest = points
    path = [f"{first[0]:.1f} {first[1]:.1f} m"]
    path.extend(f"{x:.1f} {y:.1f} l" for x, y in rest)
    return f"{_color(color)} RG {width:.1f} w {' '.join(path)} S"


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    line_width: float,
    color: tuple[float, float, float],
) -> str:
    return f"{_color(color)} RG {line_width:.1f} w {x:.1f} {y:.1f} {width:.1f} {height:.1f} re S"


def _filled_rect(
    x: float,
    y: float,
    width: float,
    height: float,
    color: tuple[float, float, float],
) -> str:
    return f"{_color(color)} rg {x:.1f} {y:.1f} {width:.1f} {height:.1f} re f"


def _color(value: tuple[float, float, float]) -> str:
    return " ".join(f"{item:.3f}" for item in value)


def _escape(value: str) -> str:
    normalized = value.encode("ascii", errors="replace").decode("ascii")
    return normalized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _available(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = ["TopMissedOpportunityEvidenceBook"]
