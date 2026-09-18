"""SIA harness Feedback-Agent unit tests."""

from backend.app.services.agents.harness import (
    DEFAULT_HARNESS,
    FeedbackHarnessAgent,
    apply_patch,
    get_harness,
    reset_harness,
)


def test_feedback_proposes_patch_on_low_prefix4():
    agent = FeedbackHarnessAgent()
    evaluation = {
        "metrics": {"prefix4_hit_rate": 0.4, "chapter_hit_rate": 0.5, "labeled": 8},
        "scored_predictions": [
            {"label_available": True, "match_prefix4": False, "match_chapter": False},
            {"label_available": True, "match_prefix4": False, "match_chapter": True},
        ],
        "quality_score": 0.4,
    }
    out = agent.propose(evaluation, DEFAULT_HARNESS)
    assert out["action"] == "harness_update"
    assert out["patch"]
    assert "force_dual" in out["patch"] or "fusion_gpt_candidate_min_conf" in out["patch"]


def test_apply_patch_clamps():
    patched = apply_patch(DEFAULT_HARNESS, {"local_only_max_tokens": 100, "fusion_gpt_candidate_min_conf": 0.1})
    assert patched["local_only_max_tokens"] <= 20
    assert patched["fusion_gpt_candidate_min_conf"] >= 0.35


def test_harness_persist_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.services.agents.harness._HARNESS_DIR", tmp_path)
    monkeypatch.setattr("backend.app.services.agents.harness._CACHE", {})
    reset_harness(99)
    h = get_harness(99)
    assert h["version"] == 1
    from backend.app.services.agents.harness import save_harness

    save_harness(99, {**h, "force_dual": True}, note="test")
    h2 = get_harness(99)
    assert h2["force_dual"] is True
    assert h2["version"] >= 2
