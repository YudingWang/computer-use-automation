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
                              operator take-control → human clicks (recorded) → resume
```

Cross-cutting: `surface/` (Playwright), `safety/policy.py`, `safety/redaction.py`, `observability/`.

Target UI is `demo_app/` — iframe search, generated IDs, nested tables, not-found / restricted / validation / interstitial.

## Setup

Python 3.11+, Chromium, OpenAI key (discovery only).

```bash
git clone https://github.com/YudingWang/computer-use-automation.git
cd computer-use-automation
python3 -m venv .venv
source .venv/bin/activate
which python    # must be .../computer-use-automation/.venv/bin/python
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env    # set OPENAI_API_KEY
```

If `python -m cuas` says `No module named cuas`, the venv is not active.

## Live discovery

The goal is to **finish creating** the sub-account, including the irreversible confirm. Confirm is still `risky`; unattended replay must pass `--allow-risky` explicitly.

Terminal 1:

```bash
python -m cuas demo-app --port 8765
```

Terminal 2:

```bash
python -m cuas discover \
  --goal "Look up member 12345, open a Savings sub-account named Vacation with initial deposit 500, and confirm creating the account." \
  --target http://127.0.0.1:8765/ \
  --param member_id=12345 \
  --param nickname=Vacation \
  --param initial_deposit=500 \
  --out artifacts/open_subaccount.v1.json \
  --evidence evidence/discovery
```

A live run is proven by `evidence/discovery/provenance.json`: `"live": true`, `openai_id` values like `chatcmpl-…`, non-zero token usage. The API key is never stored.

## Deterministic replay (no LLM)

`--allow-risky` means “I am explicitly approving the Confirm step for this unattended run.”

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=67890 \
  --input nickname=RainyDay \
  --input initial_deposit=250 \
  --allow-risky \
  --evidence evidence/replay-success
```

Not-found is a business outcome, not a crash:

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=99999 \
  --input nickname=X \
  --input initial_deposit=1 \
  --allow-risky \
  --evidence evidence/replay-not-found
```

## Manual human handoff

Without `--allow-risky`, replay pauses on **Confirm Open Account**. Click in the headed Playwright window (not a separately opened browser tab). Clicks are written to `intervention.json` as `human_events`.

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=12345 \
  --input nickname=Handoff \
  --input initial_deposit=10 \
  --headed \
  --wait-for-operator \
  --evidence evidence/replay-human
```

When it prints `=== HUMAN HANDOFF ===`:

```bash
python -m cuas operator take-control --endpoint <url printed by replay>
# click Confirm Open Account in that headed window
python -m cuas operator resume --endpoint <url printed by replay>
```

## Tests

```bash
pytest -q
```

No OpenAI key required. Scripted LLM client is a **test fixture only**.

## Evidence

| Path | Source |
|------|--------|
| `evidence/discovery/` | live `discover` |
| `evidence/replay-success/` | unattended replay with `--allow-risky` |
| `evidence/replay-not-found/` | `member_id=99999` |
| `evidence/replay-human/` | headed handoff; `human_events` must be non-empty |

`REPORT.md` is the design write-up.
