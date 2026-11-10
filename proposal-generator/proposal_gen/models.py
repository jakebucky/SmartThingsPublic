"""Data shapes and the JSON schemas each AI step must return.

Schemas are strict (every property required, no extras) so they work with
structured-output modes; "optional" values are expressed as empty strings or
empty lists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

STATUSES = ("STATED", "INFERRED", "UNCLEAR", "NOT STATED")

# Facts the PM confirms at step 6 (design doc section 2).
FACT_FIELDS: dict[str, str] = {
    "client_name": "Client: full legal entity name of whoever will sign GRAEF's contract",
    "owner_name": "Owner of the facility or project, if different from the client",
    "contact": "Client contact person, title, email and phone",
    "project_name": "Project name",
    "project_location": "Site address or location",
    "project_summary": "One or two sentences on what the project is",
    "services_requested": "Professional services requested of GRAEF (never construction work)",
    "dates": "Proposal due date, schedule and key dates",
    "phasing": "Phases or delivery-method options described",
    "submittal_type": "letter | qualifications | client_forms | unclear",
}
SUBMITTAL_TYPES = ("letter", "qualifications", "client_forms", "unclear")

REQ_TYPES = ("task", "deliverable", "meeting", "schedule", "submittal",
             "qualification", "commercial", "construction")
SCORED_REQ_TYPES = ("task", "deliverable", "meeting")

ARCHETYPES = ("structural_eor_new", "structural_renovation", "steel_detailing_connections",
              "mep_new", "mep_renovation", "civil_site", "multi_discipline_design", "other")
CLIENT_TYPES = ("architect", "contractor_fabricator", "developer_owner_private",
                "public_agency", "other")
CONFIDENCE = ("high", "medium", "low")

SCOPE_SECTIONS = ("basic_services", "assumptions", "client_provided", "additional_services")


# ----------------------------------------------------------------- dataclasses

@dataclass
class Fact:
    value: str = ""
    status: str = "NOT STATED"


@dataclass
class Requirement:
    id: str
    type: str
    text: str
    page: str = ""
    optional: bool = False

    @property
    def scored(self) -> bool:
        return self.type in SCORED_REQ_TYPES or self.optional


@dataclass
class Exemplar:
    id: str
    title: str
    status: str = "Approved"
    letter_family: str = "Standard"
    archetype: str = ""
    client_type: str = ""
    services: str = ""
    why: str = ""
    year: int | None = None
    office: str = ""
    discipline: str = ""
    market: str = ""
    submarket: str = ""
    project_description: str = ""
    basic_services: str = ""
    service_phases: str = ""
    assumptions: str = ""
    additional_services: str = ""
    client_provided: str = ""
    client_name: str = ""  # client name and short forms, ";"-separated (v0.17)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoredExemplar:
    exemplar: Exemplar
    score: float
    thin: bool
    reasons: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- JSON schemas

def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_FACT = _obj({"value": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)}})

FACTS_SCHEMA = _obj({
    **{name: _FACT for name in FACT_FIELDS},
    "missing_items": {"type": "array", "items": {"type": "string"}},
    "flags": {"type": "array", "items": {"type": "string"}},
    "scope_excerpt": {"type": "string"},
})

REQUIREMENTS_SCHEMA = _obj({
    "requirements": {"type": "array", "items": _obj({
        "id": {"type": "string"},
        "type": {"type": "string", "enum": list(REQ_TYPES)},
        "text": {"type": "string"},
        "page": {"type": "string"},
        "optional": {"type": "boolean"},
    })},
    "capped": {"type": "boolean"},
})

CLASSIFIER_SCHEMA = _obj({
    "archetype": {"type": "string", "enum": list(ARCHETYPES)},
    "archetype_alt": {"type": "string", "enum": [*ARCHETYPES, ""]},
    "client_type": {"type": "string", "enum": list(CLIENT_TYPES)},
    "confidence": {"type": "string", "enum": list(CONFIDENCE)},
    "reason": {"type": "string"},
})

_ITEM = _obj({"text": {"type": "string"}, "covers": {"type": "string"}})

DRAFT_SCHEMA = _obj({
    "based_on": {"type": "string"},
    "project_description": {"type": "string"},
    **{s: {"type": "array", "items": _ITEM} for s in SCOPE_SECTIONS},
    "warnings": {"type": "array", "items": {"type": "string"}},
    "not_addressed": {"type": "array", "items": _obj({"id": {"type": "string"}, "reason": {"type": "string"}})},
})

READ_DOCUMENT_SCHEMA = _obj({"text": {"type": "string"}})


def empty_facts() -> dict:
    out = {name: {"value": "", "status": "NOT STATED"} for name in FACT_FIELDS}
    out.update(missing_items=[], flags=[], scope_excerpt="")
    return out
