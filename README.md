# TradeFlow · HSCode-GraphRAG

관세사 사무실(테넌트)별 **GraphRAG HS 분류 + HITL 의견 학습** 실증 시스템입니다.  
`jsyang9455/hscode_prj` 관세청 HSK 데이터를 기반으로, 챗봇 분류 · 의견서 검토 · 업무자료 학습 화면을 제공합니다.

| 화면 | 역할 |
|------|------|
| 분류 챗봇 | 대화로 상품 설명 입력 → HS 추천 + 선정 사유 |
| 의견서 검토 | 시스템 추천 확인/수정 → 사무실 GraphRAG 학습 |
| 업무자료 학습 | 기존 의견서·메모 업로드/붙여넣기 → 분석 → 학습 반영 |
| 지표·관리 | metrics / weights / HS 적재 |

---

## AWS에서 받아 설치하기 (EC2 + Docker Compose)

Amazon Linux 2023 / Ubuntu 22.04 기준. 보안 그룹에서 **22, 3000, 8000** 포트를 엽니다.

### 1) 서버 준비 + Docker 설치

```bash
# Amazon Linux 2023
sudo dnf update -y
sudo dnf install -y git docker
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# 그룹 반영을 위해 재로그인 후 계속

# Ubuntu 22.04
# sudo apt-get update && sudo apt-get install -y git curl
# curl -fsSL https://get.docker.com | sudo sh
# sudo usermod -aG docker $USER
```

Docker Compose 플러그인:

```bash
# Amazon Linux 2023
sudo dnf install -y docker-compose-plugin || true
docker compose version

# 없으면 공식 바이너리
# sudo mkdir -p /usr/local/lib/docker/cli-plugins
# sudo curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
#   -o /usr/local/lib/docker/cli-plugins/docker-compose
# sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

### 2) GitHub에서 클론

```bash
git clone https://github.com/jsyang9455/tradeflow-hscode-graphrag.git
cd tradeflow-hscode-graphrag
```

또는 원클릭 스크립트:

```bash
curl -fsSL https://raw.githubusercontent.com/jsyang9455/tradeflow-hscode-graphrag/main/scripts/aws_ec2_install.sh | bash
```

### 3) 환경 설정

```bash
cp .env.example .env
# 필요 시 편집
nano .env
```

주요 변수:

| 변수 | 설명 |
|------|------|
| `USE_LLM` | `true` 시 OpenAI로 사유/문서 분석 문장 정리 |
| `OPENAI_API_KEY` | OpenAI API 키 (없으면 규칙 기반 동작) |
| `OPENAI_MODEL` | 기본 `gpt-4o-mini` |
| `CORS_ORIGINS` | 브라우저 출처. EC2면 `http://<PUBLIC_IP>:3000` 포함 |

### 4) 기동

```bash
docker compose up -d --build
docker compose ps
curl -sf http://127.0.0.1:8000/api/v1/health
```

접속:

- UI: `http://<EC2_PUBLIC_IP>:3000`
- API docs: `http://<EC2_PUBLIC_IP>:8000/docs`

### 5) 테스트 계정

앱 기동 시 `DEMO-01` / `test@demo-customs.com` / `Test1234!` 계정이 **자동 생성**됩니다.

계정이 없다면 EC2에서:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/ensure-demo
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@demo-customs.com","password":"Test1234!","office_code":"DEMO-01"}'
```

또는 수동 회원가입:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{
    "email":"test@demo-customs.com",
    "password":"Test1234!",
    "full_name":"테스트관세사",
    "office_code":"DEMO-01",
    "office_name":"데모관세사무소"
  }'
```

### 6) 유용한 운영 명령

```bash
# 로그
docker compose logs -f api

# HS 마스터 재적재
curl -X POST http://127.0.0.1:8000/api/v1/admin/ingest-hs

# 일괄 실증(로그인 토큰 필요)
# curl -X POST http://127.0.0.1:8000/api/v1/classify/batch \
#   -H "Authorization: Bearer <TOKEN>" -H 'Content-Type: application/json' \
#   -d '{"closed_loop":true,"limit":50}'

# 중지 / 재시작
docker compose down
docker compose up -d --build
```

자세한 배포(ECR/CloudFormation): [docs/aws-deployment.md](docs/aws-deployment.md)

---

## 로컬 빠른 시작

```bash
cp .env.example .env
docker compose up -d --build
# UI http://localhost:3000  ·  API http://localhost:8000/docs
```

Docker 없이:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export PYTHONPATH=.
export DATABASE_URL=sqlite:///./data/runtime/hscode.db
mkdir -p data/runtime
uvicorn backend.app.main:app --reload --port 8000
# 다른 터미널
cd frontend && python3 -m http.server 5173
```

## 주요 API

- `POST /api/v1/auth/signup|login`
- `POST /api/v1/chat/sessions` · `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/classify` · `GET /api/v1/opinions/pending` · `POST /api/v1/opinions/broker-review`
- `POST /api/v1/documents/upload|paste` · `.../analyze` · `.../save`
- `GET /api/v1/learning/weights` · `GET /api/v1/metrics`

## 설계 문서

- [docs/design/chat_docs_screens.md](docs/design/chat_docs_screens.md)
- [docs/design/legacy_integration_plan.md](docs/design/legacy_integration_plan.md)
- [docs/aws-deployment.md](docs/aws-deployment.md)
- [docs/sia_harness_loop.md](docs/sia_harness_loop.md) — SIA식 harness 자기개선 루프 (논문/설계)
- [docs/architecture.md](docs/architecture.md)

## 라이선스

연구·실증용. HS 규제 전문은 WCO/관세청 원문을 별도 확보하여 KG를 확장하세요.
