"""Thin wrapper around the AI provider SDK — mechanical, no business logic
(which prompt/data goes in is a services/ concern, app.services.ai_service),
same layering as app.core.crypto / app.core.pdf.

Server-only: nothing here is reachable from a template or JSON response,
so the API key structurally never reaches the client, per the cahier des
charges' "appel serveur uniquement."
"""

from __future__ import annotations

import anthropic

_TIMEOUT_SECONDS = 60.0  # CV extraction isn't held to the 500ms budget


class AIServiceUnavailableError(Exception):
    """Raised for any provider-side failure (missing key, timeout,
    connection error, API error) — the router turns this into the cahier
    des charges' required fallback message, never a raw technical error.
    """


class AIClient:
    def __init__(self, api_key: str | None, model: str):
        self._api_key = api_key
        self._model = model

    def complete(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        if not self._api_key:
            raise AIServiceUnavailableError("No ANTHROPIC_API_KEY configured")

        client = anthropic.Anthropic(api_key=self._api_key, timeout=_TIMEOUT_SECONDS)
        try:
            message = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AnthropicError as exc:
            raise AIServiceUnavailableError(str(exc)) from exc

        text_blocks = [block.text for block in message.content if block.type == "text"]
        return "".join(text_blocks)
