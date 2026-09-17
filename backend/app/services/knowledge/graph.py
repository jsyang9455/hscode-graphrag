"""HS Regulatory Knowledge Graph (demo subset for empirical pipeline)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

# Minimal but realistic HS regulatory subgraph for demo / empirical runs.
HS_NODES = [
    {"id": "ch33", "type": "chapter", "code": "33", "title": "Essential oils and resinoids; perfumery, cosmetic or toilet preparations"},
    {"id": "h3304", "type": "heading", "code": "3304", "title": "Beauty or make-up preparations and preparations for the care of the skin"},
    {"id": "h3304.99", "type": "subheading", "code": "3304.99", "title": "Other skin care preparations"},
    {"id": "h3304.99.1000", "type": "tariff", "code": "3304.99.1000", "title": "Creams / lotions", "rate": 6.5},
    {"id": "h3304.99.9000", "type": "tariff", "code": "3304.99.9000", "title": "Other beauty preparations", "rate": 8.0},
    {"id": "ch21", "type": "chapter", "code": "21", "title": "Miscellaneous edible preparations"},
    {"id": "h2106", "type": "heading", "code": "2106", "title": "Food preparations not elsewhere specified"},
    {"id": "h2106.90", "type": "subheading", "code": "2106.90", "title": "Other food preparations"},
    {"id": "h2106.90.9099", "type": "tariff", "code": "2106.90.9099", "title": "Other food preparations nes", "rate": 8.0},
    {"id": "ch85", "type": "chapter", "code": "85", "title": "Electrical machinery and equipment"},
    {"id": "h8517", "type": "heading", "code": "8517", "title": "Telephone sets and other apparatus for transmission"},
    {"id": "h8517.13", "type": "subheading", "code": "8517.13", "title": "Smartphones"},
    {"id": "h8517.13.0000", "type": "tariff", "code": "8517.13.0000", "title": "Smartphones", "rate": 0.0},
    {"id": "ch61", "type": "chapter", "code": "61", "title": "Articles of apparel and clothing accessories, knitted"},
    {"id": "h6109", "type": "heading", "code": "6109", "title": "T-shirts, singlets and other vests, knitted"},
    {"id": "h6109.10", "type": "subheading", "code": "6109.10", "title": "Of cotton"},
    {"id": "h6109.10.0000", "type": "tariff", "code": "6109.10.0000", "title": "Cotton T-shirts", "rate": 13.0},
    {"id": "ch39", "type": "chapter", "code": "39", "title": "Plastics and articles thereof"},
    {"id": "h3923", "type": "heading", "code": "3923", "title": "Articles for the conveyance or packing of goods, of plastics"},
    {"id": "h3923.30", "type": "subheading", "code": "3923.30", "title": "Carboys, bottles, flasks"},
    {"id": "h3923.30.0000", "type": "tariff", "code": "3923.30.0000", "title": "Plastic bottles", "rate": 6.5},
    {"id": "ch90", "type": "chapter", "code": "90", "title": "Optical, photographic, measuring instruments"},
    {"id": "h9018", "type": "heading", "code": "9018", "title": "Instruments used in medical sciences"},
    {"id": "h9018.90", "type": "subheading", "code": "9018.90", "title": "Other medical instruments"},
    {"id": "h9018.90.9000", "type": "tariff", "code": "9018.90.9000", "title": "Other medical instruments", "rate": 0.0},
]

# Legal notes / exclusion rules (simplified)
LEGAL_NOTES = [
    {
        "id": "note_ch33_1",
        "chapter": 33,
        "text": "This chapter does not cover medicinal preparations of heading 30.03/30.04.",
        "excludes": ["30"],
    },
    {
        "id": "note_ch21_1",
        "chapter": 21,
        "text": "Food preparations with therapeutic claims may be classified in Chapter 30.",
        "excludes": [],
    },
    {
        "id": "note_ch85_1",
        "chapter": 85,
        "text": "Parts of apparatus of this chapter are generally classified with the apparatus.",
        "excludes": [],
    },
    {
        "id": "gir1",
        "type": "gir",
        "code": "GIR1",
        "text": "Titles of sections/chapters are for ease of reference; classification by terms of headings and notes.",
    },
    {
        "id": "gir3",
        "type": "gir",
        "code": "GIR3",
        "text": "When goods are prima facie classifiable under two or more headings, essential character prevails.",
    },
    {
        "id": "gir6",
        "type": "gir",
        "code": "GIR6",
        "text": "Classification in subheadings shall be determined according to terms of those subheadings.",
    },
]

EDGES = [
    ("ch33", "h3304", "contains"),
    ("h3304", "h3304.99", "contains"),
    ("h3304.99", "h3304.99.1000", "contains"),
    ("h3304.99", "h3304.99.9000", "contains"),
    ("ch21", "h2106", "contains"),
    ("h2106", "h2106.90", "contains"),
    ("h2106.90", "h2106.90.9099", "contains"),
    ("ch85", "h8517", "contains"),
    ("h8517", "h8517.13", "contains"),
    ("h8517.13", "h8517.13.0000", "contains"),
    ("ch61", "h6109", "contains"),
    ("h6109", "h6109.10", "contains"),
    ("h6109.10", "h6109.10.0000", "contains"),
    ("ch39", "h3923", "contains"),
    ("h3923", "h3923.30", "contains"),
    ("h3923.30", "h3923.30.0000", "contains"),
    ("ch90", "h9018", "contains"),
    ("h9018", "h9018.90", "contains"),
    ("h9018.90", "h9018.90.9000", "contains"),
    # contention links (cross-chapter competition)
    ("h3304", "h2106", "contends_with"),
    ("h9018", "h8517", "contends_with"),
]

KEYWORD_INDEX: dict[str, list[str]] = {
    "cream": ["3304.99.1000", "3304.99.9000"],
    "lotion": ["3304.99.1000"],
    "serum": ["3304.99.1000", "3304.99.9000"],
    "cosmetic": ["3304.99.9000", "3304.99.1000"],
    "skincare": ["3304.99.1000"],
    "beauty": ["3304.99.9000"],
    "supplement": ["2106.90.9099"],
    "food": ["2106.90.9099"],
    "vitamin": ["2106.90.9099"],
    "smartphone": ["8517.13.0000"],
    "phone": ["8517.13.0000"],
    "mobile": ["8517.13.0000"],
    "t-shirt": ["6109.10.0000"],
    "tshirt": ["6109.10.0000"],
    "cotton": ["6109.10.0000"],
    "apparel": ["6109.10.0000"],
    "bottle": ["3923.30.0000"],
    "plastic": ["3923.30.0000"],
    "packaging": ["3923.30.0000"],
    "medical": ["9018.90.9000"],
    "instrument": ["9018.90.9000"],
    "thermometer": ["9018.90.9000"],
}


class HSKnowledgeGraph:
    def __init__(self) -> None:
        self.g = nx.DiGraph()
        for node in HS_NODES:
            self.g.add_node(node["id"], **node)
        for u, v, rel in EDGES:
            self.g.add_edge(u, v, relation=rel)
        self.notes = LEGAL_NOTES
        self.by_code = {d["code"]: d for d in HS_NODES if "code" in d}
        self.id_by_code = {d["code"]: d["id"] for d in HS_NODES if "code" in d}

    def local_search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        q = query.lower()
        scores: dict[str, float] = {}
        for kw, codes in KEYWORD_INDEX.items():
            if kw in q:
                for c in codes:
                    scores[c] = scores.get(c, 0.0) + 1.5
        for node in HS_NODES:
            title = (node.get("title") or "").lower()
            overlap = sum(1 for tok in q.split() if tok and tok in title)
            if overlap and node.get("type") == "tariff":
                scores[node["code"]] = scores.get(node["code"], 0.0) + overlap * 0.4
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        hits = []
        for code, score in ranked:
            meta = self.by_code.get(code, {"code": code, "title": code})
            hits.append({"code": code, "score": round(score, 3), "title": meta.get("title"), "channel": "local"})
        return hits

    def global_search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Community / contention aware search for exclusion cross-check."""
        local = self.local_search(query, top_k=3)
        hits = []
        seen = set()
        for hit in local:
            code = hit["code"]
            nid = self.id_by_code.get(code)
            if not nid:
                continue
            # walk up to heading then follow contends_with
            for pred in self.g.predecessors(nid):
                for nbr in self.g.successors(pred):
                    rel = self.g.edges[pred, nbr].get("relation")
                    if rel == "contends_with":
                        for desc in nx.descendants(self.g, nbr):
                            data = self.g.nodes[desc]
                            if data.get("type") == "tariff" and data["code"] not in seen:
                                seen.add(data["code"])
                                hits.append(
                                    {
                                        "code": data["code"],
                                        "score": 0.8,
                                        "title": data.get("title"),
                                        "channel": "global",
                                        "reason": "chapter_contention",
                                    }
                                )
            # chapter notes
            chapter = int(code[:2])
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
        return hits[:top_k]

    def dual_channel_search(self, query: str, routing: str = "dual") -> dict[str, Any]:
        if routing == "local_only":
            local = self.local_search(query)
            return {"local": local, "global": [], "routing": routing}
        if routing == "global_only":
            global_hits = self.global_search(query)
            return {"local": [], "global": global_hits, "routing": routing}
        return {
            "local": self.local_search(query),
            "global": self.global_search(query),
            "routing": "dual",
        }

    def tariff_rate(self, hs_code: str) -> float:
        meta = self.by_code.get(hs_code, {})
        return float(meta.get("rate", 8.0))

    def export_json(self, path: Path) -> None:
        payload = {"nodes": HS_NODES, "edges": EDGES, "notes": LEGAL_NOTES, "keywords": KEYWORD_INDEX}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_kg: HSKnowledgeGraph | None = None


def get_kg() -> HSKnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = HSKnowledgeGraph()
    return _kg
