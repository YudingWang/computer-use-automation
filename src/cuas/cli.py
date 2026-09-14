from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cuas",
        description="Computer-use automation: discover once, replay without the LLM.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser("demo-app", help="Run the local legacy credit-union console")
    demo.add_argument("--host", default=os.environ.get("CUAS_DEMO_HOST", "127.0.0.1"))
    demo.add_argument("--port", type=int, default=int(os.environ.get("CUAS_DEMO_PORT", "8765")))

    disc = sub.add_parser("discover", help="LLM-driven observe → decide → act (requires XAI_API_KEY)")
    disc.add_argument("--goal", required=True)
    disc.add_argument("--target", required=True)
    disc.add_argument("--param", action="append", default=[], help="key=value (parameterized into the artifact)")
    disc.add_argument("--capability-id", default="open_subaccount")
    disc.add_argument("--headed", action="store_true")
    disc.add_argument("--out", default=str(ROOT / "artifacts" / "open_subaccount.v1.json"))
    disc.add_argument("--evidence", default=str(ROOT / "evidence" / "discovery"))
    disc.add_argument("--scripted", action="store_true", help="Use the scripted teller instead of Grok (tests/demo)")

    replay = sub.add_parser("replay", help="Deterministic replay. No LLM.")
    replay.add_argument("--artifact", default=str(ROOT / "artifacts" / "open_subaccount.v1.json"))
    replay.add_argument("--input", action="append", default=[], help="key=value")
    replay.add_argument("--tenant", default=None)
    replay.add_argument("--headed", action="store_true")
    replay.add_argument("--allow-risky", action="store_true", help="Skip human approval on irreversible steps")
    replay.add_argument("--auto-operator", action="store_true", help="Scripted human takes over the live session")
    replay.add_argument("--wait-for-operator", action="store_true")
    replay.add_argument("--evidence", default=None)
    replay.add_argument("--start-url", default=None)

    inv = sub.add_parser("invoke", help="Invoke a named capability from the catalog")
    inv.add_argument("capability_id")
    inv.add_argument("--input", action="append", default=[])
    inv.add_argument("--allow-risky", action="store_true")
    inv.add_argument("--auto-operator", action="store_true")
    inv.add_argument("--tenant", default=None)

    sub.add_parser("catalog", help="List callable capabilities")
    inspect = sub.add_parser("inspect", help="Print a capability contract")
    inspect.add_argument("artifact")

    op = sub.add_parser("operator", help="Operator commands against a paused run")
    op.add_argument("action", choices=["status", "take-control", "resume"])
    op.add_argument("--endpoint", help="Operator URL from evidence/*/operator_endpoint.json")

    golden = sub.add_parser("write-golden", help="Write the canonical artifact JSON")
    golden.add_argument("--entry-url", default="http://127.0.0.1:8765/")
    golden.add_argument("--out", default=str(ROOT / "artifacts" / "open_subaccount.v1.json"))

    args = parser.parse_args(argv)
    if args.cmd == "demo-app":
        return _demo_app(args.host, args.port)
    if args.cmd == "discover":
        return asyncio.run(_discover(args))
    if args.cmd == "replay":
        return asyncio.run(_replay(args))
    if args.cmd == "invoke":
        return asyncio.run(_invoke(args))
    if args.cmd == "catalog":
        return _catalog()
    if args.cmd == "inspect":
        return _inspect(Path(args.artifact))
    if args.cmd == "operator":
        return asyncio.run(_operator(args.action, args.endpoint))
    if args.cmd == "write-golden":
        return _write_golden(args.entry_url, Path(args.out))
    return 1


def _kv(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"expected key=value, got {item}")
        key, value = item.split("=", 1)
        out[key] = value
    return out


def _demo_app(host: str, port: int) -> int:
    import uvicorn
    from demo_app.server import app

    print(f"CU*CORE console at http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def _write_golden(entry_url: str, out: Path) -> int:
    from cuas.capability.golden import open_subaccount_capability

    cap = open_subaccount_capability(entry_url)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cap.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(cap.summary())
    print(f"wrote {out}")
    return 0


async def _discover(args: argparse.Namespace) -> int:
    from cuas.agent.discovery import DiscoveryAgent, default_open_subaccount_script
    from cuas.agent.llm import ScriptedClient, XAIGrokClient
    from cuas.capability.store import CapabilityStore

    params = _kv(args.param)
    evidence = Path(args.evidence)
    if args.scripted:
        client: Any = ScriptedClient(default_open_subaccount_script(params))
    else:
        client = XAIGrokClient()
    agent = DiscoveryAgent(client, evidence_dir=evidence, headed=args.headed)
    result, events = await agent.run(args.goal, args.target)
    agent.evidence.write_json("result.json", result.model_dump(mode="json"))
    agent.evidence.write_json("trace.json", events)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    if result.status.value == "SUCCESS":
        cap = agent.compile(
            capability_id=args.capability_id,
            description=args.goal,
            params=params,
            entry_url=args.target,
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(cap.model_dump_json(indent=2) + "\n", encoding="utf-8")
        CapabilityStore(ROOT / "artifacts").save(cap)
        print(cap.summary())
        print(f"wrote {out}")
        return 0
    return 2


async def _replay(args: argparse.Namespace) -> int:
    from cuas.capability.golden import approve_confirm_operator
    from cuas.capability.store import CapabilityStore
    from cuas.replay.executor import ReplayExecutor
    from cuas.util import new_id

    cap = CapabilityStore(ROOT / "artifacts").load(Path(args.artifact))
    params = _kv(args.input)
    evidence = Path(args.evidence) if args.evidence else ROOT / "evidence" / f"replay-{new_id('ev')}"
    operator = approve_confirm_operator() if args.auto_operator else None
    executor = ReplayExecutor(
        cap,
        params,
        evidence_dir=evidence,
        headed=args.headed,
        allow_risky=args.allow_risky,
        wait_for_operator=args.wait_for_operator,
        auto_operator=operator,
        tenant_id=args.tenant,
        start_url=args.start_url,
    )
    result = await executor.run()
    executor.evidence.write_json("result.json", result.model_dump(mode="json"))
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.ok() else 2


async def _invoke(args: argparse.Namespace) -> int:
    from types import SimpleNamespace

    artifact = ROOT / "artifacts" / f"{args.capability_id}.v1.0.0.json"
    if not artifact.exists():
        artifact = ROOT / "artifacts" / f"{args.capability_id}.v1.json"
    ns = SimpleNamespace(
        artifact=str(artifact),
        input=args.input,
        tenant=args.tenant,
        headed=False,
        allow_risky=args.allow_risky,
        auto_operator=args.auto_operator,
        wait_for_operator=False,
        evidence=str(ROOT / "evidence" / f"invoke-{args.capability_id}"),
        start_url=None,
    )
    return await _replay(ns)


def _catalog() -> int:
    from cuas.capability.store import CapabilityStore

    store = CapabilityStore(ROOT / "artifacts")
    caps = store.list()
    if not caps:
        print("No capabilities in artifacts/. Run: python -m cuas write-golden")
        return 0
    for cap in caps:
        print(cap.summary())
        print()
    return 0


def _inspect(path: Path) -> int:
    from cuas.capability.store import CapabilityStore

    cap = CapabilityStore(path.parent).load(path)
    print(cap.summary())
    print(cap.model_dump_json(indent=2))
    return 0


async def _operator(action: str, endpoint: str | None) -> int:
    import httpx

    if not endpoint:
        matches = sorted((ROOT / "evidence").glob("*/operator_endpoint.json"))
        if not matches:
            print("No operator endpoint found. Pass --endpoint.")
            return 2
        endpoint = json.loads(matches[-1].read_text())["url"]
    async with httpx.AsyncClient() as client:
        if action == "status":
            r = await client.get(f"{endpoint}/status")
        elif action == "take-control":
            r = await client.post(f"{endpoint}/take-control")
        else:
            r = await client.post(f"{endpoint}/resume")
        print(r.text)
        r.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
