from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PROPOSAL_DATA_DIR", PROJECT_DIR / "data"))
DB_PATH = Path(os.environ.get("PROPOSAL_DB_PATH", DATA_DIR / "proposals.db"))
DRAFTS_DIR = DATA_DIR / "drafts"
CONFIG_DIR = PROJECT_DIR / "config"

# Limits from the design doc.
MAX_SUPPORT_ITEMS = 3          # section 2, step 4
SUPPORT_ITEM_CHARS = 8000      # section 2, step 4
MAX_REQUIREMENTS = 40          # section 4
EXEMPLAR_POOL = 100            # section 5
EXEMPLARS_SELECTED = 6         # section 5
CLASSIFIER_SOURCE_CHARS = 4000 # section 2, step 10
MAX_ADDITIONAL_SERVICES = 6    # section 4
THIN_BASIC_SERVICES = 300      # section 5


def load_offices() -> list[dict]:
    with open(CONFIG_DIR / "offices.yaml", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("offices", [])


def office_by_name(name: str) -> dict | None:
    for o in load_offices():
        if o["name"].lower() == (name or "").strip().lower():
            return o
    return None


def offices_for_state(state: str) -> list[dict]:
    return [o for o in load_offices() if o["state"] == state]
