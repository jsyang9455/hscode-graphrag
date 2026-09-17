#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=.
export DATABASE_URL="${DATABASE_URL:-sqlite:///./data/runtime/hscode.db}"
mkdir -p data/runtime reports orchestration/artifacts
python -m orchestration.run_pipeline
python -m pytest tests -q
echo "Verification complete."
