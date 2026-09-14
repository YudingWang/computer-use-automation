# Evidence

All runs target the local CU*CORE console (`python -m cuas demo-app`). Demo data is synthetic. Logs mask member ids (`12345` → `***45`).

| Path | What it shows |
|------|----------------|
| `discovery/` | Observe → decide → act loop completing the origination goal. `trace.json` is the raw transcript; `discovery_success.png` is the confirmation screen. |
| `replay-success/` | Deterministic replay for member `67890` with `--auto-operator`. Same live session: automation pauses on `Confirm Open Account`, a human actor clicks it, control returns, `confirmation_id` extracted. |
| `replay-not-found/` | `member_id=99999` → `BUSINESS_OUTCOME / MEMBER_NOT_FOUND` plus screenshot. Not a crash. |
| `replay-restricted/` | Restricted member `24680` → `MEMBER_RESTRICTED`. |
| `replay-validation/` | Negative deposit → `VALIDATION_ERROR`. |
| `replay-human-required/` | Replay without approval/operator. Stops at the irreversible step with an intervention request and screenshot of the review screen. |

The checked-in `discovery/` run used `--scripted` (same loop, policy, surface, and compiler; decisions come from a fixture instead of Grok) because no `XAI_API_KEY` was present when this package was generated. To replace it with the required live LLM run:

```bash
python -m cuas demo-app --port 8765   # other terminal
python -m cuas discover \
  --goal "Look up member 12345 and open a Savings sub-account named Vacation with initial deposit 500. Stop on the confirmation screen." \
  --target http://127.0.0.1:8765/ \
  --param member_id=12345 --param account_type=Savings \
  --param nickname=Vacation --param initial_deposit=500 \
  --evidence evidence/discovery
```
