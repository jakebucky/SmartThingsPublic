from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("RFP_CONFIG_DIR", PROJECT_DIR / "config"))
DB_PATH = Path(os.environ.get("RFP_DB_PATH", PROJECT_DIR / "data" / "rfps.db"))


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_sources(path: Path | None = None) -> list[dict]:
    data = load_yaml(path or CONFIG_DIR / "sources.yaml")
    sources = data.get("sources") or []
    for s in sources:
        if "name" not in s or "type" not in s:
            raise ValueError(f"Source is missing 'name' or 'type': {s}")
        s.setdefault("enabled", True)
        s.setdefault("agency", s["name"])
    return sources


def load_keywords(path: Path | None = None) -> dict:
    return load_yaml(path or CONFIG_DIR / "keywords.yaml")
