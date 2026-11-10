"""Azure OpenAI provider (the model family the Copilot Studio build uses).

Settings: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT
(optional AZURE_OPENAI_DEPLOYMENT_DRAFT for drafting), AZURE_OPENAI_API_VERSION.
PDFs are sent as extracted text; images as data URLs.
"""
from __future__ import annotations

import base64
import json
import os

from .base import DEFAULT_EFFORT, Attachment, ModelError


class AzureOpenAIModel:
    def __init__(self, client=None):
        import openai

        self._openai = openai
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        self.draft_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_DRAFT", self.deployment)
        if not (client or self.deployment):
            raise ModelError("Set AZURE_OPENAI_DEPLOYMENT (and endpoint/key) to use azure_openai")
        self.name = f"azure_openai:{self.deployment}"
        self.client = client or openai.AzureOpenAI(
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )

    def generate_json(self, *, task: str, system: str, user: str, schema: dict,
                      attachment: Attachment | None = None) -> dict:
        content: list[dict] = []
        if attachment is not None:
            if attachment.mime.startswith("image/"):
                url = f"data:{attachment.mime};base64,{base64.b64encode(attachment.data).decode()}"
                content.append({"type": "image_url", "image_url": {"url": url}})
            elif attachment.text:
                user = f"DOCUMENT TEXT ({attachment.filename or 'attachment'}):\n{attachment.text}\n\n{user}"
        content.append({"type": "text", "text": user})
        kwargs = {}
        if os.environ.get("AZURE_OPENAI_REASONING", "1") == "1":
            kwargs["reasoning_effort"] = DEFAULT_EFFORT.get(task, "medium")
        try:
            resp = self.client.chat.completions.create(
                model=self.draft_deployment if task == "draft" else self.deployment,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": task, "schema": schema, "strict": True}},
                **kwargs,
            )
        except self._openai.APIError as exc:
            raise ModelError(f"Azure OpenAI error during {task}: {exc}") from exc
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise ModelError(f"The {task} answer was cut off")
        try:
            return json.loads(choice.message.content or "")
        except json.JSONDecodeError as exc:
            raise ModelError(f"The {task} answer was not valid JSON") from exc
