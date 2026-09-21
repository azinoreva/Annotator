# main.py
import os
import sys
import json
import time
import asyncio
import logging
import shutil
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn

import worker
from db import init_db, close_db
from routes import ai_access
from routes import call_server
from routes import settings as settings_routes
from routes.login import configure as configure_login, ensure_token
from routes.model import set_active_model


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("annotator")

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_MODEL  = "llama3.2:1b"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
SERVICE_PORT   = 25340

# ---------------------------------------------------------------------------
# In-memory state (shared across the running process)
# ---------------------------------------------------------------------------
STATE: dict = {
    "model_name":          None,
    "annotator_id":        None,
    "annotator_password":  None,
    "base_url":            None,
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        log.warning("Config not found at %s — starting with empty config", CONFIG_PATH)
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to read config.json — using empty config")
        return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------
def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def install_ollama() -> None:
    """Install ollama via the official script on Linux/macOS."""
    log.info("Ollama binary not found — installing...")
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True, check=True,
        )
    elif sys.platform == "win32":
        raise RuntimeError(
            "Please install Ollama manually from https://ollama.com/download"
        )
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def is_ollama_running() -> bool:
    """Bounded, non-raising probe — never blocks longer than the probe timeout."""
    return ai_access.runtime_available(OLLAMA_BASE_URL)


def start_ollama_server() -> subprocess.Popen:
    log.info("Ollama server not running — starting it...")
    proc = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Poll with the bounded probe; the loop cannot hang because each probe
    # is capped by ai_access.PROBE_TIMEOUT.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if is_ollama_running():
            log.info("Ollama server is up.")
            return proc
        time.sleep(1)
    proc.terminate()
    raise RuntimeError("Ollama server did not become ready within 30 s")


def ensure_model(model_name: str) -> None:
    """Pull the requested model if it isn't already present locally."""
    ai_access.ensure_model(model_name, host=OLLAMA_BASE_URL)
    log.info("Model '%s' ready.", model_name)


# ---------------------------------------------------------------------------
# Lifespan: runs on startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load config
    cfg = load_config()

    # 2. Ensure ollama is installed
    if not is_ollama_installed():
        install_ollama()
    else:
        log.info("Ollama binary found at %s", shutil.which("ollama"))

    # 3. Ensure ollama server is running
    ollama_proc: subprocess.Popen | None = None
    if not is_ollama_running():
        ollama_proc = start_ollama_server()
    else:
        log.info("Ollama server already running on %s", OLLAMA_BASE_URL)

    # 4. Resolve model name (persist default into config on first run)
    model_name = cfg.get("model_name") or DEFAULT_MODEL
    if cfg.get("model_name") != model_name:
        cfg["model_name"] = model_name
        save_config(cfg)
        log.info("Persisted default model '%s' to config.", model_name)

    # 5. Make sure the model is pulled
    ensure_model(model_name)

    # 6. Load in-memory state
    STATE["model_name"]         = model_name
    STATE["annotator_id"]       = cfg.get("annotator_id")
    STATE["annotator_password"] = cfg.get("annotator_password")
    STATE["base_url"]           = cfg.get("base_url")
    app.state.settings = STATE
    log.info(
        "State loaded: model=%s, annotator_id=%s, base_url=%s",
        STATE["model_name"], STATE["annotator_id"], STATE["base_url"],
    )

    # 7. Database: open the sqlite connection (Tortoise) and make sure the
    #    tables (incl. the morality columns) exist.
    await init_db()
    log.info("Database initialized (sqlite via tortoise).")

    # 8. Runtime configuration for the worker: model + server credentials.
    set_active_model(STATE["model_name"])
    if STATE["base_url"]:
        call_server.set_base_url(STATE["base_url"])
    configure_login(
        annotator_id=STATE["annotator_id"],
        annotator_password=STATE["annotator_password"],
        base_url=STATE["base_url"],
    )

    # 9. Warm up the annotator login (non-fatal — worker retries on failure).
    if STATE["annotator_id"]:
        try:
            await ensure_token()
            log.info("Logged in to aggregator as %s.", STATE["annotator_id"])
        except Exception:
            log.exception("Initial annotator login failed; worker will retry.")
    else:
        log.warning(
            "No annotator credentials configured — set them via "
            "POST /save_initial_settings and restart."
        )

    # 10. Start the worker loops: SSE stream consumer + the 2s processor.
    _queue = asyncio.Queue()
    _stream_task = asyncio.create_task(worker.stream_loop(_queue), name="stream_loop")
    _process_task = asyncio.create_task(worker.process_loop(_queue), name="process_loop")

    try:
        yield
    finally:
        # --- shutdown ---
        for _task in (_stream_task, _process_task):
            _task.cancel()
        await asyncio.gather(*(_task for _task in (_stream_task, _process_task)),
                             return_exceptions=True)

        await close_db()
        log.info("Database connections closed.")

        if ollama_proc is not None:
            log.info("Shutting down ollama server (pid=%s)...", ollama_proc.pid)
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ollama_proc.kill()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Annotator Service", lifespan=lifespan)
app.include_router(settings_routes.router)


# Small helper endpoint so you can inspect STATE at runtime
@app.get("/state")
async def get_state():
    return {
        "model_name":   STATE["model_name"],
        "annotator_id": STATE["annotator_id"],
        "base_url":     STATE["base_url"],
        "server_base_url": call_server.ACTIVE_BASE_URL,
        # deliberately not returning the password
    }


# The desktop dashboard (Annotator_visual) polls these three endpoints:
#   GET /health  -> 200 {"status": "ok"}              (is the service up?)
#   GET /stats   -> counts + rate                     (dashboard LCDs)
#   GET /events  -> SSE stream of {"stats": {...}}    (live dashboard feed)
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stats")
async def stats():
    from models.annotation_model import (
        ProcessedAnnotation,
        ReceivedAnnotation,
        SentAnnotation,
    )

    received = await ReceivedAnnotation.all().count()
    processed = await ProcessedAnnotation.all().count()
    sent = await SentAnnotation.all().count()
    # "categories" = subcategory assignments (the correlations on each
    # processed annotation), tracked in memory so it grows with every item.
    categories = worker.subcategory_count()
    rate = worker.processing_rate()

    return {
        "received": received,
        "sent": sent,
        "processed": processed,
        "categories": categories,
        "rate": rate,
    }


@app.get("/events")
async def events():
    """Server-Sent Events: pushes fresh stats every 3 seconds."""

    async def _stat_stream():
        while True:
            data = {"stats": await stats()}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        _stat_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    cfg = load_config()
    port = int(os.environ.get("ANNOTATOR_PORT") or cfg.get("port") or SERVICE_PORT)
    uvicorn.run(app, host="0.0.0.0", port=port)