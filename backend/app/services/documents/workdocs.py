"""Extract and analyze broker work documents for GraphRAG learning."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

HS_RE = re.compile(r"\b(\d{4}(?:\.\d{2}){0,3})\b")


def extract_text_from_bytes(filename: str, data: bytes, mime: str = "") -> str:
    name = (filename or "").lower()
    if name.endswith((".txt", ".md", ".csv", ".json", ".log")) or mime.startswith("text/"):
        for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    if name.endswith(".pdf") or mime == "application/pdf":
        try:
            from pypdf import PdfReader  # type: ignore
            import io

            reader = PdfReader(io.BytesIO(data))
            parts = [(p.extract_text() or "") for p in reader.pages[:30]]
            text = "\n".join(parts).strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf extract failed: %s", exc)
        return ""

    if name.endswith(".docx"):
        try:
            import zipfile
            import io
            from xml.etree import ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xml = zf.read("word/document.xml")
            root = ET.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            texts = [n.text for n in root.findall(".//w:t", ns) if n.text]
            return "\n".join(texts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("docx extract failed: %s", exc)
            return ""

    # binary fallback: best-effort utf-8
    return data.decode("utf-8", errors="ignore")


def _heuristic_analysis(text: str, doc_type: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hs_codes = []
    for m in HS_RE.finditer(text):
        code = m.group(1)
        if code not in hs_codes:
            hs_codes.append(code)
    # pick a product-ish line
    description = ""
    for ln in lines[:40]:
        if HS_RE.search(ln):
            continue
        if len(ln) >= 8 and not ln.lower().startswith(("http", "www")):
            description = ln[:300]
            break
    if not description and lines:
        description = lines[0][:300]

    material = None
    usage = None
    for ln in lines:
        low = ln.lower()
        if material is None and ("재질" in ln or "material" in low):
            material = re.split(r"[:：]", ln, maxsplit=1)[-1].strip()[:120] or None
        if usage is None and ("용도" in ln or "usage" in low or "function" in low):
            usage = re.split(r"[:：]", ln, maxsplit=1)[-1].strip()[:120] or None

    opinion = ""
    for key in ("의견", "사유", "근거", "판단", "opinion", "reason"):
        for ln in lines:
            if key in ln.lower() or key in ln:
                opinion = ln[:500]
                break
        if opinion:
            break
    if not opinion:
        opinion = "\n".join(lines[:8])[:800]

    return {
        "source": "heuristic",
        "doc_type": doc_type,
        "product_description": description,
        "material": material,
        "usage": usage,
        "suggested_hs": hs_codes[0] if hs_codes else None,
        "candidate_hs": hs_codes[:5],
        "broker_opinion_excerpt": opinion,
        "keywords": list(
            dict.fromkeys(re.findall(r"[A-Za-z가-힣]{2,}", description.lower()))
        )[:12],
        "summary_ko": (
            f"업무자료에서 상품 '{description or '(미추출)'}' "
            f"및 HS 후보 {', '.join(hs_codes[:3]) or '없음'}을(를) 추출했습니다."
        ),
    }


def _llm_analysis(text: str, doc_type: str, draft: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.use_llm or not settings.openai_api_key:
        return draft
    payload = {
        "doc_type": doc_type,
        "text_excerpt": text[:6000],
        "draft": draft,
        "instruction": (
            "관세사 업무자료를 분석해 JSON만 반환. 키: product_description, material, usage, "
            "suggested_hs, candidate_hs(list), broker_opinion_excerpt, keywords(list), summary_ko. "
            "없는 값은 null. HS는 문서에 나온 코드만."
        ),
    }
    try:
        with httpx.Client(timeout=35.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "당신은 한국 관세사 업무자료 분석 보조원입니다. 근거 없는 HS를 만들지 마세요.",
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("document LLM analysis failed: %s", exc)
        draft["llm_error"] = str(exc)[:200]
        return draft

    out = dict(draft)
    for k in (
        "product_description",
        "material",
        "usage",
        "suggested_hs",
        "broker_opinion_excerpt",
        "summary_ko",
    ):
        if data.get(k) is not None:
            out[k] = data[k]
    if isinstance(data.get("candidate_hs"), list):
        out["candidate_hs"] = data["candidate_hs"][:8]
    if isinstance(data.get("keywords"), list):
        out["keywords"] = [str(x) for x in data["keywords"][:12]]
    out["source"] = "llm"
    return out


def analyze_document_text(text: str, doc_type: str = "opinion") -> dict[str, Any]:
    draft = _heuristic_analysis(text or "", doc_type)
    return _llm_analysis(text or "", doc_type, draft)


def ensure_upload_dir() -> Path:
    path = Path("data/runtime/uploads")
    path.mkdir(parents=True, exist_ok=True)
    return path
