# Evidence

Each `cuas discover` / `cuas replay` run truncates `events.jsonl` in its evidence directory. Before the final submission capture, delete the four run folders and regenerate **once** each (commands in the root README).

| Path | Result |
|------|--------|
| `discovery/` | live OpenAI discover (`provenance.json`: `live: true`) |
| `replay-success/` | no-LLM replay, different member → `SUCCESS` + `confirmation_id` |
| `replay-not-found/` | `BUSINESS_OUTCOME` / `MEMBER_NOT_FOUND` |
| `replay-human/` | same-session handoff; `human_events` records Confirm |

Do not replace `discovery/` with a scripted fixture. `trace.json` is redacted with the same rules as `events.jsonl`.
