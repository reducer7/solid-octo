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
from backend.database.redis_store import InMemoryStore, RedisStore, ScoreStore
from backend.pipeline import PipelineError, process_submission

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_store(root_cfg: dict[str, Any]) -> ScoreStore:
    redis_cfg = root_cfg["redis"]
    if not bool(redis_cfg.get("enabled", True)):
        return InMemoryStore()

    try:
        import redis

        client = redis.from_url(redis_cfg["url"])
        client.ping()
        return RedisStore(client=client, entry_key_prefix=redis_cfg["entry_key_prefix"])
    except Exception as exc:  # pragma: no cover - depends on local runtime services
        print(f"Redis unavailable ({exc}); falling back to in-memory store.")
        return InMemoryStore()


def handle_request(raw_request: dict[str, Any], store: ScoreStore | None = None) -> dict[str, Any]:
    config = load_engine_config(PROJECT_ROOT)
    live_store = store or _build_store(config["root"])
    return process_submission(raw_request, live_store, config, PROJECT_ROOT)


async def websocket_handler(websocket: Any, store: ScoreStore | None = None) -> None:
    import websockets.exceptions

    config = load_engine_config(PROJECT_ROOT)
    local_store = store or _build_store(config["root"])
    loop = asyncio.get_running_loop()

    async for raw_message in websocket:
        progress_queue: asyncio.Queue[str] = asyncio.Queue()

        def on_progress(step: str) -> None:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                json.dumps({"type": "progress", "step": step}),
            )

        response: dict[str, Any]
        try:
            request = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            response = {"error": str(exc)}
        else:
            task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
                asyncio.to_thread(
                    process_submission, request, local_store, config, PROJECT_ROOT, on_progress
                )
            )
            # Stream progress messages to the client while the pipeline runs.
            closed = False
            while not task.done():
                await asyncio.wait({task}, timeout=0.05)
                while not progress_queue.empty():
                    msg = progress_queue.get_nowait()
                    try:
                        await websocket.send(msg)
                    except websockets.exceptions.ConnectionClosed:
                        task.cancel()
                        closed = True
                        break
                if closed:
                    return
            # Drain any progress messages queued before the task finished.
            while not progress_queue.empty():
                try:
                    await websocket.send(progress_queue.get_nowait())
                except websockets.exceptions.ConnectionClosed:
                    return
            try:
                response = await task
            except (PipelineError, ConfigError) as exc:
                response = {"error": str(exc)}

        try:
            await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            break


def run_dev_websocket_server() -> None:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("Install websockets to run the dev server") from exc

    config = load_engine_config(PROJECT_ROOT)
    cfg = config["root"]["websocket"]
    shared_store = _build_store(config["root"])
    _print_dev_links(cfg["host"], int(cfg["port"]))

    async def runner() -> None:
        async with websockets.serve(
            lambda websocket: websocket_handler(websocket, shared_store),
            cfg["host"],
            int(cfg["port"]),
        ):
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
