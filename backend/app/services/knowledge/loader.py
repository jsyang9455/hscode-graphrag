"""Ingest legacy KCS HSK master (from hscode_prj) + WCO HS fallback."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import HsCodeRecord

ROOT = Path(__file__).resolve().parents[4]
KCS_CSV = ROOT / "data" / "kcs" / "kcs_hsk_master.csv"
HS_CSV = ROOT / "data" / "kcs" / "harmonized_system.csv"
CHAPTER_KO = ROOT / "data" / "kcs" / "chapter_ko.json"
META_PATH = ROOT / "data" / "kcs" / "collection_meta.json"

ECOM_KEYWORDS: dict[str, list[str]] = {
    "cream": ["3304.99.1000", "330499"],
    "lotion": ["3304.99.1000"],
    "serum": ["3304.99.1000"],
    "cosmetic": ["3304"],
    "skincare": ["3304"],
    "beauty": ["3304"],
    "화장품": ["3304"],
    "크림": ["3304"],
    "세럼": ["3304"],
    "supplement": ["2106"],
    "vitamin": ["2106"],
    "food": ["2106"],
    "건강식품": ["2106"],
    "smartphone": ["8517"],
    "phone": ["8517"],
    "mobile": ["8517"],
    "스마트폰": ["8517"],
    "휴대폰": ["8517"],
    "t-shirt": ["6109"],
    "cotton": ["6109"],
    "apparel": ["6109"],
    "티셔츠": ["6109"],
    "의류": ["6109"],
    "bottle": ["3923"],
    "plastic": ["3923"],
    "병": ["3923"],
    "medical": ["9018"],
    "instrument": ["9018"],
    "의료": ["9018"],
    "chip": ["8542"],
    "통신": ["8517"],
}


def _fmt10(digits: str) -> str:
    d = re.sub(r"\D", "", digits).zfill(10)[:10]
    return f"{d[:4]}.{d[4:6]}.{d[6:]}"


def _fmt6(digits: str) -> str:
    d = re.sub(r"\D", "", digits).zfill(6)[:6]
    return f"{d[:4]}.{d[4:6]}"


def load_chapter_ko() -> dict[str, str]:
    if CHAPTER_KO.exists():
        return json.loads(CHAPTER_KO.read_text(encoding="utf-8"))
    return {}


def ingest_kcs_hsk(db: Session, csv_path: Path = KCS_CSV, limit: int | None = None) -> dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"KCS HSK master missing: {csv_path}. Run scripts/import_legacy_hscode_prj.py"
        )
    chapter_ko = load_chapter_ko()
    existing = {r.hs_code for r in db.query(HsCodeRecord.hs_code).all()}
    added = updated = 0
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            key = re.sub(r"\D", "", row.get("HS_KEY") or "")
            if len(key) < 6:
                continue
            code = _fmt10(key) if len(key) >= 10 else _fmt6(key)
            chapter = int(key[:2])
            title_ko = (
                (row.get("hs_한글품목명") or row.get("세번10단위품명") or row.get("세번6단위품명") or "")
            ).strip()
            title_en = (row.get("hs_영문품목명") or "").strip()
            parent = _fmt6(key[:6]) if len(key) >= 10 else _fmt6(key[:4] + "00")
            ch_title = chapter_ko.get(key[:2]) or row.get("세번2단위품명")
            payload = {
                "chapter_title": ch_title,
                "heading_title": row.get("세번4단위품명"),
                "subheading_title": row.get("세번6단위품명"),
                "tariff_line_title": row.get("세번10단위품명"),
                "combined": (row.get("final_combined_text") or "")[:800],
                "legacy_source": row.get("data_source") or "hscode_prj",
            }
            if code in existing:
                rec = db.query(HsCodeRecord).filter(HsCodeRecord.hs_code == code).first()
                if rec:
                    rec.title_ko = title_ko or rec.title_ko
                    rec.title_en = title_en or rec.title_en
                    rec.parent_code = parent
                    rec.level = 10 if len(key) >= 10 else 6
                    rec.chapter = chapter
                    rec.source = "kcs_hsk_hscode_prj"
                    rec.raw = payload
                    updated += 1
                continue
            db.add(
                HsCodeRecord(
                    hs_code=code,
                    level=10 if len(key) >= 10 else 6,
                    title_en=title_en,
                    title_ko=title_ko or ch_title,
                    parent_code=parent,
                    chapter=chapter,
                    source="kcs_hsk_hscode_prj",
                    raw=payload,
                )
            )
            existing.add(code)
            added += 1
            if added % 5000 == 0:
                db.commit()
    db.commit()
    meta = {
        "source_file": str(csv_path),
        "source_project": "jsyang9455/hscode_prj",
        "source_note": "관세청 HSK 통합데이터(corrected_integrated_data) — 한글/영문 품목명 포함",
        "added": added,
        "updated": updated,
        "total_in_db": db.query(HsCodeRecord).count(),
        "is_demo_only": False,
        "is_full_kcs_hsk10": True,
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def ingest_wco_fallback(db: Session, csv_path: Path = HS_CSV, limit: int | None = None) -> dict[str, Any]:
    """Fill gaps with WCO HS if KCS file absent."""
    if not csv_path.exists():
        return {"added": 0, "note": "wco csv missing"}
    chapter_ko = load_chapter_ko()
    existing = {r.hs_code for r in db.query(HsCodeRecord.hs_code).all()}
    added = 0
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            raw = (row.get("hscode") or "").strip()
            level = int(row.get("level") or 0)
            if level not in (2, 4, 6):
                continue
            digits = re.sub(r"\D", "", raw)
            code = _fmt6(digits) if level == 6 else (digits.zfill(2) if level == 2 else f"{digits[:2]}.{digits[2:]}")
            if code in existing:
                continue
            chapter = int(digits[:2])
            db.add(
                HsCodeRecord(
                    hs_code=code,
                    level=level,
                    title_en=(row.get("description") or "").strip(),
                    title_ko=chapter_ko.get(digits[:2].zfill(2)) if level == 2 else None,
                    parent_code=None,
                    chapter=chapter,
                    source="wco_hs",
                    raw=row,
                )
            )
            existing.add(code)
            added += 1
    db.commit()
    return {"added": added, "total_in_db": db.query(HsCodeRecord).count()}


def ensure_hs_master(db: Session) -> dict[str, Any]:
    count = db.query(HsCodeRecord).count()
    if count > 1000:
        return {"total_in_db": count, "skipped": True, "is_full_kcs_hsk10": KCS_CSV.exists()}
    if KCS_CSV.exists():
        return ingest_kcs_hsk(db)
    return ingest_wco_fallback(db)


def build_runtime_index(db: Session) -> dict[str, Any]:
    records = db.query(HsCodeRecord).all()
    by_code = {r.hs_code: r for r in records}
    keyword_index: dict[str, list[str]] = {}
    for kw, codes in ECOM_KEYWORDS.items():
        resolved = []
        for c in codes:
            c_digits = re.sub(r"\D", "", c)
            matches = [
                code
                for code in by_code
                if re.sub(r"\D", "", code).startswith(c_digits)
            ]
            matches.sort(key=lambda x: (0 if by_code[x].level >= 10 else 1, len(x)))
            if matches:
                resolved.append(matches[0])
            elif c in by_code:
                resolved.append(c)
        keyword_index[kw] = resolved or codes

    # Token index from Korean/English titles (sample denser chapters for e-com)
    for r in records:
        if r.level < 6:
            continue
        text = f"{r.title_ko or ''} {r.title_en or ''}".lower()
        for tok in re.findall(r"[a-zA-Z가-힣]{3,}", text):
            bucket = keyword_index.setdefault(tok, [])
            if r.hs_code not in bucket and len(bucket) < 6:
                bucket.append(r.hs_code)
    return {"by_code": by_code, "keyword_index": keyword_index, "count": len(records)}
