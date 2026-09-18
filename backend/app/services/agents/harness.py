"""SIA-style office harness (scaffold) store and Feedback-Agent.

Harness = tunable scaffold around fixed model weights:
- routing thresholds
- GraphRAG↔GPT fusion gates
- K_history override strictness

Feedback-Agent proposes harness patches from blind-eval failures.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DEFAULT_HARNESS: dict[str, Any] = {
    "version": 1,
    "local_only_max_tokens": 6,
    "dual_force_tokens": 12,
    "fusion_gpt_candidate_min_conf": 0.55,
    "fusion_weak_graph_score": 35.0,
    "fusion_weak_graph_gpt_conf": 0.80,
    "fusion_agree_prefer_gpt_specific": True,
    "k_history_min_overlap": 3,
    "k_history_protect_score": 80.0,
    "k_history_related_score": 40.0,
    "office_token_boost_cap": 12.0,
    "force_dual": False,
    "notes": "default scaffold",
}

_HARNESS_DIR = Path("data/runtime/harness")
_CACHE: dict[int, dict[str, Any]] = {}


def harness_path(office_id: int) -> Path:
    _HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    return _HARNESS_DIR / f"office_{office_id}.json"


def get_harness(office_id: int) -> dict[str, Any]:
    if office_id in _CACHE:
        return deepcopy(_CACHE[office_id])
    path = harness_path(office_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merged = {**DEFAULT_HARNESS, **(data or {})}
            _CACHE[office_id] = merged
            return deepcopy(merged)
        except Exception:  # noqa: BLE001
            pass
    _CACHE[office_id] = deepcopy(DEFAULT_HARNESS)
    return deepcopy(DEFAULT_HARNESS)


def save_harness(office_id: int, harness: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    merged = {**DEFAULT_HARNESS, **(harness or {})}
    merged["version"] = int(merged.get("version") or 1) + 1
    merged["updated_at"] = datetime.utcnow().isoformat()
    if note:
        merged["notes"] = note
    path = harness_path(office_id)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    _CACHE[office_id] = merged
    return deepcopy(merged)


def reset_harness(office_id: int) -> dict[str, Any]:
    path = harness_path(office_id)
    if path.exists():
        path.unlink()
    _CACHE.pop(office_id, None)
    return get_harness(office_id)


def apply_patch(harness: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(harness)
    for k, v in (patch or {}).items():
        if k in {"version", "updated_at"}:
            continue
        if k in DEFAULT_HARNESS or k == "notes":
            out[k] = v
    # clamp numeric ranges
    out["local_only_max_tokens"] = int(max(2, min(20, int(out["local_only_max_tokens"]))))
    out["dual_force_tokens"] = int(max(out["local_only_max_tokens"] + 1, min(40, int(out["dual_force_tokens"]))))
    out["fusion_gpt_candidate_min_conf"] = float(max(0.35, min(0.95, float(out["fusion_gpt_candidate_min_conf"]))))
    out["fusion_weak_graph_score"] = float(max(10.0, min(120.0, float(out["fusion_weak_graph_score"]))))
    out["fusion_weak_graph_gpt_conf"] = float(max(0.5, min(0.95, float(out["fusion_weak_graph_gpt_conf"]))))
    out["k_history_min_overlap"] = int(max(1, min(8, int(out["k_history_min_overlap"]))))
    out["k_history_protect_score"] = float(max(20.0, min(200.0, float(out["k_history_protect_score"]))))
    out["k_history_related_score"] = float(max(10.0, min(150.0, float(out["k_history_related_score"]))))
    out["office_token_boost_cap"] = float(max(4.0, min(30.0, float(out["office_token_boost_cap"]))))
    out["force_dual"] = bool(out.get("force_dual"))
    out["fusion_agree_prefer_gpt_specific"] = bool(out.get("fusion_agree_prefer_gpt_specific", True))
    return out


class FeedbackHarnessAgent:
    """SIA Feedback-Agent (harness-only): propose scaffold patches from eval failures."""

    role = "feedback_harness"

    def propose(self, evaluation: dict[str, Any], harness: dict[str, Any]) -> dict[str, Any]:
        metrics = evaluation.get("metrics") or {}
        scored = evaluation.get("scored_predictions") or []
        misses = [s for s in scored if s.get("label_available") and not s.get("match_prefix4")]
        chapter_miss = [s for s in scored if s.get("label_available") and not s.get("match_chapter")]
        prefix4 = metrics.get("prefix4_hit_rate")
        patch: dict[str, Any] = {}
        reasons: list[str] = []

        # Prefer broader retrieval when chapter misses
        if chapter_miss or (prefix4 is not None and prefix4 < 0.7):
            patch["force_dual"] = True
            patch["local_only_max_tokens"] = max(2, int(harness.get("local_only_max_tokens", 6)) - 2)
            patch["dual_force_tokens"] = max(6, int(harness.get("dual_force_tokens", 12)) - 2)
            reasons.append("장/호 미스 → dual 검색 강화")

        # Let GPT pick alternative GraphRAG candidates more easily
        if misses:
            cur = float(harness.get("fusion_gpt_candidate_min_conf", 0.55))
            patch["fusion_gpt_candidate_min_conf"] = round(max(0.4, cur - 0.08), 3)
            patch["fusion_agree_prefer_gpt_specific"] = True
            reasons.append("prefix4 미스 → GPT 후보 재선정 문턱 완화")

        # If GraphRAG top is often wrong, allow GPT override when graph score weaker sooner
        if prefix4 is not None and prefix4 < 0.6:
            patch["fusion_weak_graph_score"] = float(harness.get("fusion_weak_graph_score", 35)) + 15.0
            patch["fusion_weak_graph_gpt_conf"] = round(
                max(0.55, float(harness.get("fusion_weak_graph_gpt_conf", 0.8)) - 0.1), 3
            )
            reasons.append("GraphRAG 약신호 시 GPT 보완 허용 확대")

        # Tighten unrelated K_history overrides when false positives suspected
        if len(misses) >= 2:
            patch["k_history_min_overlap"] = int(harness.get("k_history_min_overlap", 3)) + 1
            patch["k_history_protect_score"] = float(harness.get("k_history_protect_score", 80)) - 10.0
            reasons.append("약한 K_history 오버라이드 억제")

        # Boost office learned tokens a bit when labeled accuracy mediocre
        if prefix4 is not None and 0.4 <= prefix4 < 0.85:
            patch["office_token_boost_cap"] = float(harness.get("office_token_boost_cap", 12)) + 3.0
            reasons.append("사무실 학습 토큰 반영 강화")

        if not patch:
            reasons.append("게이트 통과 — harness 유지")
            return {
                "agent": self.role,
                "patch": {},
                "reasons": reasons,
                "action": "noop",
            }

        proposed = apply_patch(harness, patch)
        return {
            "agent": self.role,
            "patch": patch,
            "proposed_harness": proposed,
            "reasons": reasons,
            "action": "harness_update",
        }
