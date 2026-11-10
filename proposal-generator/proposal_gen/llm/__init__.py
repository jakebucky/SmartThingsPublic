"""Pluggable AI model layer.

Every AI step calls `model.generate_json(...)` with a task name, prompts, a
strict JSON schema and (optionally) the RFP PDF or an image. Pick the provider
with the PROPOSAL_MODEL environment variable:

  demo          rule-based stand-in, no AI and no key (default; for trying the app)
  claude        Anthropic Claude (ANTHROPIC_API_KEY or an `ant auth login` profile)
  azure_openai  Azure OpenAI deployment (AZURE_OPENAI_ENDPOINT / _API_KEY / _DEPLOYMENT)
"""
from __future__ import annotations

import os

from .base import Model, ModelError


def get_model(name: str | None = None) -> Model:
    name = (name or os.environ.get("PROPOSAL_MODEL", "demo")).lower()
    if name == "demo":
        from .demo import DemoModel
        return DemoModel()
    if name == "claude":
        from .claude import ClaudeModel
        return ClaudeModel()
    if name in ("azure", "azure_openai"):
        from .azure_openai import AzureOpenAIModel
        return AzureOpenAIModel()
    raise ValueError(f"Unknown PROPOSAL_MODEL {name!r}: use demo, claude or azure_openai")


__all__ = ["Model", "ModelError", "get_model"]
