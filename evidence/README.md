# Evidence

This directory is empty until you run the commands in the root README. Do not check in fixture/scripted discovery traces.

| Path | Command |
|------|---------|
| `discovery/` | live `python -m cuas discover …` |
| `replay-success/` | `python -m cuas replay … --allow-risky --evidence evidence/replay-success` |
| `replay-not-found/` | `python -m cuas replay … --input member_id=99999 --allow-risky --evidence evidence/replay-not-found` |
| `replay-human/` | `python -m cuas replay … --headed --wait-for-operator --evidence evidence/replay-human` |

Live discovery is proven by `discovery/provenance.json` (`live: true`, `chatcmpl-…` ids, token usage).
