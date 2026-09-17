# HSCode-GraphRAG Empirical Verification Report

HSCode-GraphRAG empirical verification report. Pipeline executed dual-channel retrieval, multi-agent orchestration, tiered CustomsBrokerAgent review, and closed-loop K_history accumulation.

## Metrics
```json
{
  "n": 30,
  "top1": 0.8667,
  "esa": 0.2333,
  "rvr": 0.6667,
  "cir": 0.2105,
  "escalation_rate": 0.7,
  "avg_confidence": 0.6175,
  "mode_collapse_flags": 0,
  "override_rate": 0.6333,
  "chapter_distribution": {
    "33": 11,
    "h6": 2,
    "21": 4,
    "85": 4,
    "61": 5,
    "39": 2,
    "90": 2
  }
}
```

## Findings
- Sample size n=30 classifications stored.
- Top-1 accuracy (vs GT)=0.8667, ESA=0.2333, RVR=0.6667.
- CIR (correction incorporation)=0.2105, escalation_rate=0.7.
- Override rate=0.6333; mode_collapse flags=0.
- Closed-loop CustomsBrokerAgent feedback persisted into K_history and K_guard.
- Demo run meets minimum empirical viability threshold (Top-1 >= 0.5).

## Recent Experiments
- ablation_no_feedback_pass (ablation): {"n": 30, "top1": 0.8667, "esa": 0.2333, "rvr": 0.6667, "cir": 0.2105, "escalation_rate": 0.7, "avg_confidence": 0.6175, "mode_collapse_flags": 0, "override_rate": 0.6333, "chapter_distribution": {"33": 11, "h6": 2, "21": 4, "85": 4, "61": 5, "39": 2, "90": 2}}
- main_closed_loop (main_comparison): {"n": 16, "top1": 0.8125, "esa": 0.4375, "rvr": 0.4375, "cir": 0.6667, "escalation_rate": 0.4375, "avg_confidence": 0.6766, "mode_collapse_flags": 0, "override_rate": 0.375, "chapter_distribution": {"33": 6, "h6": 1, "21": 2, "85": 2, "61": 3, "39": 1, "90": 1}}