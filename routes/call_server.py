# updates_client.py
import json
import logging
from datetime import date

import httpx
from enum import Enum
from typing import Annotated, AsyncIterator, Optional
from pydantic import BaseModel, Field

import crud


log = logging.getLogger("annotator.call_server")


class Categories(str, Enum):
    GENERAL       = "general"
    TECH          = "tech"
    SPORTS        = "sports"
    NEWS          = "news"
    ENTERTAINMENT = "entertainment"


class RequestUpdates(BaseModel):
    user_ids:   Optional[list[str]] = Field(None, max_length=100)
    category:   Optional[Categories] = Field(None)
    categories: Optional[list[Categories]] = Field(None, max_length=50)
    hashtags:   Optional[list[Annotated[str, Field(max_length=20)]]] = Field(None, max_length=10)
    before:     Optional[int] = Field(default=0, le=500)
    limit:      int = Field(default=20, le=500)


UPDATES_API_BASE = "http://127.0.0.1:8000"

# Resolved at runtime — main.py calls set_base_url(...) with the value from
# config.json so the whole service follows the configured server.
ACTIVE_BASE_URL = UPDATES_API_BASE


def set_base_url(url: str) -> None:
    """Override the aggregator base URL used by the server client functions."""
    global ACTIVE_BASE_URL
    if url:
        ACTIVE_BASE_URL = url.rstrip("/")


def _resolve_base_url(base_url: Optional[str]) -> str:
    return (base_url or ACTIVE_BASE_URL).rstrip("/")


async def subscribe_updates(
    filters: RequestUpdates,
    token: str,
    base_url: Optional[str] = None,
) -> AsyncIterator[dict]:
    """
    Open GET /api/updates/subscribe as SSE and yield the parsed JSON payload
    of each `event: update`. Runs until the caller breaks out of the loop
    or the connection drops (httpx raises, caller decides whether to retry).
    """
    url = f"{_resolve_base_url(base_url)}/api/updates/subscribe"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
    }
    params = filters.model_dump(exclude_none=True)
    if params.get("before") == 0:
        params.pop("before")

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url, headers=headers, params=params) as r:
            r.raise_for_status()

            event_type: Optional[str] = None
            data_lines: list[str] = []

            async for line in r.aiter_lines():
                if line == "":
                    # end of one SSE frame
                    if event_type == "update" and data_lines:
                        yield json.loads("\n".join(data_lines))
                    event_type, data_lines = None, []
                    continue

                if line.startswith(":"):
                    continue  # comment / heartbeat

                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]

                if field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)
                # `id` and `retry` ignored here — add handling if you need them


async def ack_update(
    update_id: str,
    token: str,
    base_url: Optional[str] = None,
) -> None:
    """POST /api/updates/ack. Raises on non-2xx."""
    url = f"{_resolve_base_url(base_url)}/api/updates/ack"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json={"update_id": update_id})
        r.raise_for_status()


async def send_annotations(
    update_id: str,
    user_id: str,
    category: str,
    annotations: dict,
    morality: Optional[dict] = None,
    token: str = "",
    base_url: Optional[str] = None,
) -> None:
    """
    POST the finished annotations back to the server.

    annotations is expected to be {"classification": ..., "correlations": {...}}
    where correlations is {subcategory: score}; it is converted to the server's
    list-of-{category, score} shape. The morality JSON is sent as `safety`.
    """
    url = f"{_resolve_base_url(base_url)}/api/annotation"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    correlations = (annotations or {}).get("correlations") or {}
    payload = {
        "update_id": update_id,
        "user_id": user_id,
        "category": category,
        "annotations": [
            {"category": key, "score": value}
            for key, value in correlations.items()
        ],
    }
    if morality is not None:
        payload["safety"] = morality

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()

    # Only after the server accepted the annotations do we count it in the
    # analysis table (daily frequency for the assigned category).
    await crud.increment_analysis(category, date.today().isoformat())

    log.info(
        "Sent annotations for update_id=%s (category=%s, %d sub-scores).",
        update_id,
        category,
        len(correlations),
    )