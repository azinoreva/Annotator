# NULL Annotator

An automated content annotation service for the NULL platform. The annotator
runs as a FastAPI background service, continuously consuming user-generated
updates from the aggregator server, classifying and safety-scoring them with a
local AI model (Ollama), persisting everything to SQLite, and delivering the
finished annotations back to the server.

---

## How it works

The service never blocks on external requests. On startup it performs a set of
sanity checks, then runs two long-lived background tasks.

### Startup sequence

1. Load `config.json` (model name, credentials, server URL) into in-memory state.
2. Verify Ollama is installed, its server is reachable, and the configured model
   is pulled locally (pulls it if missing).
3. Open the SQLite database through Tortoise ORM and create tables as needed.
4. Configure the active AI model and the aggregator credentials/base URL.
5. Warm up the annotator login (non-fatal — the worker retries on failure).
6. Start the stream consumer and the annotation processor.

### Background loops

**`stream_loop`** — subscribes to the aggregator's SSE feed
(`GET /api/updates/subscribe`) and banks every received update into
`received_annotations` (idempotently, by `update_id`). Each arrival wakes the
processor.

**`process_loop`** — waits ~2 seconds (batching), then pulls everything still
pending from the database and processes each update:

1. **Categorisation** — the AI assigns one main classification and correlation
   scores (0.0–1.0) for every subcategory.
2. **Morality / content-safety check** — the AI annotates the post against the
   content-safety taxonomy (flags, intensity/severity, stance).
3. **Persistence** — results are written to `processed_annotations` (internal
   record) and `sent_annotations` (the outgoing record), including the morality
   JSON.
4. **Send** — the finished annotations are delivered to the server
   (`POST /api/annotation`) only after the morality check and the database
   writes succeed.
5. **Ack** — the update is acknowledged (`POST /api/updates/ack`) so the server
   removes it from the annotator stream.
6. The intake row is deleted from `received_annotations`.

Failures are non-fatal: the intake row is left in place and retried on the next
sweep, and the processor re-runs a full sweep at startup, so updates stranded
by a crash are recovered.

### Annotation payload

The payload the service sends back to the server follows this shape:

```json
{
  "update_id": "UPDATE_ID",
  "user_id": "USER_ID",
  "category": "news",
  "annotations": [
    { "category": "politics", "score": 0.92 }
  ],
  "safety": {
    "schema_version": "1.0",
    "flags": [
      {
        "name": "violence",
        "intensity_percent": 10,
        "severity_percent": 5,
        "subcategories": []
      }
    ],
    "context": { "stance": "educational" }
  }
}
```

---

## Configuration

All configuration lives in `config.json` (auto-created at the project root) and
is managed through the settings endpoint:

| Field                 | Description                                      |
| --------------------- | ------------------------------------------------ |
| `model_name`          | Ollama model to use for annotation (default `llama3.2:3b`) |
| `annotator_id`        | Annotator identity registered with the server    |
| `annotator_password`  | Annotator password                               |
| `base_url`            | Aggregator server base URL (default `http://127.0.0.1:8000`) |

```bash
curl -X POST http://127.0.0.1:25340/save_initial_settings \
  -H "Content-Type: application/json" \
  -d '{"annotator_id":"annotator_1","annotator_password":"secret",\
       "base_url":"http://127.0.0.1:8000"}'
```

Partial updates are supported — only the fields you send are written; existing
values are preserved. Credentials can also be supplied via the
`ANOTATOR_ID`, `ANOTATOR_PASSWORD`, and `Aggregator_base_url` environment
variables as a fallback.

---

## Installation

Requires **Python 3.10+**, a running **Ollama** runtime, and the aggregator
(Null-KIB) backend with Redis.

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (POSIX: source venv/bin/activate)
pip install -r requirements.txt
```

> `aiosqlite` is pinned to `0.20.0` — newer releases are incompatible with
> the pinned `tortoise-orm`.

## Running

```bash
python main.py
```

The service listens on `http://127.0.0.1:25340`. Run it as a background
service via your process manager of choice (systemd, NSSM, supervisord, etc.).

For development, the same app can be launched with reload:

```bash
uvicorn main:app --reload
```

---

## Endpoints

| Method | Path                      | Purpose                                   |
| ------ | ------------------------- | ----------------------------------------- |
| `POST` | `/save_initial_settings`  | Write annotator credentials / server URL / port |
| `GET`  | `/state`                  | Inspect runtime state (model, id, server) |
| `GET`  | `/health`                 | Liveness check (used by the dashboard)    |
| `GET`  | `/stats`                  | Counts + processing rate (dashboard LCDs) |
| `GET`  | `/events`                 | SSE push of `{"stats": {...}}` every 3 s  |

The desktop dashboard (`../Annotator_visual/main.py`, PySide6) launches
`annotator.exe` on the configured port, then reads `/health`, `/stats` and
`/events` to populate its live counters, and drives the settings through
`/save_initial_settings`.

An optional admin API (`app.py`, `uvicorn app:app`) exposes REST read/write
operations over the same database for inspection and tooling.

---

## Database

SQLite via Tortoise ORM (`annotator.sqlite`), created automatically on startup.

| Table                 | Purpose                                            |
| --------------------- | -------------------------------------------------- |
| `received_annotations` | Updates pulled from the stream (intake)            |
| `processed_annotations` | Updates after AI categorisation + morality check  |
| `sent_annotations`     | Outgoing records ready to be delivered             |
| `unsent_annotations`   | Reserved for failed/undelivered records            |
| `analysis`             | Per-category daily aggregation (category + frequency) |

Both `processed_annotations` and `sent_annotations` carry a `morality` JSON
column for the content-safety annotation; `sent_annotations` also tracks
delivery time.

---

## Project structure

```
Annotator/
├── main.py            # Service entrypoint, startup checks, task lifecycle
├── app.py             # Optional admin REST API over the database
├── worker.py          # SSE consumer + annotation processor loops
├── db.py              # Tortoise connection setup
├── crud.py            # Database read/write operations
├── schemas.py         # Pydantic request/response models
├── models/            # Tortoise ORM models + classification/morality taxonomies
└── routes/
    ├── call_server.py # Server client: SSE, ack, send annotations
    ├── login.py       # Annotator auth / token manager
    ├── ai_access.py   # Ollama chat wrapper
    ├── model.py       # Active-model adapter for the engines
    ├── annotator.py   # Classification/correlation engine
    ├── morality.py    # Content-safety annotation engine
    └── settings.py    # /save_initial_settings route
```

---

## Server integration

The annotator talks to the aggregator server using a long-lived annotator
access token:

- `POST /api/annotator_login` — obtain tokens
- `POST /api/annotator_refresh` — refresh tokens
- `GET  /api/updates/subscribe` — SSE stream of unprocessed updates
- `POST /api/updates/ack` — remove a processed update from the stream
- `POST /api/annotation` — deliver finished annotations