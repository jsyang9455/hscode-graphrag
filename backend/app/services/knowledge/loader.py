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
    # cosmetics
    "cream": ["3304.99.1000", "3304"],
    "lotion": ["3304.99.1000", "3304"],
    "serum": ["3304.99.1000", "3304"],
    "cosmetic": ["3304"],
    "skincare": ["3304"],
    "skin care": ["3304"],
    "beauty": ["3304"],
    "moisturizer": ["3304"],
    "화장품": ["3304"],
    "크림": ["3304"],
    "세럼": ["3304"],
    "로션": ["3304"],
    "히알루론": ["3304"],
    # food / supplements
    "supplement": ["2106"],
    "vitamin": ["2106"],
    "건강식품": ["2106"],
    # phones
    "smartphone": ["8517"],
    "phone": ["8517"],
    "mobile": ["8517"],
    "스마트폰": ["8517"],
    "휴대폰": ["8517"],
    # apparel
    "t-shirt": ["6109"],
    "tshirt": ["6109"],
    "tee": ["6109"],
    "cotton": ["6109", "5208"],
    "apparel": ["6109", "6209"],
    "clothing": ["6109", "6209"],
    "티셔츠": ["6109"],
    "의류": ["6109", "6209"],
    # plastics / bottles (generic plastic pack) vs vacuum flask
    "plastic bottle": ["3923"],
    "plastic": ["3923", "3924"],
    # vacuum flask / thermos — HS 9617
    "thermos": ["9617"],
    "flask": ["9617"],
    "vacuum flask": ["9617"],
    "drinkware": ["9617", "7323"],
    "보온병": ["9617"],
    "텀블러": ["9617", "7323"],
    "진공보온": ["9617"],
    # stainless cookware/tableware often 7323 when household
    "스테인리스 보온": ["9617"],
    "stainless steel bottle": ["9617"],
    "보온": ["9617"],
    # computers
    "laptop": ["8471"],
    "notebook": ["8471"],
    "computer": ["8471"],
    "pc": ["8471"],
    "노트북": ["8471"],
    "컴퓨터": ["8471"],
    "랩탑": ["8471"],
    # medical / chips / telecom
    "medical": ["9018"],
    "instrument": ["9018"],
    "의료": ["9018"],
    "chip": ["8542"],
    "반도체": ["8542"],
    "통신": ["8517"],
}

# Tokens too generic to auto-index from titles (cause false positives)
STOP_TOKENS = {
    "기타",
    "제품",
    "제품류",
    "것으로서",
    "것으로",
    "만든",
    "포함하는",
    "함유한",
    "갖춘",
    "other",
    "parts",
    "thereof",
    "including",
    "steel",
    "stainless",
    "스테인리스",
    "스테인리스강",
    "강제",
    "컴퓨터",  # too broad alone — handled via curated phrases
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


def ensure_hs_master(db: Session, force: bool = False) -> dict[str, Any]:
    """Load priority KCS (+ optional full master) and fill gaps from WCO HS."""
    count = db.query(HsCodeRecord).count()
    if not force and count > 10000:
        return {"total_in_db": count, "skipped": True, "is_full_kcs_hsk10": KCS_CSV.exists()}

    results: dict[str, Any] = {"steps": []}
    priority = ROOT / "data" / "kcs" / "kcs_hsk_priority.csv"
    if KCS_CSV.exists():
        results["steps"].append(ingest_kcs_hsk(db, csv_path=KCS_CSV))
    elif priority.exists():
        results["steps"].append(ingest_kcs_hsk(db, csv_path=priority))
    else:
        results["steps"].append({"note": "no kcs csv"})

    # Always try WCO 2/4/6-digit gap fill for broader heading coverage
    results["steps"].append(ingest_wco_fallback(db))
    results["total_in_db"] = db.query(HsCodeRecord).count()
    results["skipped"] = False
    results["is_full_kcs_hsk10"] = KCS_CSV.exists()
    results["force"] = force
    return results


def build_runtime_index(db: Session) -> dict[str, Any]:
    records = db.query(HsCodeRecord).all()
    by_code = {r.hs_code: r for r in records}
    curated: dict[str, list[str]] = {}
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
        curated[kw.lower()] = resolved or codes

    # Title token inverted index: exact token -> codes (not substring-scanned as phrases)
    title_index: dict[str, list[str]] = {}
    for r in records:
        if r.level < 6:
            continue
        text = f"{r.title_ko or ''} {r.title_en or ''}".lower()
        for tok in re.findall(r"[a-zA-Z가-힣]{2,}", text):
            if tok in STOP_TOKENS or len(tok) < 2:
                continue
            if tok.isdigit():
                continue
            bucket = title_index.setdefault(tok, [])
            if r.hs_code not in bucket and len(bucket) < 8:
                bucket.append(r.hs_code)

    # backward-compatible combined view (curated preferred)
    keyword_index = dict(title_index)
    keyword_index.update(curated)
    return {
        "by_code": by_code,
        "keyword_index": keyword_index,
        "curated": curated,
        "title_index": title_index,
        "count": len(records),
    }
