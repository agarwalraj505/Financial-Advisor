"""Small, bounded PDF factsheet parser for accessible public documents."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(contents: bytes, max_pages: int = 40) -> str:
    """Extract a bounded amount of text; malformed/encrypted PDFs return blank."""
    if not contents or len(contents) > 12_000_000:
        return ""
    try:
        reader = PdfReader(BytesIO(contents))
        pages = reader.pages[:max(1, min(int(max_pages), 40))]
        return "\n".join((page.extract_text() or "") for page in pages)
    except Exception:
        return ""


def parse_pdf_factsheet_text(text: str, source_url: str = "", isin: str | None = None) -> dict:
    """Apply the common labelled-field parser and identify PDF extraction."""
    from web_scraper import extract_etf_metadata_from_text

    result = extract_etf_metadata_from_text(text, source_url, isin)
    result["extraction_method"] = "PDF text label-pattern extraction"
    return result

