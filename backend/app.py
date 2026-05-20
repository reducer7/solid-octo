from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow direct script execution from backend/ while keeping package-style imports.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.common.config_loader import ConfigError, load_engine_config
from backend.database.redis_store import InMemoryStore
from backend.pipeline import PipelineError, process_submission

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def handle_request(raw_request: dict[str, Any], store: InMemoryStore | None = None) -> dict[str, Any]:
    config = load_engine_config(PROJECT_ROOT)
    live_store = store or InMemoryStore()
    return process_submission(raw_request, live_store, config, PROJECT_ROOT)


async def websocket_handler(websocket: Any) -> None:
    local_store = InMemoryStore()
    async for raw_message in websocket:
        try:
            request = json.loads(raw_message)
            response = handle_request(request, store=local_store)
        except (json.JSONDecodeError, PipelineError, ConfigError) as exc:
            response = {"error": str(exc)}
        await websocket.send(json.dumps(response))


def run_dev_websocket_server() -> None:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("Install websockets to run the dev server") from exc

    cfg = load_engine_config(PROJECT_ROOT)["root"]["websocket"]
    _print_dev_links(cfg["host"], int(cfg["port"]))

    async def runner() -> None:
        async with websockets.serve(websocket_handler, cfg["host"], int(cfg["port"])):
            await asyncio.Future()

    asyncio.run(runner())


def _print_dev_links(host: str, port: int) -> None:
    frontend_page = (PROJECT_ROOT / "frontend" / "index.html").resolve()
    websocket_url = f"ws://{host}:{port}"

    print("Solidocto dev server is starting...")
    print(f"WebSocket endpoint: {websocket_url}")
    if frontend_page.exists():
        print(f"Frontend page: {frontend_page.as_uri()}")
    else:
        print(f"Frontend page not found at: {frontend_page}")


if __name__ == "__main__":
    run_dev_websocket_server()
