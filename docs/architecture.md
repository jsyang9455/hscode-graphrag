# Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 SupervisorAgent (총괄)                        │
│  design → work orders → dispatch → verify → remediate       │
└───────────────┬─────────────────────────────────────────────┘
                │
    ┌───────────┼───────────┬────────────┬──────────────┐
    ▼           ▼           ▼            ▼              ▼
 data_collect analysis  backend/fe     api      verification
                              │
                              ▼
              empirical_report → paper_writer
                              │
                              ▼
                     reports/ + PostgreSQL/SQLite

┌─────────────────────────────────────────────────────────────┐
│              HSCode-GraphRAG Runtime (API)                   │
│  Product → Dual GraphRAG → Hypothesis → Critic → Guardrail  │
│           → CustomsBrokerAgent (tiered review)              │
│           → OpinionReport + CorrectionDelta                 │
│           → K_history / K_guard (closed loop)               │
└─────────────────────────────────────────────────────────────┘
```

## Research alignment

| Research item | Implementation |
|---------------|----------------|
| Dual-channel GraphRAG | `services/knowledge/graph.py` local/global search |
| Knowledge loop / K_history | `KnowledgeHistory` model + broker corrections |
| CustomsBrokerAgent | `services/classification/pipeline.py` |
| Tiered review | lightweight vs deep by θ_high |
| Opinion Report | `OpinionReport` + API `/opinions/{id}` |
| Metric guardrails | mode collapse / GIR avoidance flags + K_guard |
| Ablation no-feedback | `closed_loop=false` / experiment ablation |
| RQ metrics | Top-1, ESA, RVR, CIR, escalation |
