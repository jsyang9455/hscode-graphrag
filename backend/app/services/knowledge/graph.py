"""HS Regulatory Knowledge Graph backed by collected HS master + per-office weights."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import networkx as nx
from sqlalchemy.orm import Session

from backend.app.db.models import HsCodeRecord, TenantKeywordWeight
from backend.app.services.knowledge.loader import ECOM_KEYWORDS, build_runtime_index, load_chapter_ko


class HSKnowledgeGraph:
    def __init__(self) -> None:
        self.g = nx.DiGraph()
        self.by_code: dict[str, dict[str, Any]] = {}
        self.keyword_index: dict[str, list[str]] = dict(ECOM_KEYWORDS)
        self.notes: list[dict[str, Any]] = [
            {
                "id": "note_ch33_1",
                "chapter": 33,
                "text": "제33류는 의료용 조제(제30류)를 포함하지 않는다.",
                "excludes": ["30"],
            },
            {
                "id": "gir1",
                "type": "gir",
                "code": "GIR1",
                "text": "부·류의 표제는 참고용이며, 분류는 항의 용어와 부·류의 주에 따른다.",
            },
            {
                "id": "gir3",
                "type": "gir",
                "code": "GIR3",
                "text": "둘 이상의 항에 해당하면 본질적 특성(Essential Character)을 따른다.",
            },
            {
                "id": "gir6",
                "type": "gir",
                "code": "GIR6",
                "text": "소호 분류는 소호의 용어와 관련 주에 따른다.",
            },
        ]
        self._office_weights: dict[int, dict[tuple[str, str], float]] = {}
        self.curated: dict[str, list[str]] = {}
        self.title_index: dict[str, list[str]] = {}
        self.loaded = False

    def load_from_db(self, db: Session) -> int:
        idx = build_runtime_index(db)
        self.by_code = {
            code: {
                "code": code,
                "title": (r.title_ko or r.title_en),
                "title_en": r.title_en,
                "title_ko": r.title_ko,
                "level": r.level,
                "chapter": r.chapter,
                "parent": r.parent_code,
                "source": r.source,
                "rate": 8.0 if r.chapter in {33, 61, 62} else (0.0 if r.chapter in {85, 90} else 6.5),
            }
            for code, r in idx["by_code"].items()
        }
        self.keyword_index = idx["keyword_index"]
        self.curated = idx.get("curated") or {}
        self.title_index = idx.get("title_index") or {}
        self.g = nx.DiGraph()
        for code, meta in self.by_code.items():
            self.g.add_node(code, **meta)
        for code, meta in self.by_code.items():
            parent = meta.get("parent")
            if parent and parent in self.by_code:
                self.g.add_edge(parent, code, relation="contains")
        # contention edges among sibling chapters commonly contested in e-com
        for a, b in [("33", "21"), ("85", "90"), ("61", "62")]:
            nodes_a = [c for c in self.by_code if c.startswith(a)]
            nodes_b = [c for c in self.by_code if c.startswith(b)]
            if nodes_a and nodes_b:
                self.g.add_edge(nodes_a[0], nodes_b[0], relation="contends_with")
        self.loaded = True
        return len(self.by_code)

    def refresh_office_weights(self, db: Session, office_id: int) -> None:
        rows = db.query(TenantKeywordWeight).filter(TenantKeywordWeight.office_id == office_id).all()
        self._office_weights[office_id] = {(r.keyword, r.hs_code): r.weight for r in rows}

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t for t in re.findall(r"[a-zA-Z가-힣0-9]+", (text or "").lower()) if len(t) >= 2]

    def local_search(self, query: str, office_id: Optional[int] = None, top_k: int = 8) -> list[dict[str, Any]]:
        q = (query or "").lower()
        q_tokens = self._tokens(q)
        scores: dict[str, float] = {}
        office_w = self._office_weights.get(office_id or -1, {})

        # 1) Curated multi-word / keyword phrases (highest priority)
        curated_hit_codes: set[str] = set()
        curated_items = sorted(self.curated.items(), key=lambda kv: len(kv[0]), reverse=True)
        for kw, codes in curated_items:
            if len(kw) < 2:
                continue
            if kw in q:
                weight = 20.0 + min(len(kw), 16) * 0.25
                for c in codes:
                    target = c if c in self.by_code else next((x for x in self.by_code if x.startswith(c[:4])), None)
                    if not target:
                        continue
                    boost = office_w.get((kw, target), office_w.get((kw, c), 1.0))
                    # office learning boost capped so it cannot dominate curated misses forever
                    boost = min(float(boost), 2.5)
                    scores[target] = scores.get(target, 0.0) + weight * boost
                    curated_hit_codes.add(target)

        # 2) Exact query-token hits against title inverted index
        for tok in q_tokens:
            if tok in {"material", "usage", "function"}:
                continue
            for code in self.title_index.get(tok, []):
                # if curated already selected family, lightly boost siblings only
                penalty = 0.35 if curated_hit_codes and code not in curated_hit_codes else 1.0
                scores[code] = scores.get(code, 0.0) + 0.9 * penalty

        # 3) Title overlap ratio (prefer multi-token agreement)
        for code, meta in self.by_code.items():
            if (meta.get("level") or 0) < 4:
                continue
            title = f"{meta.get('title_ko') or ''} {meta.get('title_en') or meta.get('title') or ''}".lower()
            if not title.strip():
                continue
            t_tokens = set(self._tokens(title))
            if not t_tokens or not q_tokens:
                continue
            overlap = [t for t in q_tokens if t in t_tokens and t not in {"material", "usage", "function"}]
            if not overlap:
                continue
            ratio = len(overlap) / max(len(set(q_tokens)), 1)
            level_bonus = 0.25 if (meta.get("level") or 0) >= 10 else 0.1
            damp = 0.25 if curated_hit_codes and code not in curated_hit_codes else 1.0
            scores[code] = scores.get(code, 0.0) + (len(overlap) * 0.55 + ratio * 1.2 + level_bonus) * damp

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        hits = []
        for code, score in ranked:
            meta = self.by_code.get(code, {"code": code, "title": code})
            hits.append(
                {
                    "code": code,
                    "score": round(score, 3),
                    "title": meta.get("title"),
                    "channel": "local",
                    "source": meta.get("source", "kg"),
                }
            )
        return hits

    def global_search(self, query: str, office_id: Optional[int] = None, top_k: int = 8) -> list[dict[str, Any]]:
        local = self.local_search(query, office_id=office_id, top_k=3)
        hits: list[dict[str, Any]] = []
        seen = set()
        for hit in local:
            code = hit["code"]
            digits = re.sub(r"\D", "", code)
            chapter = int(digits[:2]) if len(digits) >= 2 else 0
            for note in self.notes:
                if note.get("chapter") == chapter:
                    hits.append(
                        {
                            "code": code,
                            "score": 0.5,
                            "title": note["text"],
                            "channel": "global",
                            "reason": "legal_note",
                            "note_id": note["id"],
                        }
                    )
            # contend neighbors
            if code in self.g:
                for _, nbr, data in self.g.edges(code, data=True):
                    if data.get("relation") == "contends_with" and nbr not in seen:
                        seen.add(nbr)
                        meta = self.by_code.get(nbr, {})
                        hits.append(
                            {
                                "code": nbr,
                                "score": 0.8,
                                "title": meta.get("title"),
                                "channel": "global",
                                "reason": "chapter_contention",
                            }
                        )
        return hits[:top_k]

    def dual_channel_search(
        self, query: str, routing: str = "dual", office_id: Optional[int] = None
    ) -> dict[str, Any]:
        if routing == "local_only":
            return {"local": self.local_search(query, office_id), "global": [], "routing": routing}
        return {
            "local": self.local_search(query, office_id),
            "global": self.global_search(query, office_id),
            "routing": "dual",
        }

    def tariff_rate(self, hs_code: str) -> float:
        meta = self.by_code.get(hs_code)
        if meta:
            return float(meta.get("rate", 8.0))
        # parent fallback
        digits = re.sub(r"\D", "", hs_code)
        for code, meta in self.by_code.items():
            if re.sub(r"\D", "", code) == digits[:6]:
                return float(meta.get("rate", 8.0))
        return 8.0

    def export_json(self, path: Path) -> None:
        payload = {
            "nodes": list(self.by_code.values())[:500],
            "node_count": len(self.by_code),
            "keywords": {k: v for k, v in list(self.keyword_index.items())[:200]},
            "chapter_ko": load_chapter_ko(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_kg: HSKnowledgeGraph | None = None


def get_kg() -> HSKnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = HSKnowledgeGraph()
    return _kg
