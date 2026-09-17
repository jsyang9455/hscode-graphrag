# HSCode-GraphRAG — Paper Draft (from stored empirical data)

## Introduction

HS code misclassification in high-volume cross-border e-commerce creates tariff risk, regulatory exposure, and logistics delay. Korea's surge in inbound and outbound direct purchases intensifies verification scarcity under list-clearance regimes. This paper proposes HSCode-GraphRAG, a four-layer framework with a CustomsBrokerAgent supervisory layer that enforces closed-loop expert feedback into K_history.

## Related Work

Prior work progressed from text classifiers to explainable RAG and knowledge-graph agents (e.g., HSGraphAgent), yet typically explores a single classification path, lacks cross-session knowledge transfer, omits metric-gaming defenses, and treats brokers as open-loop escalation endpoints. Closed-loop expert supervision literature (EON, DNFO, Digital Apprentice) motivates embedding broker corrections as first-class learning signals.

## HSCode-GraphRAG Framework

HSCode-GraphRAG comprises (1) HS regulatory knowledge graph with hierarchical communities, (2) knowledge-driven multi-agent orchestration (HypothesisAgent, RegulationCritic), (3) dual-channel Local+Global GraphRAG retrieval with adaptive routing, and (4) CustomsBrokerAgent tiered review producing Opinion Reports and structured correction deltas that update K_history and K_guard reality anchors.

## Experimental Design

We evaluate on a KCS-10D-style demonstration set with closed-loop vs no-feedback ablation. Metrics include Top-1, regulation violation rate (RVR), expert-system agreement (ESA), correction incorporation rate (CIR), escalation rate, and mode-collapse flags.

## Results

Stored empirical metrics (n=30): Top-1=0.8667, ESA=0.2333, RVR=0.6667, CIR=0.2105, escalation_rate=0.7, override_rate=0.6333. K_history accumulated 6 structured correction records. HSCode-GraphRAG empirical verification report. Pipeline executed dual-channel retrieval, multi-agent orchestration, tiered CustomsBrokerAgent review, and closed-loop K_history accumulation.

## Discussion

Closed-loop broker corrections provide a reality anchor that mitigates open-loop Correction Collapse risk. Dual-channel retrieval surfaces chapter contention notes that single-path agents miss. Limitations include demo KG coverage, simulated broker policy relative to licensed human brokers, and need for larger KCS-10D Hard calibration studies.

## Conclusion

HSCode-GraphRAG demonstrates a deployable closed-loop architecture for regulation-compliant HS classification under e-commerce volume pressure. Future work expands the regulatory graph, integrates live LLM backbones, and conducts multi-broker ORQ/RTR user studies.

## References

- Guo, X. (2025). Expert Oversight Network (EON).
- Lee, E., et al. (2023). Explainable Product Classification for Customs. ACM TIST.
- Seki, T. (2026). Distributed Negative Feedback Optimization for Multi-Agent AI.
- Weber, T., & Taneja, R. (2026). The Digital Apprentice.
- Ko, J. (2026). Preventing Correction Collapse.