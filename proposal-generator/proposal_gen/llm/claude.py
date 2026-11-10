"""Anthropic Claude provider (official `anthropic` SDK)."""
from __future__ import annotations

import base64
import json
import os

from .base import DEFAULT_EFFORT, Attachment, ModelError

DEFAULT_MODEL = "claude-opus-5-5"


class ClaudeModel:
    def __init__(self, model: str | None = None, client=None):
        import anthropic

        self._anthropic = anthropic
        self.model = model or os.environ.get("PROPOSAL_CLAUDE_MODEL", DEFAULT_MODEL)
        self.name = f"claude:{self.model}"
        # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.
        self.client = client or anthropic.Anthropic()

    def _content(self, user: str, attachment: Attachment | None) -> list[dict]:
        blocks: list[dict] = []
        if attachment is not None:
            data = base64.standard_b64encode(attachment.data).decode("ascii")
            if attachment.mime == "application/pdf":
                blocks.append({"type": "document", "title": attachment.filename or "Request",
                               "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
            elif attachment.mime in ("image/png", "image/jpeg", "image/gif", "image/webp"):
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": attachment.mime, "data": data}})
            elif attachment.text:
                user = f"{attachment.text}\n\n{user}"
        blocks.append({"type": "text", "text": user})
        return blocks

    def generate_json(self, *, task: str, system: str, user: str, schema: dict,
                      attachment: Attachment | None = None) -> dict:
        effort = os.environ.get(f"PROPOSAL_EFFORT_{task.upper()}", DEFAULT_EFFORT.get(task, "medium"))
        try:
            # Streaming: RFP PDFs and drafts can be long. Server-side fallback
            # re-runs a refused request on another model inside the same call.
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=system,
                messages=[{"role": "user", "content": self._content(user, attachment)}],
                output_config={"effort": effort,
                               "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except self._anthropic.RateLimitError as exc:
            raise ModelError(f"Claude rate limit reached during {task}; try again shortly") from exc
        except self._anthropic.APIStatusError as exc:
            raise ModelError(f"Claude API error {exc.status_code} during {task}: {exc.message}") from exc
        except self._anthropic.APIConnectionError as exc:
            raise ModelError(f"Could not reach the Claude API during {task}") from exc

        if message.stop_reason == "refusal":
            raise ModelError(f"The model declined the {task} step")
        if message.stop_reason == "max_tokens":
            raise ModelError(f"The {task} answer was cut off (max_tokens)")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelError(f"The {task} answer was not valid JSON") from exc
