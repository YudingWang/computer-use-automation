# Evidence

Checked-in runs for this submission:

| Path | Result |
|------|--------|
| `discovery/` | live OpenAI discover (`provenance.json`: `live: true`) |
| `replay-success/` | no-LLM replay, different member → `SUCCESS` + `confirmation_id` |
| `replay-not-found/` | `BUSINESS_OUTCOME` / `MEMBER_NOT_FOUND` |
| `replay-human/` | same-session handoff; `human_events` records Confirm click/submit |

Do not replace `discovery/` with a scripted fixture.
