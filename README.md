# Computer-Use Automation System

interface.ai take-home: an LLM discovers how to operate a legacy credit-union console **once**. The successful run is compiled into a typed capability. Production invocation is **deterministic replay** — no model in the decision loop.

```
live LLM discovery → compiler → artifacts/open_subaccount.v1.json → replay(params) → no LLM
```

## Architecture

```
python -m cuas discover          observe → OpenAI → policy → act → compile
        │
        ▼
artifacts/open_subaccount.v1.json     typed inputs/outputs, locator chain, checkpoints
        │
        ▼
python -m cuas replay            no LLM; locators + checkpoints + outcome detectors
        │
        └── risky Confirm ──► pause same headed browser
                              operator take-control → human clicks → resume
```

Cross-cutting: `surface/` (Playwright), `safety/policy.py`, `safety/redaction.py`, `observability/`.

Target UI is `demo_app/` — iframe search, generated IDs, nested tables, not-found / restricted / validation / interstitial.

## Setup

Python 3.11+, Chromium, OpenAI key (discovery only).

```bash
cd /Users/yh-yao/Downloads/computer-use-automation
python3 -m venv .venv
source .venv/bin/activate          # prompt should show (.venv), not anaconda
which python                       # must be .../computer-use-automation/.venv/bin/python
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env               # set OPENAI_API_KEY
```

Every later command in this README assumes that venv is active. If `python -m cuas` says `No module named cuas`, you are on the wrong interpreter.

## Live discovery

Terminal 1:

```bash
python -m cuas demo-app --port 8765
```

Terminal 2 — this is the required genuine LLM run. It writes `evidence/discovery/` and compiles `artifacts/open_subaccount.v1.json`.

```bash
python -m cuas discover \
  --goal "Look up member 12345 and open a Savings sub-account named Vacation with initial deposit 500. Stop on the confirmation screen." \
  --target http://127.0.0.1:8765/ \
  --param member_id=12345 \
  --param account_type=Savings \
  --param nickname=Vacation \
  --param initial_deposit=500 \
  --out artifacts/open_subaccount.v1.json \
  --evidence evidence/discovery
```

A live run is proven by `evidence/discovery/provenance.json`: `"live": true`, `openai_id` values like `chatcmpl-…`, non-zero token usage. The API key is never stored.

## Deterministic replay (no LLM)

Uses the artifact from discovery. Different member:

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=67890 \
  --input account_type=Savings \
  --input nickname=RainyDay \
  --input initial_deposit=250 \
  --allow-risky \
  --evidence evidence/replay-success
```

`--allow-risky` is for unattended happy-path capture. Member not found is a business outcome, not a crash:

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=99999 \
  --input account_type=Savings \
  --input nickname=X \
  --input initial_deposit=1 \
  --allow-risky \
  --evidence evidence/replay-not-found
```

## Manual human handoff

Replay pauses on irreversible **Confirm Open Account**. The headed Playwright window **stays open**; you click in that same window.

Terminal 2:

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=12345 \
  --input account_type=Savings \
  --input nickname=Handoff \
  --input initial_deposit=10 \
  --headed \
  --wait-for-operator \
  --evidence evidence/replay-human
```

When it prints `=== HUMAN HANDOFF ===`, Terminal 3:

```bash
python -m cuas operator take-control --endpoint <url printed by replay>
# click Confirm Open Account in the headed browser
python -m cuas operator resume --endpoint <url printed by replay>
```

`--headed` keeps the live session visible and waits for the operator. Do not close the browser.

## Tests

```bash
pytest -q
```

No OpenAI key required. Scripted LLM client is a **test fixture only**.

## Evidence

Generate after live discovery / replay (do not commit placeholders):

| Path | Source |
|------|--------|
| `evidence/discovery/` | live `discover` — provenance, events, trace, result, screenshots |
| `evidence/replay-success/` | `replay` with a different member |
| `evidence/replay-not-found/` | `replay` with `member_id=99999` |
| `evidence/replay-human/` | headed handoff — intervention, events, result, screenshots |

`REPORT.md` is the design write-up.
