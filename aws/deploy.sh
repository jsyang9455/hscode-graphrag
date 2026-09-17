#!/usr/bin/env bash
# Deploy HSCode-GraphRAG containers to AWS (ECR + optional ECS/EC2 Docker host)
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-2}"
PROJECT="${PROJECT_NAME:-hscode-graphrag}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_API="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$PROJECT-api"
ECR_FE="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$PROJECT-frontend"

echo "==> Login ECR ($REGION)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

for repo in "$PROJECT-api" "$PROJECT-frontend"; do
  aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" --region "$REGION" >/dev/null
done

echo "==> Build & push images"
docker build -f backend/Dockerfile -t "$ECR_API:latest" .
docker build -f frontend/Dockerfile -t "$ECR_FE:latest" .
docker push "$ECR_API:latest"
docker push "$ECR_FE:latest"

echo "==> Images pushed:"
echo "  $ECR_API:latest"
echo "  $ECR_FE:latest"
echo "Next: deploy docker-compose on EC2/ECS using these images, or update cloudformation.yml parameters."
