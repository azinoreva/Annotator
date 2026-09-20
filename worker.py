"""
Background worker: SSE stream consumer + delayed annotation processor.

Pipeline per update:
  1. subscribe to the server SSE stream and save each update to
     `received_annotations` (idempotently).
  2. On new arrivals, wait PROCESS_DELAY (2s), then pull everything from the
     DB and run: AI categorisation -> AI morality check -> save processed +
     outgoing(sent) -> trigger send -> ack the stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import crud
from routes import call_server as server
from routes import login as login_mod
from routes.ai_access import chat
from routes.annotator import FeedAnnotationEngine
from routes.call_server import RequestUpdates
from routes.model import get_active_model
from routes.morality import ContentSafetyEngine


log = logging.getLogger("annotator.worker")

# Wait before pulling pending items out of the DB for processing.
PROCESS_DELAY = 2.0
# How long to wait before reconnecting to the SSE stream after an error.
RECONNECT_DELAY = 5.0
# How long to wait between attempts when credentials are not configured yet.
WAIT_FOR_CONFIG = 15.0

_ENGINE = FeedAnnotationEngine()
_SAFETY = ContentSafetyEngine()

# Rolling timestamps of finished processing runs (for the /stats rate).
_PROCESS_TIMES: list[float] = []


def processing_rate(window_seconds: float = 60.0) -> int:
    """How many items were processed in the last `window_seconds`."""
    cutoff = time.time() - window_seconds
    return sum(1 for t in _PROCESS_TIMES if t >= cutoff)


# ---------------------------------------------------------------------------
# Stream consumer
# ---------------------------------------------------------------------------

async def _store_received(update: dict) -> None:
    update_id = update.get("update_id")
    if not update_id:
        log.warning("Dropping update without update_id: %r", update)
        return

    await crud.add_received_annotation(
        update_id=update_id,
        datetime=int(time.time()),
        update_data=json.dumps(update, ensure_ascii=False),
        user_id=str(update.get("user_id") or ""),
        category=update.get("category"),
    )


async def stream_loop(queue: asyncio.Queue) -> None:
    """Subscribe to the annotator SSE stream; bank every update in the DB."""
    filters = RequestUpdates()
    _warned = False
    while True:
        # If credentials haven't been configured yet, wait quietly instead
        # of spamming the logs with errors — the operator may still be
        # filling in the settings page.
        if not login_mod.is_configured():
            if not _warned:
                log.info(
                    "No annotator credentials configured yet — waiting for "
                    "them to be added (set them via the config page)."
                )
                _warned = True
            await asyncio.sleep(WAIT_FOR_CONFIG)
            continue

        _warned = False
        try:
            token = await login_mod.ensure_token()
            async for update in server.subscribe_updates(filters, token):
                await _store_received(update)
                await queue.put(update["update_id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.info(
                "SSE stream unavailable right now — retrying in %.0fs.",
                RECONNECT_DELAY,
            )
            await asyncio.sleep(RECONNECT_DELAY)


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

async def process_loop(queue: asyncio.Queue) -> None:
    """
    Wait for arrival signals, sleep PROCESS_DELAY (batching), then process
    everything still pending in the DB. Also does a sweep on startup so items
    stranded in the DB from a previous run are picked up.
    """
    await _process_pending()

    while True:
        try:
            await queue.get()
            # Let more updates trickle in before we open the DB.
            await asyncio.sleep(PROCESS_DELAY)
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            await _process_pending()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Unhandled error in process_loop; continuing.")
            await asyncio.sleep(PROCESS_DELAY)


async def _process_pending() -> None:
    # Processing requires the server credentials; hold off quietly until
    # they are configured so we don't error-spam while the operator is
    # still setting things up.
    if not login_mod.is_configured():
        log.info(
            "Updates are banked but credentials are not configured yet — "
            "processing will resume once they are added."
        )
        return

    received = await crud.list_received_annotations()
    if not received:
        return

    processed = await crud.list_processed_annotations()
    sent = await crud.list_sent_annotations()
    done = {p.update_id for p in processed} | {s.update_id for s in sent}

    for row in received:
        if row.update_id in done:
            continue
        try:
            await _process_one(row)
        except Exception:
            log.exception("Failed to process update_id=%s", row.update_id)


async def _process_one(row) -> None:
    text = _decode_update(row.update_data).get("text") or ""
    text = text.strip()

    # 1) Categorisation (main classification + subcategory correlations).
    result = await asyncio.to_thread(_ENGINE.annotate, text)

    # 2) Morality / content-safety check.
    morality: Optional[dict] = None
    if text:
        morality = await asyncio.to_thread(_morality_check, text)

    annotations = {
        "classification": result.classification,
        "correlations": result.correlations,
    }

    # 3) Persist processed + outgoing.
    await crud.add_processed_annotation(
        update_id=row.update_id,
        datetime=row.datetime,
        update_data=row.update_data,
        category=result.classification,
        annotations=annotations,
        user_id=row.user_id,
        morality=morality,
    )
    await crud.add_sent_annotation(
        update_id=row.update_id,
        datetime=row.datetime,
        update_data=row.update_data,
        category=result.classification,
        annotations=annotations,
        user_id=row.user_id,
        morality=morality,
    )

    # 4) Send — only after the morality check and the DB writes are done.
    token = await login_mod.ensure_token()
    await server.send_annotations(
        update_id=row.update_id,
        user_id=row.user_id,
        category=result.classification,
        annotations=annotations,
        morality=morality,
        token=token,
    )

    # 5) Ack so the server removes it from the annotator stream.
    await server.ack_update(row.update_id, token)
    log.info("Processed %s -> %s (acked).", row.update_id, result.classification)

    # 6) The update is fully processed — remove it from the intake table.
    await crud.delete_received_annotation(row.update_id)
    _PROCESS_TIMES.append(time.time())
    if len(_PROCESS_TIMES) > 10_000:
        del _PROCESS_TIMES[:-10_000]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_update(data: str) -> dict:
    try:
        obj = json.loads(data)
        if isinstance(obj, dict):
            return obj
    except (TypeError, json.JSONDecodeError):
        pass
    return {"text": data}


def _morality_check(text: str) -> dict:
    messages = [
        {"role": "system", "content": _SAFETY.system_message()},
        {"role": "user", "content": _SAFETY.user_message(text)},
    ]
    response = chat(messages, model=get_active_model()).content
    annotation = _SAFETY.parse(response)
    return annotation.model_dump()