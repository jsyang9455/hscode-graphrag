# HSCode-GraphRAG

**관세사 총괄 에이전트 기반 지식구동 GraphRAG를 활용한 폐루프 규제 준수 HSCode 분류 실증 시스템**

연구계획서(`docs/research_plan_extracted.txt`)의 HSCode-GraphRAG 프레임워크를 동작 가능한 실증 스택으로 구현했습니다.

## 구성

| 계층 | 내용 |
|------|------|
| 지식 층 | HS 규제 지식그래프 (데모 서브그래프) + 시드 상품 케이스 |
| 오케스트레이션 층 | HypothesisAgent / RegulationCritic / Knowledge Loop |
| 검색·생성 층 | Local + Global 이중 채널 GraphRAG, 적응형 라우팅, GIR 근거 |
| 감독 층 | **CustomsBrokerAgent** 계층적 검토, Opinion Report, K_history / K_guard 폐루프 |

### 메타 에이전트 (프로젝트 총괄)

총괄 에이전트(`orchestration/run_pipeline.py`)가 설계·작업지시·이행·검증·재지시를 수행합니다.

1. `data_collect` — 자료 수집·KG export  
2. `analysis` — 폐루프/개방루프 실증 분석  
3. `backend_dev` / `frontend_dev` — 개발 산출물 검증  
4. `api` — REST API 스모크 테스트  
5. `verification` — 수락 기준 검증  
6. `empirical_report` — 실증·검증 보고서 생성  
7. `paper_writer` — DB 저장 데이터 기반 논문 초안 작성  

## 빠른 시작 (로컬, Docker 없이)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
export PYTHONPATH=.
export DATABASE_URL=sqlite:///./data/runtime/hscode.db
mkdir -p data/runtime reports

# 총괄 파이프라인 (시드→분류→검증→보고서→논문)
python -m orchestration.run_pipeline

# API 서버
uvicorn backend.app.main:app --reload --port 8000

# 프론트 (별도 터미널)
cd frontend && python3 -m http.server 5173
```

- API: http://localhost:8000/docs  
- UI: http://localhost:5173  

## Docker / AWS

```bash
docker compose up -d --build
docker compose --profile batch run --rm worker
```

자세한 배포: [docs/aws-deployment.md](docs/aws-deployment.md)

## 주요 API

- `POST /api/v1/classify` — 단일 분류 + 의견서 + 폐루프 저장  
- `POST /api/v1/classify/batch` — 시드 케이스 일괄 실증  
- `POST /api/v1/experiments/run` — 실험 실행 (ablation: `no_feedback`, `local_only`)  
- `GET /api/v1/metrics` — Top-1, ESA, RVR, CIR 등  
- `GET /api/v1/knowledge/history` — K_history  
- `GET /api/v1/papers` / `GET /api/v1/reports/empirical` — 논문·실증 산출물  

## 산출물 위치

- `reports/empirical_verification_report.md`  
- `reports/paper_draft.md`  
- `docs/work_orders/` — 총괄 작업지시서  
- `docs/design/master_plan.json` — 설계 기획  

## 라이선스

연구·실증용. HS 규제 전문은 WCO/관세청 원문을 별도 확보하여 KG를 확장하세요.
