"""
Connector: wires Tortoise ORM up to annotator.sqlite.

Two ways to use this, depending on context:

1. Inside a FastAPI app -> use `register_tortoise(app)` in app.py (recommended,
   handles startup/shutdown via the app's lifespan automatically).
2. In a plain script (management commands, one-off tooling, tests) -> use the
   `init_db()` / `close_db()` pair directly, as in test_run.py.
"""

from tortoise import Tortoise
from tortoise.contrib.fastapi import RegisterTortoise

# File lives wherever you run the process from; change to an absolute
# path (e.g. "sqlite:////home/user/app/annotator.sqlite") if needed.
DB_URL = "sqlite://annotator.sqlite"

TORTOISE_ORM_CONFIG = {
    "connections": {"default": DB_URL},
    "apps": {
        "models": {
            "models": ["models"],
            "default_connection": "default",
        },
    },
}


def register_tortoise(app, db_url: str = DB_URL, generate_schemas: bool = True) -> RegisterTortoise:
    """
    FastAPI integration: attaches Tortoise ORM startup/shutdown to the app's
    lifespan. Use inside app.py's `lifespan` context manager:

        async with register_tortoise(app):
            yield

    generate_schemas=True is fine for SQLite/dev; turn it off once you're
    managing migrations yourself (e.g. with Aerich).
    """
    return RegisterTortoise(
        app=app,
        db_url=db_url,
        modules={"models": ["models"]},
        generate_schemas=generate_schemas,
    )


async def init_db(db_url: str = DB_URL, generate_schemas: bool = True) -> None:
    """Plain-script use (no FastAPI app around). Opens the connection and
    (optionally) creates tables if they don't exist yet."""
    await Tortoise.init(db_url=db_url, modules={"models": ["models"]})
    if generate_schemas:
        await Tortoise.generate_schemas(safe=True)


async def close_db() -> None:
    """Plain-script use: close all open connections."""
    await Tortoise.close_connections()