"""GraphRAG + GPT fusion merger tests (no live OpenAI required)."""

from backend.app.services.classification.llm_recommend import merge_graph_and_gpt


def test_merge_agree_boosts():
    out = merge_graph_and_gpt(
        graph_proposal="3304.99.1000",
        graph_alternatives=["3304.20"],
        search={"local": [{"code": "3304.99.1000", "score": 40}]},
        gpt={
            "recommended_hs": "3304.99.1000",
            "confidence": 0.9,
            "alternatives": ["3304.91"],
            "agree_with_graphrag": True,
        },
    )
    assert out["proposed"].startswith("3304.99")
    assert out["fusion"] == "hybrid_agree"
    assert out["confidence_boost"] > 0


def test_merge_gpt_picks_other_candidate():
    out = merge_graph_and_gpt(
        graph_proposal="6109.10.0000",
        graph_alternatives=["6116.10.0000"],
        search={
            "local": [
                {"code": "6109.10.0000", "score": 20},
                {"code": "6116.10.0000", "score": 18},
            ]
        },
        gpt={
            "recommended_hs": "6116.10.0000",
            "confidence": 0.8,
            "alternatives": ["6109.10.0000"],
            "agree_with_graphrag": False,
        },
    )
    assert out["proposed"].startswith("6116")
    assert out["fusion"] == "hybrid_gpt_from_candidates"


def test_merge_keeps_graph_when_gpt_offlist_weak():
    out = merge_graph_and_gpt(
        graph_proposal="8471.30.0000",
        graph_alternatives=[],
        search={"local": [{"code": "8471.30.0000", "score": 55}]},
        gpt={
            "recommended_hs": "9999.99.9999",
            "confidence": 0.4,
            "alternatives": [],
            "agree_with_graphrag": False,
        },
    )
    assert out["proposed"].startswith("8471")
    assert out["fusion"] in {"hybrid_graph_primary_gpt_alt", "hybrid_agree"}
