"""Small JSON surface. Credentials live behind the participant cookie and never in page source."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import runtime, store
from ..config import settings
from ..tracker import SELF_STEPS
from .public import current_participant

router = APIRouter(prefix="/api")


def integration_snippet(base_url, model, key):
    """The Galileo custom-LLM integration body, filled in. Built here rather than in the guide so
    the key reaches the browser only after the cookie has been checked."""
    return json.dumps({
        "authentication_type": "api_key",
        "endpoint": base_url,
        "default_model": model,
        "model_properties": [{
            "name": model,
            "alias": model,
            "based_on": None,
            "supported_parameters": ["max_tokens", "stop_sequences", "temperature",
                                     "tool_choice", "tools"],
            "supports_json_schema": False,
        }],
        "token": None,
        "api_key_header": "Authorization",
        "api_key_value": f"Bearer {key}",
        "authentication_scope": None,
        "oauth2_token_url": None,
        "headers": None,
        "custom_llm_config": None,
        "custom_header_mapping": None,
        "multi_modal_config": None,
    }, indent=2)


@router.get("/counts")
def counts():
    data = store.counts()
    return {
        "registered": data["participants"],
        "instances_free": data["boxes_free"],
        "instances_total": data["boxes_total"],
        "closed": data["participants"] >= settings.account_cap,
    }


@router.get("/status")
def status(request: Request):
    participant = current_participant(request)
    if not participant:
        return JSONResponse({"error": "not registered"}, status_code=401)
    ahead = store.queue_position(participant["id"])
    return {
        "name": participant["name"],
        "email": participant["email"],
        "box_url": store.clean_url(participant["box_url"]),
        "galileo_state": participant["galileo_state"],
        "galileo_email": participant["galileo_email"],
        "waiting_for_instance": participant["box_id"] is None,
        "queue_ahead": ahead,
        # Four seconds per account is what the four Galileo calls plus their pacing cost.
        "queue_seconds": ahead * 4,
    }


@router.get("/credentials")
def credentials(request: Request):
    participant = current_participant(request)
    if not participant:
        return JSONResponse({"error": "not registered"}, status_code=401)
    galileo_ready = participant["galileo_state"] in ("ready", "pool")
    ahead = 0 if galileo_ready else store.queue_position(participant["id"])
    return {
        "instance": {
            "url": store.clean_url(participant["box_url"]),
            "account": settings.bank_account,
            "password": settings.bank_password,
            "presenter_password": settings.presenter_password,
        },
        "galileo": {
            "ready": galileo_ready,
            "state": participant["galileo_state"],
            "queue_ahead": ahead,
            "queue_seconds": ahead * 4,
            "email": participant["galileo_email"] if galileo_ready else "",
            "password": (participant["galileo_password"] or runtime.get("galileo_password"))
                        if galileo_ready else "",
            "console_url": settings.galileo_console_url,
            "api_url": settings.galileo_api_url,
            "agent_control_url": settings.galileo_agent_control_url,
        },
        "llm": {
            "base_url": runtime.get("llm_base_url"),
            "model": runtime.get("llm_model"),
            "api_key": runtime.get("llm_api_key"),
            "integration_json": integration_snippet(
                runtime.get("llm_base_url"), runtime.get("llm_model"), runtime.get("llm_api_key")),
        },
    }


class Tick(BaseModel):
    step: int
    done: bool = True


@router.post("/progress")
def tick(request: Request, body: Tick):
    """A participant marking a step the tracker cannot see on their instance."""
    participant = current_participant(request)
    if not participant:
        return JSONResponse({"error": "not registered"}, status_code=401)
    if body.step not in SELF_STEPS:
        return JSONResponse({"error": "that step is tracked automatically"}, status_code=400)
    if body.done:
        store.mark_step(participant["id"], body.step, "self")
    else:
        store.unmark_step(participant["id"], body.step, "self")
    return {"step": body.step, "done": body.done}
