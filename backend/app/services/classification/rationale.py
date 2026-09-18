"""Generate customs-broker-readable HS recommendation rationales (LLM or template)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from backend.app.core.config import get_settings
from backend.app.services.knowledge.graph import get_kg

logger = logging.getLogger(__name__)


def _code_meta(hs: str) -> dict[str, Any]:
    kg = get_kg()
    digits = re.sub(r"\D", "", hs or "")
    meta = kg.by_code.get(hs) or kg.by_code.get(digits) or {}
    if not meta and len(digits) >= 4:
        meta = kg.by_code.get(f"{digits[:4]}.{digits[4:6]}" if len(digits) >= 6 else digits[:4]) or {}
    title = meta.get("title_ko") or meta.get("title") or meta.get("title_en") or "품명 미확인"
    return {
        "hs": hs,
        "title": title,
        "title_en": meta.get("title_en") or "",
        "tariff_rate": kg.tariff_rate(hs) if hs else None,
    }


def _hit_lines(hits: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for h in hits[:limit]:
        code = h.get("code") or h.get("hs") or ""
        meta = _code_meta(code)
        out.append(
            {
                "hs": code,
                "title": h.get("title") or meta["title"],
                "score": h.get("score"),
                "reason": h.get("reason") or "GraphRAG 유사도",
                "channel": h.get("channel") or "local",
            }
        )
    return out


def _template_brief(
    *,
    description: str,
    material: Optional[str],
    usage: Optional[str],
    recommended_hs: str,
    alternatives: list[str],
    local_hits: list[dict[str, Any]],
    global_hits: list[dict[str, Any]],
    gir: list[str],
    exclusion_checks: list[dict[str, Any]],
    confidence: float,
    confidence_grade: str,
    review_tier: str,
    metric_flags: list[str],
    routing_mode: str,
) -> dict[str, Any]:
    top = _code_meta(recommended_hs)
    alt_rows = []
    for code in alternatives[:3]:
        m = _code_meta(code)
        alt_rows.append(
            {
                "hs": code,
                "title": m["title"],
                "why_secondary": (
                    f"유사 후보이나 상품 설명·재질·용도와의 정합성이 1순위({recommended_hs})보다 낮아 "
                    "보조 후보로 유지합니다. 관세사 검토 시 품명·구성 비율에 따라 재평가하세요."
                ),
            }
        )

    product_bits = [description.strip()]
    # case.description may already embed material:/usage: from the API layer
    desc_l = description.lower()
    if material and f"material:{material.lower()}" not in desc_l and f"재질: {material.lower()}" not in desc_l:
        product_bits.append(f"재질: {material}")
    if usage and f"usage:{usage.lower()}" not in desc_l and f"용도: {usage.lower()}" not in desc_l:
        product_bits.append(f"용도: {usage}")
    product_line = " / ".join(product_bits)

    gir_text = ", ".join(gir) if gir else "GIR1"
    gir_explain = {
        "GIR1": "호(heading) 문구와 관련 주석에 따라 분류",
        "GIR3": "복합·세트성 물품 등 복수 후보 경합 시 적용",
        "GIR6": "소호(subheading) 수준까지 동일 원칙으로 세분",
    }
    gir_detail = "; ".join(f"{g}({gir_explain.get(g, '일반 해석 규칙')})" for g in gir) or "GIR1 기본 적용"

    exclusions = [e.get("note", "") for e in exclusion_checks if e.get("note")]
    exclusion_text = "; ".join(exclusions) if exclusions else "현재 검색 범위에서 배제 주석 위반은 검출되지 않았습니다."

    risks: list[str] = []
    if "chapter_contention" in (metric_flags or []) or any(
        e.get("note") == "contending chapter candidate" for e in exclusion_checks
    ):
        risks.append("장(chapter) 경합 신호가 있습니다. 주성분·본질적 특성(GIR3)을 재확인하세요.")
    if "mode_collapse_risk" in (metric_flags or []):
        risks.append("최근 분류가 특정 장에 편중되어 있습니다. 습관적 추천 여부를 점검하세요.")
    if "gir_avoidance_risk" in (metric_flags or []):
        risks.append("적용 GIR이 제한적입니다. 복합물품 여부를 추가로 검토하세요.")
    if confidence < 0.45:
        risks.append("신뢰도가 낮습니다. 원재료 비율·기능·포장 형태 보완 자료가 필요합니다.")
    if not risks:
        risks.append("즉시 차단 사유는 없으나, 최종 확정 전 품명 표기와 관세율 영향은 확인하세요.")

    local = _hit_lines(local_hits)
    evidence = []
    for h in local[:3]:
        sc = h.get("score")
        sc_txt = f" (점수 {sc:.3f})" if isinstance(sc, (int, float)) else ""
        evidence.append(f"{h['hs']} {h['title']}{sc_txt} — {h['reason']}")

    why = (
        f"상품 설명「{description.strip()[:120]}」에 대해 사무실 GraphRAG·관세청 HSK 검색 결과 "
        f"1순위 후보로 {top['hs']}({top['title']})를 선정했습니다. "
        f"검색 채널은 {routing_mode}이며, {gir_detail}를 근거로 소호까지 정렬했습니다. "
        f"예상 기본세율은 {top.get('tariff_rate')}% 수준입니다."
    )

    review_guidance = (
        "① 추천 HS 품명이 실물 구성·용도와 일치하는지 확인  "
        "② 대체 후보와 비교해 본질적 특성이 다른 장/호에 해당하지 않는지 점검  "
        "③ 배제·포함 주석 및 FTA/특혜세율 영향 검토 후 확정 또는 수정"
    )

    narrative = "\n".join(
        [
            f"【추천 코드】 {top['hs']} — {top['title']}",
            f"【상품 이해】 {product_line}",
            f"【선정 사유】 {why}",
            f"【적용 GIR】 {gir_text} — {gir_detail}",
            f"【배제·주석】 {exclusion_text}",
            f"【신뢰도】 {confidence_grade} ({confidence:.1%}) · 검토단계 {review_tier}",
            f"【검토 가이드】 {review_guidance}",
        ]
    )

    return {
        "source": "template",
        "headline": f"추천 HS {top['hs']} — {top['title']}",
        "product_understanding": product_line,
        "recommended": {
            "hs": top["hs"],
            "title": top["title"],
            "tariff_rate": top.get("tariff_rate"),
            "why_selected": why,
            "gir_basis": gir_detail,
        },
        "alternatives": alt_rows,
        "evidence": evidence,
        "exclusion_summary": exclusion_text,
        "risks_and_checks": risks,
        "review_guidance": review_guidance,
        "confidence_note": (
            f"시스템 신뢰도 {confidence_grade}({confidence:.1%}). "
            f"{'경량 검토로 충분해 보이나' if review_tier == 'lightweight' else '심층 검토를 권고하며'} "
            "최종 판단은 관세사 HITL 확정이 필요합니다."
        ),
        "narrative_ko": narrative,
    }


def _llm_enrich(brief: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.use_llm or not settings.openai_api_key:
        return brief

    system = (
        "당신은 한국 관세사 실무를 돕는 HS 분류 보좌관입니다. "
        "주어진 분류 근거를 바탕으로 관세사 직원이 바로 검토할 수 있게 "
        "한국어로 명확하고 간결하게 정리하세요. 추측으로 없는 HS를 만들지 마세요."
    )
    user = {
        "task": "broker_brief",
        "instruction": (
            "JSON만 반환. 키: headline, product_understanding, why_selected, "
            "gir_basis, alternatives_notes(list of {hs, note}), risks(list), "
            "review_guidance, confidence_note, narrative_ko"
        ),
        "context": context,
        "draft": brief,
    }
    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                    ],
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
    except Exception as exc:  # noqa: BLE001 — fall back silently for UX
        logger.warning("LLM rationale enrichment failed: %s", exc)
        brief["source"] = "template_fallback"
        brief["llm_error"] = str(exc)[:200]
        return brief

    if data.get("headline"):
        brief["headline"] = data["headline"]
    if data.get("product_understanding"):
        brief["product_understanding"] = data["product_understanding"]
    if data.get("why_selected") and brief.get("recommended"):
        brief["recommended"]["why_selected"] = data["why_selected"]
    if data.get("gir_basis") and brief.get("recommended"):
        brief["recommended"]["gir_basis"] = data["gir_basis"]
    if data.get("alternatives_notes") and brief.get("alternatives"):
        notes = {n.get("hs"): n.get("note") for n in data["alternatives_notes"] if isinstance(n, dict)}
        for alt in brief["alternatives"]:
            if notes.get(alt["hs"]):
                alt["why_secondary"] = notes[alt["hs"]]
    if data.get("risks"):
        brief["risks_and_checks"] = data["risks"]
    if data.get("review_guidance"):
        brief["review_guidance"] = data["review_guidance"]
    if data.get("confidence_note"):
        brief["confidence_note"] = data["confidence_note"]
    if data.get("narrative_ko"):
        brief["narrative_ko"] = data["narrative_ko"]
    brief["source"] = "llm"
    return brief


def build_broker_brief(
    *,
    description: str,
    material: Optional[str] = None,
    usage: Optional[str] = None,
    recommended_hs: str,
    alternatives: list[str],
    local_hits: list[dict[str, Any]],
    global_hits: list[dict[str, Any]],
    gir: list[str],
    exclusion_checks: list[dict[str, Any]],
    confidence: float,
    confidence_grade: str,
    review_tier: str,
    metric_flags: list[str],
    routing_mode: str,
) -> dict[str, Any]:
    brief = _template_brief(
        description=description,
        material=material,
        usage=usage,
        recommended_hs=recommended_hs,
        alternatives=alternatives,
        local_hits=local_hits,
        global_hits=global_hits,
        gir=gir,
        exclusion_checks=exclusion_checks,
        confidence=confidence,
        confidence_grade=confidence_grade,
        review_tier=review_tier,
        metric_flags=metric_flags,
        routing_mode=routing_mode,
    )
    context = {
        "description": description,
        "material": material,
        "usage": usage,
        "recommended_hs": recommended_hs,
        "alternatives": alternatives,
        "local_hits": _hit_lines(local_hits),
        "global_hits": _hit_lines(global_hits),
        "gir": gir,
        "confidence": confidence,
        "confidence_grade": confidence_grade,
        "review_tier": review_tier,
        "metric_flags": metric_flags,
        "routing_mode": routing_mode,
    }
    return _llm_enrich(brief, context)
