"""LLM co-recommendation: GPT cross-checks GraphRAG candidates for higher accuracy.

Pipeline order:
1) Office GraphRAG retrieves/ranks candidates from internal HS + learning weights
2) GPT (OPENAI_MODEL, e.g. gpt-5.6) reviews product + candidates and proposes HS
3) Merger keeps GraphRAG as anchor, adopts GPT when it agrees or picks a strong in-list candidate
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from backend.app.core.config import get_settings
from backend.app.services.knowledge.graph import get_kg

logger = logging.getLogger(__name__)

HS_RE = re.compile(r"(?<![\d.])(\d{4}(?:\.\d{2,4}){1,3}|\d{6,10})(?![\d.])")


def _normalize_hs(code: str | None) -> str:
    if not code:
        return ""
    code = str(code).strip()
    m = HS_RE.search(code)
    return m.group(1) if m else code


def _digits(code: str) -> str:
    return re.sub(r"\D", "", code or "")


def _same_family(a: str, b: str, n: int = 6) -> bool:
    da, db = _digits(a), _digits(b)
    return bool(da and db and da[:n] == db[:n])


def _candidate_pack(search: dict[str, Any], proposal: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    kg = get_kg()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in (search.get("local") or [])[:limit]:
        code = _normalize_hs(h.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        meta = kg.by_code.get(code) or {}
        rows.append(
            {
                "hs": code,
                "title": h.get("title") or meta.get("title_ko") or meta.get("title") or meta.get("title_en") or "",
                "score": h.get("score"),
                "channel": "local",
            }
        )
    for h in (search.get("global") or [])[:4]:
        code = _normalize_hs(h.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        meta = kg.by_code.get(code) or {}
        rows.append(
            {
                "hs": code,
                "title": h.get("title") or meta.get("title_ko") or meta.get("title") or "",
                "score": h.get("score"),
                "channel": "global",
                "reason": h.get("reason"),
            }
        )
    prop = _normalize_hs(proposal.get("proposed"))
    if prop and prop not in seen:
        meta = kg.by_code.get(prop) or {}
        rows.insert(0, {"hs": prop, "title": meta.get("title_ko") or meta.get("title") or "", "score": None, "channel": "hypothesis"})
    return rows


def call_openai_json(
    *,
    system: str,
    user_payload: dict[str, Any],
    temperature: float = 0.1,
    timeout: float = 45.0,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.use_llm or not settings.openai_api_key:
        raise RuntimeError("LLM disabled or OPENAI_API_KEY missing")
    model = settings.openai_model
    payload: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    # gpt-5.x family only accepts default temperature
    if not str(model).lower().startswith("gpt-5"):
        payload["temperature"] = temperature
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                detail = resp.text[:240]
            raise RuntimeError(f"OpenAI {resp.status_code}: {detail or resp.reason_phrase}")
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def gpt_hs_search(
    *,
    description: str,
    material: Optional[str],
    usage: Optional[str],
    graph_proposal: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask GPT to recommend HS using GraphRAG candidates as primary evidence."""
    system = (
        "당신은 한국 관세사 HS/HSK 분류 전문 보조원입니다. "
        "내부 GraphRAG 후보와 상품 설명을 함께 검토해 가장 타당한 HS를 고르세요. "
        "가능하면 제공된 candidates 중에서 선택하세요. "
        "candidates 밖 코드를 제안할 때는 근거가 명확해야 하며, "
        "근거 없는 추측 HS는 만들지 마세요. JSON만 반환합니다."
    )
    user = {
        "task": "hs_co_recommend",
        "product": {
            "description": description,
            "material": material,
            "usage": usage,
        },
        "graphrag": {
            "proposed_hs": graph_proposal,
            "candidates": candidates,
        },
        "instruction": (
            "JSON 키: recommended_hs, confidence(0-1), "
            "alternatives(list of hs), why_ko, "
            "agree_with_graphrag(bool), used_candidate(bool), "
            "risks(list of string)."
        ),
    }
    data = call_openai_json(system=system, user_payload=user, temperature=0.05, timeout=50.0)
    rec = _normalize_hs(data.get("recommended_hs"))
    alts = [_normalize_hs(a) for a in (data.get("alternatives") or []) if _normalize_hs(a)]
    conf = data.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.55
    except (TypeError, ValueError):
        conf_f = 0.55
    conf_f = max(0.0, min(1.0, conf_f))
    return {
        "recommended_hs": rec,
        "confidence": conf_f,
        "alternatives": alts[:4],
        "why_ko": data.get("why_ko") or "",
        "agree_with_graphrag": bool(data.get("agree_with_graphrag"))
        or _same_family(rec, graph_proposal),
        "used_candidate": bool(data.get("used_candidate")),
        "risks": data.get("risks") if isinstance(data.get("risks"), list) else [],
        "raw": data,
        "model": get_settings().openai_model,
    }


def merge_graph_and_gpt(
    *,
    graph_proposal: str,
    graph_alternatives: list[str],
    search: dict[str, Any],
    gpt: Optional[dict[str, Any]],
    harness: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge GraphRAG hypothesis with GPT co-recommendation."""
    h = harness or {}
    gpt_cand_min = float(h.get("fusion_gpt_candidate_min_conf", 0.55))
    weak_score = float(h.get("fusion_weak_graph_score", 35.0))
    weak_gpt = float(h.get("fusion_weak_graph_gpt_conf", 0.8))
    prefer_specific = bool(h.get("fusion_agree_prefer_gpt_specific", True))

    g = _normalize_hs(graph_proposal)
    alts = list(dict.fromkeys([_normalize_hs(a) for a in graph_alternatives if _normalize_hs(a)]))
    local_codes = [_normalize_hs(h0.get("code")) for h0 in (search.get("local") or [])]
    local_codes = [c for c in local_codes if c]
    top_score = float((search.get("local") or [{}])[0].get("score") or 0) if search.get("local") else 0.0
    kg = get_kg()

    if not gpt or not gpt.get("recommended_hs"):
        return {
            "proposed": g,
            "alternatives": alts[:3],
            "fusion": "graphrag_only",
            "gpt": gpt,
            "confidence_boost": 0.0,
        }

    l = _normalize_hs(gpt["recommended_hs"])
    gpt_conf = float(gpt.get("confidence") or 0.5)
    in_local = any(_same_family(l, c, 6) or l == c for c in local_codes[:8])
    in_kg = l in kg.by_code or any(_digits(l)[:6] == _digits(c)[:6] for c in kg.by_code if len(_digits(c)) >= 6)

    # Case A: agreement
    if _same_family(g, l, 6) or g == l:
        fused = g if g else l
        if prefer_specific and l and l != fused and l in kg.by_code:
            fused = l
        for x in [l] + (gpt.get("alternatives") or []):
            x = _normalize_hs(x)
            if x and x != fused and x not in alts:
                alts.insert(0, x)
        return {
            "proposed": fused,
            "alternatives": [a for a in alts if a != fused][:3],
            "fusion": "hybrid_agree",
            "gpt": gpt,
            "confidence_boost": 0.08 + 0.07 * gpt_conf,
        }

    # Case B: GPT picks another GraphRAG candidate
    if in_local and gpt_conf >= gpt_cand_min:
        for x in [g] + (gpt.get("alternatives") or []):
            x = _normalize_hs(x)
            if x and x != l and x not in alts:
                alts.append(x)
        if g and g not in alts:
            alts.insert(0, g)
        return {
            "proposed": l,
            "alternatives": [a for a in alts if a != l][:3],
            "fusion": "hybrid_gpt_from_candidates",
            "gpt": gpt,
            "confidence_boost": 0.04 * gpt_conf,
        }

    # Case C: GPT proposes known HS outside top local — only if GraphRAG is weak
    if in_kg and gpt_conf >= weak_gpt and top_score < weak_score:
        if g and g not in alts:
            alts.insert(0, g)
        return {
            "proposed": l,
            "alternatives": [a for a in alts if a != l][:3],
            "fusion": "hybrid_gpt_override_weak_graph",
            "gpt": gpt,
            "confidence_boost": 0.02,
        }

    # Case D: keep GraphRAG, surface GPT as alternative
    if l and l not in alts:
        alts.insert(0, l)
    return {
        "proposed": g,
        "alternatives": [a for a in alts if a != g][:3],
        "fusion": "hybrid_graph_primary_gpt_alt",
        "gpt": gpt,
        "confidence_boost": 0.02 if in_local else 0.0,
    }


def co_recommend(
    *,
    description: str,
    material: Optional[str],
    usage: Optional[str],
    search: dict[str, Any],
    proposal: dict[str, Any],
    harness: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run GPT co-recommend + merge. Falls back to GraphRAG-only when LLM unavailable."""
    settings = get_settings()
    graph_hs = _normalize_hs(proposal.get("proposed"))
    graph_alts = [_normalize_hs(a) for a in (proposal.get("alternatives") or [])]
    candidates = _candidate_pack(search, proposal)

    if not settings.use_llm or not settings.openai_api_key:
        return {
            "proposed": graph_hs,
            "alternatives": graph_alts[:3],
            "fusion": "graphrag_only",
            "gpt": None,
            "confidence_boost": 0.0,
            "candidates_fed": candidates,
        }

    try:
        gpt = gpt_hs_search(
            description=description,
            material=material,
            usage=usage,
            graph_proposal=graph_hs,
            candidates=candidates,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("GPT co-recommend failed: %s", exc)
        return {
            "proposed": graph_hs,
            "alternatives": graph_alts[:3],
            "fusion": "graphrag_only_llm_error",
            "gpt": {"error": str(exc)[:240], "model": settings.openai_model},
            "confidence_boost": 0.0,
            "candidates_fed": candidates,
        }

    merged = merge_graph_and_gpt(
        graph_proposal=graph_hs,
        graph_alternatives=graph_alts,
        search=search,
        gpt=gpt,
        harness=harness,
    )
    merged["candidates_fed"] = candidates
    return merged
