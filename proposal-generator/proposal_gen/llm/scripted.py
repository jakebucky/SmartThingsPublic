"""A model that returns prepared answers; used by the tests."""
from __future__ import annotations

import copy
from typing import Callable

from .base import Attachment, ModelError


class ScriptedModel:
    name = "scripted"

    def __init__(self, answers: dict[str, dict | list | Callable]):
        self.answers = answers
        self.calls: list[dict] = []

    def generate_json(self, *, task: str, system: str, user: str, schema: dict,
                      attachment: Attachment | None = None) -> dict:
        self.calls.append({"task": task, "system": system, "user": user,
                           "attachment": attachment.filename if attachment else None})
        answer = self.answers.get(task)
        if answer is None:
            raise ModelError(f"no scripted answer for {task}")
        if callable(answer):
            return answer(system=system, user=user, attachment=attachment)
        if isinstance(answer, list):  # successive answers
            return copy.deepcopy(answer.pop(0) if len(answer) > 1 else answer[0])
        return copy.deepcopy(answer)
