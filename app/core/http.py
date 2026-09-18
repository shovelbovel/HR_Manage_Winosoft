"""Shared HTTP helpers so every router serves HTML and JSON from the same
route, per the cahier des charges' "rend des pages HTML pour la navigation et
des réponses JSON pour les appels AJAX, dans un même service" principle.
"""

from __future__ import annotations

import json
from typing import Literal, TypeVar
from urllib.parse import urlencode

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_BAD_REQUEST = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="Missing or invalid request body"
)


def wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


async def read_body(request: Request, model: type[ModelT]) -> ModelT:
    """Read and validate a request body from either a JSON payload (AJAX) or
    an HTML form POST — same route accepts both. Malformed JSON and
    schema/format violations both surface as a 400, never an unhandled 500.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError: a body that isn't valid UTF-8 (a
            # mis-encoded client, not necessarily malicious) must not crash
            # the server with a 500 — same "never trust the wire" principle
            # as the JSON-syntax case above.
            raise _BAD_REQUEST from exc
    else:
        form = await request.form()
        payload = dict(form)

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise _BAD_REQUEST from exc


def flash_redirect(
    url: str, message: str, category: Literal["success", "danger", "warning"] = "success"
) -> RedirectResponse:
    """Redirect (PRG pattern) carrying a one-shot toast message as a query
    string. base.html reads `flash`/`flash_category` on load, shows the
    ephemeral toast, then strips them from the URL via history.replaceState
    so a page refresh never re-shows it.
    """
    separator = "&" if "?" in url else "?"
    query = urlencode({"flash": message, "flash_category": category})
    return RedirectResponse(url=f"{url}{separator}{query}", status_code=status.HTTP_303_SEE_OTHER)
