"""Adaptive office learning + GraphRAG weight application."""

from __future__ import annotations

from backend.app.services.learning.adaptive import extract_features, apply_pattern_learning
from backend.app.services.knowledge.graph import HSKnowledgeGraph


def test_extract_features_includes_bigrams():
    feats = extract_features(
        description="히알루론산 수분 크림",
        opinion="3304.99로 분류하는 것이 타당",
        conditions=["practice"],
    )
    assert any("히알루론산" in f or "수분" in f for f in feats)
    assert any(" " in f for f in feats) or len(feats) >= 3


def test_local_search_uses_office_token_weights():
    kg = HSKnowledgeGraph()
    kg.by_code = {
        "3304.99.1000": {"code": "3304.99.1000", "title": "beauty cream", "level": 10, "title_ko": "미용크림"},
        "6109.10": {"code": "6109.10", "title": "t-shirts", "level": 10, "title_ko": "티셔츠"},
    }
    kg.title_index = {"cream": ["3304.99.1000"], "티셔츠": ["6109.10"]}
    kg.curated = {}
    kg._office_weights[1] = {("히알루론산", "3304.99.1000"): 2.8, ("수분 크림", "3304.99.1000"): 3.0}
    kg.build_office_phrase_overlay(1)
    hits = kg.local_search("히알루론산 수분 크림", office_id=1, top_k=3)
    assert hits
    assert hits[0]["code"].startswith("3304")
