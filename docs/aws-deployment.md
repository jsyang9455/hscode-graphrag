# AWS 배포 가이드 — TradeFlow HSCode-GraphRAG

## 권장 구성

1. **실증 단일 호스트**: EC2(Amazon Linux 2023) + Docker Compose ← 가장 빠름  
2. **운영 확장**: ECR + ECS Fargate + RDS Postgres + ALB (`aws/cloudformation.yml`)

---

## A. EC2에서 GitHub 클론 후 설치 (권장)

보안 그룹: `22`(SSH), `3000`(UI), `8000`(API, 필요 시 IP 제한).

```bash
# --- Amazon Linux 2023 ---
sudo dnf update -y
sudo dnf install -y git docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
# SSH 재접속

sudo dnf install -y docker-compose-plugin || true
docker compose version

git clone https://github.com/jsyang9455/tradeflow-hscode-graphrag.git
cd tradeflow-hscode-graphrag
cp .env.example .env

# (선택) LLM 사유 정리
# echo 'USE_LLM=true' >> .env
# echo 'OPENAI_API_KEY=sk-...' >> .env

# 공개 IP를 CORS에 추가 (예)
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com || curl -s https://ifconfig.me)
sed -i "s|CORS_ORIGINS=.*|CORS_ORIGINS=http://${PUBLIC_IP}:3000,http://localhost:3000|" .env

docker compose up -d --build
curl -sf http://127.0.0.1:8000/api/v1/health

echo "UI  http://${PUBLIC_IP}:3000"
echo "API http://${PUBLIC_IP}:8000/docs"
```

원클릭:

```bash
curl -fsSL https://raw.githubusercontent.com/jsyang9455/tradeflow-hscode-graphrag/main/scripts/aws_ec2_install.sh | bash
```

테스트 계정 생성:

```bash
# 최신 이미지: 기동 시 자동 생성. 없으면:
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/ensure-demo

# 로그인 확인
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@demo-customs.com","password":"Test1234!","office_code":"DEMO-01"}'
```

---

## B. ECR 이미지 푸시

로컬/CI에서:

```bash
chmod +x aws/deploy.sh
export AWS_REGION=ap-northeast-2
export PROJECT_NAME=tradeflow-hscode-graphrag
./aws/deploy.sh
```

EC2에서는 푸시된 이미지를 `docker compose`에서 참조하도록 `docker-compose.yml`의 `build:` 대신 `image:` 로 교체해 사용합니다.

## C. 데이터 영속성

- Compose 볼륨 `pgdata` (Postgres)
- 바인드: `./data`, `./reports`, `./data/runtime/uploads`
- HS 마스터: `data/kcs/kcs_hsk_priority.csv` (우선) / 전체 마스터는 별도 적재

## D. 트러블슈팅

| 증상 | 조치 |
|------|------|
| UI는 뜨고 API 실패 | 보안그룹 8000, `docker compose logs api` |
| CORS 오류 | `.env`의 `CORS_ORIGINS`에 `http://<IP>:3000` 추가 후 `docker compose up -d` |
| 로그인 버튼 무반응(구버전) | 프론트 이미지 재빌드, 강력 새로고침 |
| DB 스키마 누락 | `docker compose restart api` (startup 시 `create_all`) |
