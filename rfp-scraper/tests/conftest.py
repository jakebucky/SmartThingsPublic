import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"

from rfp_scraper import config  # noqa: E402


@pytest.fixture
def keywords():
    return config.load_keywords(ROOT / "config" / "keywords.yaml")


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text()


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIXTURES / name).read_text())
