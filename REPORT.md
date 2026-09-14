# REPORT

## 1. Architecture

The system is a vertical slice of “model discovers, artifact executes.” Three objects sit at the center:

- **Capability** — a versioned, reviewable contract. The calling agent only needs `interface` (typed inputs/outputs/outcome codes). Replay uses `implementation` (steps, locator chains, checkpoints, detectors). `binding` attaches the capability to an app family and optional tenant overrides.
- **Surface adapter** — the seam between “what to do” and “how this computer is driven.” Today that is Playwright; the artifact never stores Playwright calls.
- **Session + control lease** — discovery, replay, and the operator act on the same live page. Only `AUTOMATION` or `HUMAN` may act at a time.

Discovery is a small observe → policy → act loop (Grok `grok-4.6`, JSON decisions). A compiler then *replaces* the transcript with a parameterized artifact: invocation values become `{{member_id}}`, controls become role/name/placeholder chains, and app-family detectors for “member not found” / interstitials are copied in. Replay never asks a model what to do next.

Trade-off: a single-process CLI plus a loopback operator HTTP port, not a worker fleet. The assignment penalizes premature infrastructure; the abstractions (adapter, artifact, lease, detectors-as-data) are what would scale to many tenants.

Target: a local CU*CORE-style console, not a public site. That lets us own exceptional states (not-found, restricted, validation, interstitial, timeout, slowness) and hostile markup (iframe search workspace, nested tables, generated IDs, missing labels) without ToS issues.

## 2. Artifact schema

A capability is not a step list. It is an **invocable tool**:

- `interface` — name, description, inputs (with `sensitive`), outputs, declared outcome codes.
- `implementation.steps[]` — ordered actions with an ordered **locator chain**, optional `{{param}}` values, a post-step checkpoint, and a risk class.
- `implementation.known_outcomes` / `recoverables` — page detectors that live *in the artifact*, not in Python `if url == ...` branches. The engine is generic; a new core-banking screen adds detectors, not code.
- `binding.tenants[]` — locator/text overrides for institutions running the same vendor product.

Locators prefer accessibility identity (`role` + accessible name), then label/placeholder/text, and CSS only as a last-resort fallback (used here for the unlabeled nickname/deposit fields). Schema version and capability version are separate.

## 3. Determinism & error handling

Replay renders parameters, resolves a unique locator, re-checks policy, acts, then classifies the page:

| Result | Meaning | Example |
|---|---|---|
| `SUCCESS` | Success checkpoint + extracted outputs | `confirmation_id=CNF-…` |
| `BUSINESS_OUTCOME` | Declared, legitimate answer | `MEMBER_NOT_FOUND`, `MEMBER_RESTRICTED`, `VALIDATION_ERROR` |
| recoverable | Bounded dismiss/wait, then continue | System Notice → click Continue |
| `HUMAN_REQUIRED` | Cannot safely proceed | risky confirm, session expired, unknown dialog |
| `HARD_FAILURE` | Automation broke | missing target, checkpoint mismatch, policy deny |

Waits are checkpoints (`visible_text` / `title` / `url_regex` / `role_name`), not sleeps. Fallbacks are recorded (`strategy` on the event). UI drift is secondary: fallback use is the early signal; repeated checkpoint failure quarantines the artifact rather than mutating it at runtime.

## 4. Heterogeneity & multi-tenant

**Surfaces.** The artifact stores intent (`click` a `button` named `Search` in frame `work`). `SurfaceAdapter` maps that onto Playwright today. A desktop adapter would resolve the same `role_name` against an OS accessibility tree; a screenshot adapter would be a *different* adapter with a weaker locator strategy, not a different artifact language. Observation is already an accessibility snapshot plus a control list, which is the portable perception format.

**Tenants.** Capabilities are owned by `app_family` + compatible versions, not by institution. Eastside Community CU is the stand-in: same flows, different chrome (`Member ID`→`Member Number`, `Search`→`Find Member`). Replay `--tenant eastside` merges `TenantOverride`s. Drift: watch fallback rates and intervention rate per tenant/version; quarantine; re-discover or add a reviewed override. Never silently rewrite an approved artifact during replay.

## 5. Escalation & handoff

Stuck is detected by policy (risky/irreversible), recoverables with `on_match: escalate` (session expired), unresolved targets, or discovery dead-ends.

The handoff is a **control lease**, not a new browser:

1. Automation pauses and writes an `Intervention` (reason, step, URL, screenshot, expected/observed).
2. A loopback operator API is bound to that Playwright page (`/take-control`, `/act`, `/resume`, plus DOM listeners for a headed human).
3. `HUMAN` acts on the same page; events are attributed `actor=human`.
4. `resume` returns the lease. If the risky step’s checkpoint is already true, replay **skips** re-clicking it.

`--auto-operator` is a scripted human on that seam (used in tests and the demo). `--wait-for-operator` plus `--headed` is the real teller: use the open window, then `python -m cuas operator resume`. A full co-browse console is out of scope; the lease, the same session, and the evidence trail are real.

## 6. Safety

The same `PolicyEngine` gates discovery and replay: host allowlist (`127.0.0.1`/`localhost`), allowed action types, blocked action types, and risk classes. Reads/searches are `safe`; form fill is `reversible`; `Confirm Open Account` is `risky` and, on replay, requires approval or a human. There is no `eval_js` path.

Sensitive inputs are parameterized out of artifacts. Logs mask `member_id` and secret-shaped keys. Screenshots are taken on failure/escalation against synthetic data; a production bank would need image redaction, encryption, and retention. Limits: the allowlist is host/action based, not a full entitlement graph, and screenshot redaction is not implemented.

## 7. Cuts

Left out on purpose: desktop adapter implementation, remote browser streaming, artifact draft→approved lifecycle, bounded LLM repair of a single failed replay step, queues/multi-tenant routing, and image-level PII redaction.

Next: reliability scoring over N replays, per-tenant locator telemetry, and an approval record so unattended replay of `risky` steps is an explicit, reviewed state rather than a CLI flag.
