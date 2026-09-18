#!/usr/bin/env bash
# TradeFlow HSCode-GraphRAG — AWS EC2 bootstrap (Amazon Linux 2023 / Ubuntu)
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/jsyang9455/tradeflow-hscode-graphrag.git}"
APP_DIR="${APP_DIR:-$HOME/tradeflow-hscode-graphrag}"

echo "==> Detect OS"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
else
  OS_ID=unknown
fi

echo "==> Install git + docker ($OS_ID)"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf update -y
  sudo dnf install -y git docker
  sudo dnf install -y docker-compose-plugin || true
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y git curl ca-certificates
  if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
  fi
else
  echo "Unsupported OS. Install Docker manually, then re-run."
  exit 1
fi

sudo systemctl enable --now docker || true
if ! docker compose version >/dev/null 2>&1; then
  echo "==> Installing docker compose plugin binary"
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  ARCH=$(uname -m)
  case "$ARCH" in
    aarch64|arm64) CARCH=aarch64 ;;
    *) CARCH=x86_64 ;;
  esac
  sudo curl -fsSL \
    "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${CARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

echo "==> Clone repository"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only || true
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
fi

PUBLIC_IP="$(curl -fsS http://checkip.amazonaws.com 2>/dev/null || curl -fsS https://ifconfig.me 2>/dev/null || echo localhost)"
if grep -q '^CORS_ORIGINS=' .env; then
  sed -i.bak "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://${PUBLIC_IP}:3000,http://localhost:3000,http://127.0.0.1:3000|" .env || true
fi

echo "==> Build & start"
docker compose up -d --build

echo "==> Health check"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null; then
    break
  fi
  sleep 2
done
curl -sf http://127.0.0.1:8000/api/v1/health || true
echo

# Ensure demo login works even on older images
curl -sf -X POST http://127.0.0.1:8000/api/v1/auth/ensure-demo >/dev/null || true

echo "==> Done"
echo "  UI : http://${PUBLIC_IP}:3000"
echo "  API: http://${PUBLIC_IP}:8000/docs"
echo "  App: $APP_DIR"
echo
echo "Demo login:"
echo "  email: test@demo-customs.com"
echo "  password: Test1234!"
echo "  office: DEMO-01"
