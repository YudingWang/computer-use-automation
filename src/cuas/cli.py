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
        description="Computer-use automation: discover once with an LLM, replay without one.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser("demo-app", help="Run the local legacy credit-union console")
    demo.add_argument("--host", default=os.environ.get("CUAS_DEMO_HOST", "127.0.0.1"))
    demo.add_argument("--port", type=int, default=int(os.environ.get("CUAS_DEMO_PORT", "8765")))

    disc = sub.add_parser("discover", help="Live LLM observe → decide → act (requires OPENAI_API_KEY)")
    disc.add_argument("--goal", required=True)
    disc.add_argument("--target", required=True)
    disc.add_argument("--param", action="append", default=[], help="key=value (parameterized into the artifact)")
    disc.add_argument("--capability-id", default="open_subaccount")
    disc.add_argument("--headed", action="store_true")
    disc.add_argument("--out", default=str(ROOT / "artifacts" / "open_subaccount.v1.json"))
    disc.add_argument("--evidence", default=str(ROOT / "evidence" / "discovery"))
    disc.add_argument("--model", default=None, help="OpenAI model (default: OPENAI_MODEL or gpt-4o)")

    replay = sub.add_parser("replay", help="Deterministic replay. No LLM.")
    replay.add_argument("--artifact", default=str(ROOT / "artifacts" / "open_subaccount.v1.json"))
    replay.add_argument("--input", action="append", default=[], help="key=value")
    replay.add_argument("--tenant", default=None)
    replay.add_argument("--headed", action="store_true", help="Open a visible browser; implies --wait-for-operator unless --allow-risky")
    replay.add_argument("--allow-risky", action="store_true", help="Execute irreversible steps without a human")
    replay.add_argument("--wait-for-operator", action="store_true", help="Pause on risky steps until take-control / resume")
    replay.add_argument("--evidence", default=None)
    replay.add_argument("--start-url", default=None)

    inspect = sub.add_parser("inspect", help="Print a capability contract")
    inspect.add_argument("artifact")

    op = sub.add_parser("operator", help="Take or return control of a paused replay")
    op.add_argument("action", choices=["status", "take-control", "resume"])
    op.add_argument("--endpoint", help="Operator URL printed when replay pauses")
    op.add_argument("--evidence", help="Evidence dir containing operator_endpoint.json")

    args = parser.parse_args(argv)
    if args.cmd == "demo-app":
        return _demo_app(args.host, args.port)
    if args.cmd == "discover":
        return asyncio.run(_discover(args))
    if args.cmd == "replay":
        return asyncio.run(_replay(args))
    if args.cmd == "inspect":
        return _inspect(Path(args.artifact))
    if args.cmd == "operator":
        return asyncio.run(_operator(args.action, args.endpoint, getattr(args, "evidence", None)))
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


async def _discover(args: argparse.Namespace) -> int:
    from cuas.agent.discovery import DiscoveryAgent
    from cuas.agent.llm import OpenAIClient

    params = _kv(args.param)
    evidence = Path(args.evidence)
    client = OpenAIClient(model=args.model)
    agent = DiscoveryAgent(client, evidence_dir=evidence, headed=args.headed)
    result, events = await agent.run(args.goal, args.target)
    agent.evidence.write_json("result.json", result.model_dump(mode="json"))
    agent.evidence.write_json("trace.json", events)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    provenance_path = evidence / "provenance.json"
    if provenance_path.exists():
        print(f"provenance: {provenance_path}")
    if result.status.value != "SUCCESS":
        return 2
    cap = agent.compile(
        capability_id=args.capability_id,
        description=args.goal,
        params=params,
        entry_url=args.target,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cap.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(cap.summary())
    print(f"wrote {out}")
    return 0


async def _replay(args: argparse.Namespace) -> int:
    from cuas.capability.store import CapabilityStore
    from cuas.replay.executor import ReplayExecutor

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(
            f"No artifact at {artifact}. Run live discovery first:\n"
            "  python -m cuas discover --goal '...' --target http://127.0.0.1:8765/ ...",
            file=sys.stderr,
        )
        return 2
    cap = CapabilityStore(artifact.parent).load(artifact)
    params = _kv(args.input)
    wait = bool(args.wait_for_operator or (args.headed and not args.allow_risky))
    if args.evidence:
        evidence = Path(args.evidence)
    elif wait:
        evidence = ROOT / "evidence" / "replay-human"
    elif params.get("member_id") == "99999":
        evidence = ROOT / "evidence" / "replay-not-found"
    else:
        evidence = ROOT / "evidence" / "replay-success"
    executor = ReplayExecutor(
        cap,
        params,
        evidence_dir=evidence,
        headed=args.headed,
        allow_risky=args.allow_risky,
        wait_for_operator=wait,
        start_url=args.start_url,
        tenant_id=args.tenant,
    )
    result = await executor.run()
    executor.evidence.write_json("result.json", result.model_dump(mode="json"))
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.ok() else 2


def _inspect(path: Path) -> int:
    from cuas.capability.store import CapabilityStore

    cap = CapabilityStore(path.parent).load(path)
    print(cap.summary())
    print(cap.model_dump_json(indent=2))
    return 0


async def _operator(action: str, endpoint: str | None, evidence: str | None) -> int:
    import httpx

    if not endpoint:
        endpoint = _find_operator_endpoint(Path(evidence) if evidence else None)
    if not endpoint:
        print("No operator endpoint. Pass --endpoint URL printed when replay paused.", file=sys.stderr)
        return 2
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


def _find_operator_endpoint(evidence: Path | None) -> str | None:
    candidates: list[Path] = []
    if evidence:
        candidates.append(evidence / "operator_endpoint.json")
    evidence_root = ROOT / "evidence"
    if evidence_root.exists():
        candidates.extend(evidence_root.glob("*/operator_endpoint.json"))
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None
    newest = max(existing, key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text()).get("url")


if __name__ == "__main__":
    raise SystemExit(main())
