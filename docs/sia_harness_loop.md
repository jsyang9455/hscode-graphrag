# SIA식 Harness 개선 루프 (MVP)

TradeFlow HSCode-GraphRAG에 도입한 **SIA(Self Improving AI with Harness & Weight Updates)** 스타일 **harness-only** 자기개선 루프 설계·구현 문서입니다.  
논문 Methods / System Design 절에 반영하기 위한 기술 설명용입니다.

관련 논문: Hebbar et al., *SIA: Self Improving AI with Harness & Weight Updates*, arXiv:2605.27276.

---

## 1. 개요

관세 HS 분류 시스템은 (1) 사무실별 GraphRAG 검색·학습 가중치, (2) GPT 공동 추천, (3) 관세사 HITL 의견서 학습을 이미 갖추고 있다.  
SIA MVP는 여기에 **Feedback-Agent가 에이전트 scaffold(harness)를 갱신**하는 루프를 추가한다.

| SIA 축 | 본 시스템 대응 | MVP |
|--------|----------------|-----|
| Harness update | 라우팅·GraphRAG↔GPT 융합 문턱·K_history 규칙·학습 토큰 cap | **적용** |
| Weight update (LoRA 등) | GPT API 모델 가중치 재학습 | 미적용 (모델 고정) |
| Office GraphRAG weights | `TenantKeywordWeight` + HITL/업무자료 | 기존 경로 유지, 루프 내 시뮬 의견서로 병행 |

**핵심 주장:** LLM 가중치를 바꾸지 않고도, 블라인드 평가를 verifier로 삼아 scaffold를 선택적으로 진화시키면 사무실 단위 분류 안정성·적중률을 개선할 수 있다.

---

## 2. 시스템 위치

```
┌──────────────────────────────────────────────────────────────────┐
│                    Runtime Classify Path                         │
│  Product → Dual GraphRAG → Hypothesis → GPT fusion → Draft       │
│              ▲                                                   │
│              │ get_harness(office_id)                            │
│         OfficeHarness (JSON, tenant-scoped)                      │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ save / rollback
┌──────────────────────────────────────────────────────────────────┐
│                 SIAHarnessLoop (meta loop)                       │
│  BlindTester → Evaluator → Simulated HITL → FeedbackHarnessAgent │
│       → trial harness → accept if score ≥ baseline               │
└──────────────────────────────────────────────────────────────────┘
```

연구용 오케스트레이션(`orchestration/SupervisorAgent`)과 별개로, **런타임 API**에서 사무실별로 동작한다.

---

## 3. 구성 요소

### 3.1 OfficeHarness (scaffold)

경로: `data/runtime/harness/office_{office_id}.json`  
모듈: `backend/app/services/agents/harness.py`

대표 파라미터:

| 파라미터 | 파이프라인 단계 | 의미 |
|----------|-----------------|------|
| `force_dual`, `local_only_max_tokens`, `dual_force_tokens` | Retrieve / routing | local-only vs dual GraphRAG |
| `fusion_gpt_candidate_min_conf`, `fusion_weak_graph_score`, `fusion_weak_graph_gpt_conf`, `fusion_agree_prefer_gpt_specific` | GPT co-recommend merge | GraphRAG 1순위 vs GPT 재선정 |
| `k_history_min_overlap`, `k_history_protect_score`, `k_history_related_score` | HypothesisAgent | 과거 HITL 오버라이드 엄격도 |
| `office_token_boost_cap` | Local GraphRAG scoring | 사무실 학습 토큰 반영 상한 |

버전(`version`)이 증가하며, 분류 trajectory의 retrieve 스텝에 `harness_version`이 기록된다.

### 3.2 BlindTester (외부 사용자 대리)

모듈: `backend/app/services/agents/loop.py`, `sia_loop.py`의 고정 프로브

- 정답 HS를 분류기에 노출하지 않음 (`ground_truth_hs=None`).
- SIA 루프는 **고정 프로브 세트**(`SIA_PROBES`)만 사용해 라운드 간 비교 가능성을 확보한다.
- 프로브 예: 히알루론산 크림, 면 티셔츠, 스테인리스 보온병, 노트북, 가죽 지갑, 면 양말, 플라스틱 장난감, 무선 이어폰 등.

### 3.3 Evaluator (verifier / reward)

모듈: `EvaluatorAgent`

- `prefix4_hit_rate`, `prefix6_hit_rate`, `chapter_hit_rate`, `quality_score` 등을 산출.
- 루프 점수:  
  `score = 0.55·prefix4 + 0.25·chapter + 0.20·quality_score`  
  (라벨이 없으면 quality_score만 사용).

### 3.4 FeedbackHarnessAgent (SIA Feedback-Agent, harness-only)

모듈: `FeedbackHarnessAgent.propose`

블라인드 실패 패턴에 따른 **규칙 기반** 패치 제안 (MVP):

- 장/호 미스 → `force_dual`, dual 진입 문턱 완화  
- prefix4 미스 → GPT 후보 재선정 문턱 완화  
- GraphRAG 약신호 → weak-graph GPT override 허용 확대  
- 오적용 의심 → K_history overlap 강화  
- 중간 정확도 → `office_token_boost_cap` 상향  

LLM 메타에이전트 호출은 MVP에 포함하지 않는다 (결정론·재현성·비용).

### 3.5 Simulated HITL (의견서 시뮬)

미스 케이스에 대해 `apply_broker_feedback`으로 기대 HS를 사무실 학습 스토어에 반영한다.  
이는 SIA harness와 **직교하는 office GraphRAG weight** 경로이며, 실무 HITL+scaffold 공진화를 모사한다.

### 3.6 Accept / Rollback

harness 패치 적용 후 **동일 프로브로 재블라인드**하여 `trial_score ≥ score`일 때만 채택, 아니면 rollback.  
잘못된 scaffold 자동 배포를 막는 안전장치이다.

---

## 4. 알고리즘 (한 라운드)

```
harness ← load_or_reset(office)
for r in 1..R:
  preds ← BlindClassify(SIA_PROBES | harness)      # GT 미노출
  eval  ← Evaluate(preds, expected_hs)
  score ← Score(eval)

  opinions ← SimulateBrokerHITL(misses)            # optional
  proposal ← FeedbackAgent.propose(eval, harness)

  if proposal.action == harness_update:
    save(trial_harness)
    trial_score ← Score(Evaluate(BlindClassify(...)))
    if trial_score ≥ score: accept
    else: rollback
  persist round metrics
emit report: baseline → final, Δscore, patches
```

실험 기록: `ExperimentRun.experiment_type = "sia_harness_loop"`.

---

## 5. API · 운영 UI

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/agents/sia-harness` | 현재 사무실 harness |
| POST | `/api/v1/agents/sia-harness/reset` | harness 기본값 초기화 |
| POST | `/api/v1/agents/sia-harness/run` | body: `{rounds, apply_opinions, reset}` |
| GET | `/api/v1/agents/blind-eval/latest` | blind / sia 실험 이력 |

프론트 **운영 지표** 화면: `SIA Harness 개선 루프` 버튼.

구현 파일:

- `backend/app/services/agents/harness.py`
- `backend/app/services/agents/sia_loop.py`
- `backend/app/api/agents.py`
- 분류 연동: `pipeline.py`, `llm_recommend.py`, `knowledge/graph.py`

---

## 6. 파일럿 실험 결과 (로컬)

조건: 고정 8프로브, 3라운드, harness + 시뮬 HITL.  
(scaffold/HITL 효과 분리 측정 시 GPT co-recommend는 off로 실행 가능.)

| 지표 | Baseline | Final |
|------|----------|-------|
| 종합 점수 | 0.698 | **1.000** (Δ **+0.302**) |
| prefix4 hit rate | 0.625 | **1.000** |
| chapter hit rate | 0.750 | **1.000** |
| 시뮬 의견서 | — | 1라운드 3건 |
| harness 채택 | — | 1/3 라운드 |

1라운드에서 Feedback-Agent가 `force_dual`, GPT 융합 문턱 완화, 학습 토큰 cap 상향 등을 제안·채택했고, 이후 라운드는 게이트 통과로 noop를 유지했다.

**해석 문장(논문용):**  
*SIA-style harness loop uses blind evaluation as a verifier to selectively update the office-scoped agent scaffold. Combined with simulated broker HITL, prefix-4 hit rate on a fixed probe set rose from 62.5% to 100% over three rounds.*

---

## 7. 기존 모듈과의 관계

| 모듈 | 역할 | SIA와의 관계 |
|------|------|----------------|
| Office GraphRAG weights | HITL/업무자료 online 학습 | 루프 내 의견서 시뮬로 병행 |
| GraphRAG + GPT-5.6 hybrid | 분류 추론 | harness가 융합·라우팅 규칙 조절 |
| Blind / Evaluator / Supervisor | 단발 품질 게이트·재학습 | SIA는 **다라운드·버전·rollback**이 명시된 scaffold 진화 |
| Orchestration Supervisor | 연구 메타 파이프라인 | 런타임 SIA와 분리 |

---

## 8. 한계와 향후 작업

1. Feedback-Agent는 규칙 기반 MVP이며, LLM 메타에이전트는 미도입.  
2. GPT/LoRA **weight update** 축은 미포함.  
3. 시뮬 의견서는 실관세사 HITL의 대리이다.  
4. 프로브 규모가 작아 일반화 성능은 확장 벤치마크가 필요하다.  
5. 향후: LLM Feedback-Agent, harness A/B 온라인 배포, 소형 랭커 LoRA와의 dual-lever SIA.

---

## 9. 인용

```bibtex
@article{hebbar2026sia,
  title   = {SIA: Self Improving AI with Harness \& Weight Updates},
  author  = {Hebbar, Prannay and Manawat, Yogendra and Verboomen, Samuel
             and Ivanova, Alesia and Palanimalai, Selvam and Bhatia, Kunal
             and Baskaran, Vignesh},
  journal = {arXiv preprint arXiv:2605.27276},
  year    = {2026},
  url     = {https://arxiv.org/abs/2605.27276}
}
```
