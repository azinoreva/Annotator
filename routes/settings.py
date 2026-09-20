from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
import json
import os

router = APIRouter()

# Path to the config file (the project root, i.e. the same config.json that
# main.py reads on startup).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Used when no base_url is provided and none exists on disk yet.
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


# Request body schema — everything that lives in config.json is settable here.
class InitialSettings(BaseModel):
    annotator_id: Optional[str] = None
    annotator_password: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    port: Optional[int] = None


@router.post("/save_initial_settings")
async def save_initial_settings(settings: InitialSettings):
    """
    Saves (any of) model_name, annotator_id, annotator_password and base_url
    to config.json. Existing values are preserved; only the fields you send
    are updated. base_url is defaulted the first time if not provided.
    """
    # Start from whatever is already on disk so partial updates don't clobber.
    config_data: dict = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                config_data = json.load(f)
        except Exception:
            config_data = {}

    updates = settings.model_dump(exclude_none=True)
    if "base_url" not in config_data and "base_url" not in updates:
        updates["base_url"] = DEFAULT_BASE_URL

    config_data.update(updates)

    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=4)

    # Apply the new settings to the running process immediately so the
    # worker picks them up without a restart.
    if "annotator_id" in updates or "annotator_password" in updates:
        from routes.login import configure as configure_login

        configure_login(
            annotator_id=config_data.get("annotator_id"),
            annotator_password=config_data.get("annotator_password"),
        )
    if "base_url" in updates:
        from routes import call_server

        call_server.set_base_url(config_data["base_url"])
    if "model_name" in updates:
        from routes.model import set_active_model

        set_active_model(config_data["model_name"])

    return {
        "status": "success",
        "message": "Initial settings saved successfully.",
        "config_path": CONFIG_PATH,
        "saved": list(updates.keys()),
    }