# AWS 배포 가이드 — HSCode-GraphRAG

## 권장 구성

1. **개발/실증 단일 호스트**: EC2(Amazon Linux 2023) + Docker Compose
2. **운영 확장**: ECR + ECS Fargate + RDS Postgres + ALB (`aws/cloudformation.yml` 골격)

## EC2 + Docker Compose (가장 빠른 실증)

```bash
# 1) EC2에 Docker 설치 후 저장소 클론
git clone <YOUR_REPO_URL> hscode-graphrag
cd hscode-graphrag

# 2) 환경 파일
cp .env.example .env

# 3) 기동
docker compose up -d --build

# 4) 시드 + 총괄 파이프라인
curl -X POST http://localhost:8000/api/v1/admin/seed
docker compose --profile batch run --rm worker

# 5) 접속
# Frontend: http://<EC2_PUBLIC_IP>:3000
# API docs: http://<EC2_PUBLIC_IP>:8000/docs
```

보안 그룹: `80/3000`(프론트), `8000`(API, 필요 시 제한), `22`(SSH).

## ECR 이미지 푸시

```bash
chmod +x aws/deploy.sh
export AWS_REGION=ap-northeast-2
./aws/deploy.sh
```

## 데이터 영속성

- Compose: `pgdata` 볼륨 + `./data`, `./reports` 바인드 마운트
- 논문/실증 보고서는 DB(`empirical_reports`, `paper_artifacts`)와 `reports/`에 동시 저장
