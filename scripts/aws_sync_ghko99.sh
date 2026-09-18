#!/usr/bin/env bash
# AWS/EC2 after git pull: ensure DB is seeded from shipped ghko99 CSV, then restart API.
# Usage:
#   bash scripts/aws_sync_ghko99.sh
#   RESTART_CMD='sudo systemctl restart hscode-api' bash scripts/aws_sync_ghko99.sh
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

CSV="data/kcs/ghko99_hscode_enriched.csv"
if [[ ! -f "$CSV" ]]; then
  echo "ERROR: $CSV missing from repo. Re-pull main or run scripts/convert_ghko99_hscode.py"
  exit 1
fi

echo "[1/3] seed DB from shipped ghko99 CSV ($CSV)"
"$PYTHON" - <<'PY'
from backend.app.db.models import init_db, get_session_factory, reset_engine_cache
from backend.app.services.knowledge.loader import seed_default_hs_master
from backend.app.services.knowledge.graph import get_kg
import json

reset_engine_cache()
init_db()
db = get_session_factory()()
try:
    seed = seed_default_hs_master(db, force=True)
    kg = get_kg().load_from_db(db)
    print(json.dumps({**seed, "kg_nodes": kg}, ensure_ascii=False, indent=2))
finally:
    db.close()
PY

echo "[2/3] health sample"
"$PYTHON" - <<'PY'
from backend.app.db.models import get_session_factory, HsCodeRecord, init_db
from backend.app.services.knowledge.graph import get_kg
init_db()
db = get_session_factory()()
n = db.query(HsCodeRecord).count()
hits = get_kg().local_search("인스턴트 커피", top_k=1)
print({"hs_records": n, "sample_top1": hits[0]["code"] if hits else None})
db.close()
PY

if [[ -n "${RESTART_CMD:-}" ]]; then
  echo "[3/3] restart: $RESTART_CMD"
  eval "$RESTART_CMD"
else
  echo "[3/3] skip restart (set RESTART_CMD=... to restart API)"
fi

echo "done — on next API start, seed_default_hs_master runs automatically if DB is empty"
