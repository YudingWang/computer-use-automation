#!/usr/bin/env bash
# Recapture evidence/ against a running console at http://127.0.0.1:8765/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

"$PY" -m cuas write-golden --entry-url http://127.0.0.1:8765/ --out artifacts/open_subaccount.v1.json

if [[ -n "${XAI_API_KEY:-}" ]]; then
  "$PY" -m cuas discover \
    --goal "Look up member 12345 and open a Savings sub-account named Vacation with initial deposit 500. Stop on the confirmation screen." \
    --target http://127.0.0.1:8765/ \
    --param member_id=12345 --param account_type=Savings \
    --param nickname=Vacation --param initial_deposit=500 \
    --out artifacts/open_subaccount.from_discovery.json \
    --evidence evidence/discovery
else
  "$PY" -m cuas discover --scripted \
    --goal "Look up member 12345 and open a Savings sub-account named Vacation with initial deposit 500. Stop on the confirmation screen." \
    --target http://127.0.0.1:8765/ \
    --param member_id=12345 --param account_type=Savings \
    --param nickname=Vacation --param initial_deposit=500 \
    --out artifacts/open_subaccount.from_discovery.json \
    --evidence evidence/discovery
fi

"$PY" -m cuas replay --artifact artifacts/open_subaccount.v1.json \
  --input member_id=67890 --input account_type=Savings --input nickname=RainyDay --input initial_deposit=250 \
  --auto-operator --evidence evidence/replay-success

"$PY" -m cuas replay --artifact artifacts/open_subaccount.v1.json \
  --input member_id=99999 --input account_type=Savings --input nickname=X --input initial_deposit=1 \
  --allow-risky --evidence evidence/replay-not-found || true

"$PY" -m cuas replay --artifact artifacts/open_subaccount.v1.json \
  --input member_id=24680 --input account_type=Savings --input nickname=X --input initial_deposit=1 \
  --allow-risky --evidence evidence/replay-restricted || true

"$PY" -m cuas replay --artifact artifacts/open_subaccount.v1.json \
  --input member_id=12345 --input account_type=Savings --input nickname=Bad --input initial_deposit=-10 \
  --allow-risky --evidence evidence/replay-validation || true

"$PY" -m cuas replay --artifact artifacts/open_subaccount.v1.json \
  --input member_id=12345 --input account_type=Savings --input nickname=Gate --input initial_deposit=10 \
  --evidence evidence/replay-human-required || true

echo "evidence recaptured"
