"""Work-document extraction for heterogeneous office templates."""

from __future__ import annotations

import io
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

from openpyxl import Workbook

from backend.app.services.documents.workdocs import (
    analyze_document_text,
    extract_document,
    extract_text_from_bytes,
)


def _minimal_docx(paragraphs: list[str], table_rows: list[list[str]] | None = None) -> bytes:
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    document = Element(f"{W}document")
    body = SubElement(document, f"{W}body")
    for text in paragraphs:
        p = SubElement(body, f"{W}p")
        r = SubElement(p, f"{W}r")
        t = SubElement(r, f"{W}t")
        t.text = text
    if table_rows:
        tbl = SubElement(body, f"{W}tbl")
        for row in table_rows:
            tr = SubElement(tbl, f"{W}tr")
            for cell in row:
                tc = SubElement(tr, f"{W}tc")
                p = SubElement(tc, f"{W}p")
                r = SubElement(p, f"{W}r")
                t = SubElement(r, f"{W}t")
                t.text = cell
    xml = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(document)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def _minimal_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "분류"
    ws.append(["품명", "재질", "용도", "HS코드", "의견"])
    ws.append(["히알루론산 수분크림", "cream", "스킨케어", "3304.99.1000", "3304.99로 분류"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_xlsx_company_table():
    data = _minimal_xlsx()
    result = extract_document("office_a.xlsx", data)
    assert result.ok
    assert "히알루론산" in result.text
    assert "3304.99.1000" in result.text
    analysis = analyze_document_text(result.text, "opinion")
    assert analysis["suggested_hs"] == "3304.99.1000"
    assert "수분" in (analysis["product_description"] or "") or "product_description" in analysis.get("matched_fields", [])


def test_extract_docx_with_table():
    data = _minimal_docx(
        ["관세 분류 의견서"],
        [["품명", "면 티셔츠"], ["세번", "6109.10"], ["사유", "편물제 티셔츠"]],
    )
    result = extract_document("memo.docx", data)
    assert result.ok
    assert "면 티셔츠" in result.text
    assert "6109.10" in result.text
    analysis = analyze_document_text(result.text)
    assert analysis["suggested_hs"] and analysis["suggested_hs"].startswith("6109")


def test_reject_legacy_doc_and_xls():
    r1 = extract_document("a.doc", b"MZ")
    assert not r1.ok
    assert "docx" in (r1.warning or "").lower()
    r2 = extract_document("a.xls", b"\xd0\xcf\x11\xe0")
    assert not r2.ok
    assert "xlsx" in (r2.warning or "").lower()


def test_extract_text_api_surfaces_warning():
    text = extract_text_from_bytes("legacy.doc", b"binary")
    assert text.startswith("(텍스트 추출 실패)")
    assert "docx" in text.lower()


def test_csv_and_varied_labels():
    raw = "물품명,세번부호,소재,사용용도\n스테인리스 보온병,9617.00,스테인리스,음료보관\n".encode("utf-8")
    result = extract_document("pl.csv", raw)
    assert result.ok
    analysis = analyze_document_text(result.text)
    assert analysis["suggested_hs"] == "9617.00"
    assert analysis.get("material") or "스테인리스" in (analysis["product_description"] or "")
