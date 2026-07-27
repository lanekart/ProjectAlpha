from __future__ import annotations

from pathlib import Path


MODULE = Path("alpha/decision_superiority/pre2016_calendar_recovery.py")
TESTS = Path("tests/decision_superiority/test_pre2016_calendar_recovery.py")
DOCS = Path("docs/DSI-010_PRE2011_OFFICIAL_CALENDAR_RECOVERY.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_module() -> None:
    text = MODULE.read_text(encoding="utf-8")
    if "class _VisibleHtmlTextParser(HTMLParser):" in text:
        print("MODULE_ALREADY_PATCHED=true")
        return

    text = replace_once(
        text,
        "from dataclasses import asdict, dataclass, replace\nfrom io import BytesIO\n",
        "from dataclasses import asdict, dataclass, replace\n"
        "from html.parser import HTMLParser\n"
        "from io import BytesIO\n",
        "html parser import",
    )
    text = replace_once(
        text,
        '    pdf_signature_valid: bool = False\n'
        '    text_extraction_status: str = "NOT_ATTEMPTED"\n',
        '    pdf_signature_valid: bool = False\n'
        '    document_format: str = ""\n'
        '    text_extraction_status: str = "NOT_ATTEMPTED"\n',
        "attempt document format",
    )
    text = replace_once(
        text,
        '        "Accept": "application/pdf,application/octet-stream,*/*",\n',
        '        "Accept": "application/pdf,text/html,application/octet-stream,*/*",\n',
        "accept header",
    )
    text = replace_once(
        text,
        '    pdf_signature = raw.startswith(b"%PDF-")\n'
        "    document_path = _persist_document(\n"
        "        candidate,\n"
        "        documents=documents,\n"
        "        raw=raw,\n"
        "        digest=digest,\n"
        "        pdf_signature=pdf_signature,\n"
        "    )\n",
        '    pdf_signature = raw.startswith(b"%PDF-")\n'
        "    document_format = _detect_document_format(\n"
        "        candidate.source_url,\n"
        "        raw,\n"
        "        content_type,\n"
        "    )\n"
        "    document_path = _persist_document(\n"
        "        candidate,\n"
        "        documents=documents,\n"
        "        raw=raw,\n"
        "        digest=digest,\n"
        "        document_format=document_format,\n"
        "    )\n",
        "document detection",
    )
    text = replace_once(
        text,
        "        pdf_signature_valid=pdf_signature,\n"
        "        document_path=str(document_path) if document_path else None,\n",
        "        pdf_signature_valid=pdf_signature,\n"
        "        document_format=document_format,\n"
        "        document_path=str(document_path) if document_path else None,\n",
        "attempt document format assignment",
    )
    text = replace_once(
        text,
        "    if not pdf_signature:\n"
        "        error = (\n"
        '            "HTML_RESPONSE_REJECTED"\n'
        '            if "html" in content_type.casefold() or raw.lstrip().startswith(b"<")\n'
        '            else "PDF_SIGNATURE_MISSING"\n'
        "        )\n"
        "        return replace(\n"
        "            base,\n"
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        "            error=error,\n"
        "        )\n",
        "    if document_format == \"UNKNOWN\":\n"
        "        error = (\n"
        '            "HTML_RESPONSE_REJECTED"\n'
        "            if _looks_like_html(raw, content_type)\n"
        '            else "DOCUMENT_FORMAT_UNSUPPORTED"\n'
        "        )\n"
        "        return replace(\n"
        "            base,\n"
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        "            error=error,\n"
        "        )\n",
        "document rejection",
    )
    text = replace_once(
        text,
        "    try:\n"
        "        text = _extract_pdf_text(raw)\n"
        "    except (OSError, ValueError) as exc:\n"
        "        return replace(\n"
        "            base,\n"
        '            text_extraction_status="FAILED",\n'
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        '            error=f"PDF_TEXT_EXTRACTION_FAILED:{type(exc).__name__}",\n'
        "        )\n",
        "    try:\n"
        "        text = _extract_document_text(raw, document_format)\n"
        "    except (OSError, UnicodeError, ValueError) as exc:\n"
        "        return replace(\n"
        "            base,\n"
        '            text_extraction_status="FAILED",\n'
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        '            error=f"DOCUMENT_TEXT_EXTRACTION_FAILED:{type(exc).__name__}",\n'
        "        )\n",
        "document text extraction",
    )
    text = replace_once(
        text,
        "def _persist_document(\n"
        "    candidate: Pre2011CalendarSourceCandidate,\n"
        "    *,\n"
        "    documents: Path,\n"
        "    raw: bytes,\n"
        "    digest: str | None,\n"
        "    pdf_signature: bool,\n"
        ") -> Path | None:\n"
        "    if not raw or digest is None:\n"
        "        return None\n"
        '    suffix = ".pdf" if pdf_signature else ".bin"\n',
        "class _VisibleHtmlTextParser(HTMLParser):\n"
        '    """Extract visible text from an immutable official archive HTML document."""\n\n'
        "    def __init__(self) -> None:\n"
        "        super().__init__(convert_charrefs=True)\n"
        "        self.parts: list[str] = []\n"
        "        self._suppressed_depth = 0\n\n"
        "    def handle_starttag(\n"
        "        self,\n"
        "        tag: str,\n"
        "        attrs: list[tuple[str, str | None]],\n"
        "    ) -> None:\n"
        "        del attrs\n"
        '        if tag.casefold() in {"script", "style"}:\n'
        "            self._suppressed_depth += 1\n\n"
        "    def handle_endtag(self, tag: str) -> None:\n"
        '        if tag.casefold() in {"script", "style"} and self._suppressed_depth:\n'
        "            self._suppressed_depth -= 1\n\n"
        "    def handle_data(self, data: str) -> None:\n"
        "        if self._suppressed_depth:\n"
        "            return\n"
        '        normalized = re.sub(r"\\s+", " ", data).strip()\n'
        "        if normalized:\n"
        "            self.parts.append(normalized)\n\n\n"
        "def _looks_like_html(raw: bytes, content_type: str) -> bool:\n"
        "    prefix = raw[:2048].lstrip().lower()\n"
        "    return (\n"
        '        "html" in content_type.casefold()\n'
        '        or prefix.startswith(b"<!doctype html")\n'
        '        or prefix.startswith(b"<html")\n'
        '        or b"<body" in prefix\n'
        "    )\n\n\n"
        "def _detect_document_format(\n"
        "    source_url: str,\n"
        "    raw: bytes,\n"
        "    content_type: str,\n"
        ") -> str:\n"
        '    if raw.startswith(b"%PDF-"):\n'
        '        return "PDF"\n'
        "    suffix = Path(urlparse(source_url).path).suffix.casefold()\n"
        '    if suffix in {".htm", ".html"} and _looks_like_html(raw, content_type):\n'
        '        return "HTML"\n'
        '    return "UNKNOWN"\n\n\n'
        "def _extract_document_text(raw: bytes, document_format: str) -> str:\n"
        '    if document_format == "PDF":\n'
        "        return _extract_pdf_text(raw)\n"
        '    if document_format == "HTML":\n'
        "        parser = _VisibleHtmlTextParser()\n"
        '        parser.feed(raw.decode("utf-8", errors="replace"))\n'
        '        rendered = "\\n".join(parser.parts)\n'
        "        if not rendered:\n"
        '            raise ValueError("HTML_TEXT_EMPTY")\n'
        "        return rendered\n"
        '    raise ValueError("DOCUMENT_FORMAT_UNSUPPORTED")\n\n\n'
        "def _persist_document(\n"
        "    candidate: Pre2011CalendarSourceCandidate,\n"
        "    *,\n"
        "    documents: Path,\n"
        "    raw: bytes,\n"
        "    digest: str | None,\n"
        "    document_format: str,\n"
        ") -> Path | None:\n"
        "    if not raw or digest is None:\n"
        "        return None\n"
        '    suffix = {"PDF": ".pdf", "HTML": ".htm"}.get(document_format, ".bin")\n',
        "HTML helpers and persistence",
    )
    text = replace_once(
        text,
        '        "CAPITAL_MARKET": ("capital market segment",),\n',
        '        "CAPITAL_MARKET": (\n'
        '            "capital market segment",\n'
        '            "capital market operations",\n'
        '            "capital market trading regulations",\n'
        '            "capital market (equities)",\n'
        "        ),\n",
        "capital market tokens",
    )
    text = replace_once(
        text,
        '        "CROSS_SEGMENT_CORROBORATION": (\n'
        '            "capital market segment",\n',
        '        "CROSS_SEGMENT_CORROBORATION": (\n'
        '            "capital market segment",\n'
        '            "capital market operations",\n'
        '            "capital market trading regulations",\n'
        '            "capital market (equities)",\n',
        "cross-segment tokens",
    )
    text = replace_once(
        text,
        '            r"\\b\\d{1,2}[-/]\\w{3,9}[-/]\\d{2,4}\\b",\n'
        '            r"\\b\\d{4}-\\d{2}-\\d{2}\\b",\n',
        '            r"\\b\\d{1,2}[-/]\\w{3,9}[-/]\\d{2,4}\\b",\n'
        '            r"\\b\\d{4}-\\d{2}-\\d{2}\\b",\n'
        '            r"\\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}\\b",\n'
        '            r"\\b\\d{1,2}(?:st|nd|rd|th)?\\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{4}\\b",\n',
        "textual date validation",
    )
    text = replace_once(
        text,
        '            not candidate.requires_muhurat_statement or "muhurat trading" in normalized\n',
        "            not candidate.requires_muhurat_statement\n"
        '            or "muhurat trading" in normalized\n'
        '            or "mahurat trading" in normalized\n',
        "Muhurat spelling validation",
    )
    MODULE.write_text(text, encoding="utf-8")
    print("MODULE_PATCHED=true")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    if "def test_valid_official_archive_html_is_recovered" in text:
        print("TESTS_ALREADY_PATCHED=true")
        return
    marker = "\n\ndef test_html_200_response_is_rejected_without_pdf_extraction"
    test = '''

def test_valid_official_archive_html_is_recovered(tmp_path: Path) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/cmtr5633.htm"
    raw = b"""<!doctype html><html><body>
    National Stock Exchange of India Limited
    Capital Market Operations
    Sub: Trading holidays for the calendar year 2005
    Download No. NSE/CMTR/5633
    Date: December 07, 2004
    Wednesday, January 26, 2005 Republic Day
    Muhurat Trading will be conducted
    </body></html>"""
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2005,
                source_id="NSE_CM_2005_CALENDAR_HTML",
                source_url=url,
                segment_scope="CAPITAL_MARKET",
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                requires_muhurat_statement=True,
            ),
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=raw,
                    content_type="text/html; charset=utf-8",
                    url=url,
                )
            }
        ),
    )

    attempt = result.attempts[0]
    assert result.fully_recovered_years == (2005,)
    assert attempt.document_format == "HTML"
    assert attempt.pdf_signature_valid is False
    assert attempt.text_extraction_status == "EXTRACTED"
    assert attempt.content_validation_passed is True
    assert attempt.recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
    assert attempt.document_path is not None
    assert attempt.document_path.endswith(".htm")
'''
    text = replace_once(text, marker, test + marker, "HTML recovery test marker")
    TESTS.write_text(text, encoding="utf-8")
    print("TESTS_PATCHED=true")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    text = text.replace(
        "- Official NSE circular PDF.\n- Official NSE archive PDF.\n",
        "- Official NSE circular PDF or immutable archive HTML.\n"
        "- Official NSE archive PDF or HTML document.\n",
    )
    text = text.replace(
        "An HTTP 200 response is not accepted unless it contains a valid PDF and the\n"
        "mandatory circular-content checks pass.\n",
        "An HTTP 200 response is accepted only when it contains either a valid PDF or an\n"
        "official archive HTML document whose URL also ends in `.htm`/`.html`, and all mandatory\n"
        "circular-content checks pass. HTML returned for a PDF URL remains rejected.\n",
    )
    DOCS.write_text(text, encoding="utf-8")
    print("DOCS_PATCHED=true")


def main() -> None:
    patch_module()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
