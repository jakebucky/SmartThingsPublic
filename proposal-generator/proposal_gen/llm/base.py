from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Tasks, matching the design doc's prompts.
TASKS = ("facts", "requirements", "classifier", "draft", "read_document")

# The design runs drafting on a stronger reasoning setting and everything else
# faster (section 3, model note). Providers map this to their own knob.
DEFAULT_EFFORT = {"draft": "high", "facts": "low", "requirements": "low",
                  "classifier": "low", "read_document": "low"}


class ModelError(RuntimeError):
    """The model could not produce a usable answer (refusal, truncation, bad JSON)."""


@dataclass
class Attachment:
    """A file the model should read directly when the provider supports it."""
    data: bytes
    mime: str            # application/pdf, image/png, image/jpeg
    filename: str = ""
    text: str = ""       # extracted text, for providers that can't read the file


class Model(Protocol):
    name: str

    def generate_json(self, *, task: str, system: str, user: str, schema: dict,
                      attachment: Attachment | None = None) -> dict:
        ...
