# REPORT

## 1. Architecture

Three objects: a **capability** (the agent-invocable contract), a **surface adapter** (how a computer is perceived and acted on), and a **session with a control lease** (who may act).

Discovery is observe → OpenAI JSON decision → policy → act. A successful trace is compiled into `artifacts/open_subaccount.v1.json` — parameterized, versioned, decoupled from the model transcript. Replay interprets that artifact with no LLM. Both paths share Playwright, the policy engine, redaction, and evidence.

The target is a local CU*CORE-style console (iframe search, generated IDs, nested tables) so we can own not-found, restricted, validation, and interstitial states without touching a public site.

Trade-off: one process plus a loopback operator port, not a worker fleet. The abstractions (adapter, artifact, lease, detectors-as-data) are what would scale; the infrastructure is not built.

## 2. Artifact schema

A capability is a tool, not a step dump:

- `interface` — name, description with `{{params}}` (no instance values like `12345`), typed inputs (`member_id` is a **string** even when numeric; `initial_deposit` is a **number**), outputs that the success page actually yields, outcome codes. Inputs are only those bound in a step (`{{member_id}}`, etc.).
- `implementation.steps[]` — action, ordered locator chain (primary `role_name` plus text/label/placeholder fallbacks), `{{param}}` values, checkpoint, risk class.
- `implementation.known_outcomes` / `recoverables` — page detectors in the artifact, not hardcoded `if url`.
- `binding` — `app_family`, surface kind, entry URL; optional tenant locator overrides.

Locators prefer role + accessible name, then label/placeholder/text, CSS last. Schema version and capability version are separate. The compiler infers this from a live trace; replay does not need a hand-authored artifact.

## 3. Determinism & error handling

Replay renders parameters, resolves a unique locator, re-checks policy, acts, then classifies:

| Result | Meaning | Example |
|---|---|---|
| `SUCCESS` | Success checkpoint + extracted outputs | `confirmation_id=CNF-…` |
| `BUSINESS_OUTCOME` | Legitimate answer, not a crash | `MEMBER_NOT_FOUND`, `MEMBER_RESTRICTED`, `VALIDATION_ERROR` |
| recoverable | Bounded dismiss/wait, then continue | System Notice → Continue |
| `HUMAN_REQUIRED` | Cannot safely proceed | risky confirm, session expired |
| `HARD_FAILURE` | Automation broke | missing target, checkpoint mismatch |

Waits are checkpoints, not sleeps. Fallback strategy is recorded. UI drift is secondary: fallback use is the signal; replay does not mutate an approved artifact.

## 4. Heterogeneity & multi-tenant

The artifact stores intent (`click` a `button` named `Search` in frame `work`). `SurfaceAdapter` maps that onto Playwright today. A desktop adapter would resolve the same `role_name` against an OS accessibility tree — a new adapter, not a new artifact language. Observation is already an accessibility snapshot plus a control list.

Capabilities are owned by `app_family` + version, not by institution. `binding.tenants[]` is the specialization seam (relabel Search → Find Member). Drift: watch fallback and intervention rates per tenant; quarantine; re-discover or add a reviewed override. Not implemented as routing infrastructure.

## 5. Escalation & handoff

Risky/irreversible steps, session-expired recoverables, and unresolved targets escalate.

The handoff is a **control lease** on the same Playwright page:

1. Automation pauses, writes an `Intervention` (reason, step, URL, screenshot).
2. A loopback API (`take-control` / `resume`). DOM listeners on the same Playwright page report click/submit through `expose_function` (not a cross-origin fetch).
3. After `take-control`, the human clicks in **that** browser; each click/submit is appended to `intervention.human_events` and `events.jsonl`.
4. `resume` returns the lease. If the risky step’s checkpoint is already true, replay skips re-clicking it.

`--headed --wait-for-operator` is the submission path. `--allow-risky` is an explicit unattended approval of Confirm, not the default. A scripted operator exists only in tests.

## 6. Safety

The same policy engine gates discovery and replay: host allowlist (`127.0.0.1` / `localhost`), allowed action types, no `eval_js`. Reads/searches are safe; form fill is reversible; Confirm Open Account is risky and, on replay, requires a human unless `--allow-risky` (evidence capture only).

Sensitive inputs are parameterized out of artifacts. Logs and persisted JSON (`events.jsonl`, `trace.json`) go through the same recursive redaction (`member_id` and secret-shaped keys). API keys stay in the environment. Each run truncates `events.jsonl` so evidence folders do not accumulate prior attempts. Screenshots are synthetic demo data; production would need image redaction, encryption, and retention. The allowlist is host/action based, not a full entitlement graph.

## 7. Cuts

Not built: desktop adapter, remote browser streaming, artifact draft→approved lifecycle, bounded LLM repair of a failed replay step, queues, catalog API, per-tenant routing.

Next: reliability over N replays, locator telemetry, and an explicit approval record so unattended risky replay is a reviewed state rather than a flag.
