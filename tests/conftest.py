from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cuas.util import free_port  # noqa: E402
from demo_app.server import app  # noqa: E402


@pytest.fixture(scope="session")
def demo_url() -> str:
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{url}/health", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("demo app did not start")
    yield url + "/"
    server.should_exit = True
