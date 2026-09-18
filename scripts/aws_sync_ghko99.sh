#!/usr/bin/env bash
# AWS/EC2: pull → convert ghko99 HS master → ingest → reload GraphRAG.
# Usage (from repo root):
#   bash scripts/aws_sync_ghko99.sh
# Optional: RESTART_CMD='sudo systemctl restart hscode-api' bash scripts/aws_sync_ghko99.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

echo "[1/4] ensure ghko99 enriched CSV"
if [[ ! -f data/kcs/ghko99_hscode_enriched.csv ]]; then
  TMP="$(mktemp -d)"
  git clone --depth 1 https://github.com/ghko99/Hscode.git "$TMP/Hscode"
  "$PYTHON" scripts/convert_ghko99_hscode.py --src "$TMP/Hscode"
  rm -rf "$TMP"
else
  echo "  already present: data/kcs/ghko99_hscode_enriched.csv"
fi

echo "[2/4] ingest into DB + load GraphRAG"
"$PYTHON" scripts/import_ghko99_hscode.py

echo "[3/4] quick health check"
"$PYTHON" - <<'PY'
from backend.app.db.models import get_session_factory, HsCodeRecord, init_db
from backend.app.services.knowledge.graph import get_kg
init_db()
db = get_session_factory()()
n = db.query(HsCodeRecord).count()
kg = get_kg().load_from_db(db)
hits = get_kg().local_search("인스턴트 커피", top_k=1)
print({"hs_records": n, "kg_nodes": kg, "sample_top1": hits[0]["code"] if hits else None})
db.close()
PY

if [[ -n "${RESTART_CMD:-}" ]]; then
  echo "[4/4] restart: $RESTART_CMD"
  eval "$RESTART_CMD"
else
  echo "[4/4] skip restart (set RESTART_CMD to restart your API process)"
fi

echo "done"
