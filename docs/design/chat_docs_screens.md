# 화면 분리 · 업무자료 학습 설계

## 목표
`jsyang9455/hscode_prj`처럼 **대화형 요청/결과**, **의견서 검토**, **기존 업무자료 학습**을 분리한다.

## 화면
| View | 역할 |
|------|------|
| 분류 챗봇 `#chat` | 세션·말풍선으로 상품 설명 수신 → HS 추천 + LLM/규칙 사유 카드 |
| 의견서 검토 `#opinions` | pending 분류 검토, HS 확정/수정, HITL 학습 |
| 업무자료 학습 `#documents` | 파일/붙여넣기 → 분석 → 수정 → 저장 시 GraphRAG 학습 |
| 지표·관리 `#admin` | metrics, weights, ingest |

## 데이터 흐름
```
챗봇 메시지 → ProductCase → classify → OpinionReport(pending)
                                      ↘ ChatMessage(assistant + broker_brief)

업무자료 upload/paste → WorkDocument
  → analyze (heuristic + optional LLM)
  → 사용자 수정
  → save: KnowledgeHistory + TenantKeywordWeight (+ optional classify → pending)

의견서 broker-review → BrokerOpinionFeedback + 기존 HITL 학습 경로
```

## API
- `POST/GET /chat/sessions`, `GET/POST .../messages`
- `POST /documents/upload|paste`, `POST /documents/{id}/analyze|save`, `GET /documents`

## 저장소
- `chat_sessions`, `chat_messages`
- `work_documents` (+ `data/runtime/uploads/{office_id}/`)
