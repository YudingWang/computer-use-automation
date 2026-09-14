# Computer-Use Automation System

Take-home for interface.ai: an LLM discovers how to operate a legacy credit-union console **once**. The successful run is compiled into a typed, versioned **capability**. Production invocation is **deterministic replay** — no model in the decision loop — with explicit business outcomes, bounded recovery, policy guardrails, and a real same-session human handoff.

```
goal → observe/decide/act (Grok) → capability artifact → replay(params) → SUCCESS | BUSINESS_OUTCOME | HUMAN_REQUIRED
```

## Setup

Requires Python 3.11+ and Chromium (Playwright).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
python -m cuas write-golden --entry-url http://127.0.0.1:8765/
```

Discovery talks to [xAI Grok](https://docs.x.ai) (`grok-4.6`) via `XAI_API_KEY`. Copy `.env.example` to `.env` and fill the key. Replay, tests, and the demo console do **not** need a model.

```bash
cp .env.example .env   # then set XAI_API_KEY
```

## Demo path

Terminal 1 — start the local back-office console (hostile markup, iframe, generated IDs, no test IDs):

```bash
python -m cuas demo-app --port 8765
```

The console is at http://127.0.0.1:8765/. Synthetic members:

| Member ID | What happens |
|-----------|----------------|
| `12345` | Alice Chen, active — happy path |
| `67890` | Bob Rivera, active — second invocation |
| `24680` | Priya Nair, restricted — `MEMBER_RESTRICTED` |
| `99999` | `MEMBER_NOT_FOUND` |
| deposit `< 0` | inline validation → `VALIDATION_ERROR` |
| `?simulate=interstitial` | unexpected System Notice (dismiss + continue) |
| `?brand=eastside` | same vendor product, relabeled chrome |

Terminal 2 — **discover** (live LLM; this is the required genuine computer-use run):

```bash
python -m cuas discover \
  --goal "Look up member 12345 and open a Savings sub-account named Vacation with initial deposit 500. Stop on the confirmation screen." \
  --target http://127.0.0.1:8765/ \
  --param member_id=12345 \
  --param account_type=Savings \
  --param nickname=Vacation \
  --param initial_deposit=500 \
  --capability-id open_subaccount \
  --out artifacts/open_subaccount.v1.json \
  --evidence evidence/discovery
```

Without a live key, the same loop can be exercised with a scripted teller (not a substitute for the Grok run above):

```bash
python -m cuas discover --scripted \
  --goal "Open a savings sub-account named Vacation for member 12345 with initial deposit 500" \
  --target http://127.0.0.1:8765/ \
  --param member_id=12345 --param account_type=Savings \
  --param nickname=Vacation --param initial_deposit=500 \
  --evidence evidence/discovery-scripted
```

**Replay** the artifact for a different member. `--auto-operator` is the production-shaped path: the irreversible confirm is *not* auto-approved; a human (here, a scripted operator) takes the **same live Playwright session**, clicks confirm, and hands control back.

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --input member_id=67890 \
  --input account_type=Savings \
  --input nickname=RainyDay \
  --input initial_deposit=250 \
  --auto-operator \
  --evidence evidence/replay-success
```

Not-found is a **business outcome**, not a crash:

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

Same-vendor tenant variant (Eastside labels: "Member Number" / "Find Member"):

```bash
python -m cuas replay \
  --artifact artifacts/open_subaccount.v1.json \
  --tenant eastside \
  --start-url "http://127.0.0.1:8765/?brand=eastside" \
  --input member_id=12345 --input account_type=Savings \
  --input nickname=East --input initial_deposit=50 \
  --auto-operator
```

Agent-facing catalog:

```bash
python -m cuas catalog
python -m cuas invoke open_subaccount \
  --input member_id=12345 --input account_type=Savings \
  --input nickname=Catalog --input initial_deposit=10 \
  --auto-operator
```

Paused runs expose a loopback operator API (URL is in `evidence/<run>/operator_endpoint.json`):

```bash
python -m cuas operator status
python -m cuas operator take-control
python -m cuas operator resume
```

## Tests (no LLM)

```bash
pytest -q
```

## Layout

```
demo_app/                 local CU*CORE console (the target surface)
src/cuas/
  models/                 capability schema, actions, results
  surface/                SurfaceAdapter + Playwright web implementation
  agent/                  discovery loop, Grok client, prompts
  capability/             compiler, store, golden artifact
  replay/                 deterministic executor
  safety/                 allowlist + risk classes + redaction
  handoff/                control lease + operator API
  observability/          JSONL evidence
artifacts/                versioned capabilities
evidence/                 discovery + replay traces
REPORT.md                 design write-up
```

## Evidence

See [`evidence/README.md`](evidence/README.md). Checked in: a successful discovery trace, a parameterized artifact, a no-LLM replay with extracted `confirmation_id`, a `MEMBER_NOT_FOUND` business outcome (with screenshot), and a same-session human handoff on the irreversible confirm.

Secrets never go in the repo. Demo data is synthetic. Member ids are masked in logs (`12345` → `***45`).
