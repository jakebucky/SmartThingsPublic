"""Rule-based stand-in for an AI model.

Lets you click through the whole app with no API key. Its output is crude on
purpose and every draft it writes says so; never send a demo draft to a client.
"""
from __future__ import annotations

import json
import re

from ..models import FACT_FIELDS, empty_facts
from .base import Attachment

DEMO_NOTE = "Demo model: this draft was produced by simple rules, not AI. Set PROPOSAL_MODEL to use a real model."

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
CONSTRUCTION = re.compile(r"^(install|supply|furnish|remove|demolish|replace|construct|build|fabricate|erect|procure|rework|repair|mount|hang)\b", re.I)
ACTION = re.compile(r"\b(provide|prepare|design|evaluate|review|inspect|survey|attend|submit|deliver|analy[sz]e|assess|look at|tell us|drawings?|report|plans?|specifications?|meetings?|site visits?)\b", re.I)


def section(user: str, name: str) -> str:
    m = re.search(rf"=== {re.escape(name)} ===\n(.*?)(?=\n=== [A-Z][A-Z /()-]+ ===|\Z)", user, re.S)
    return m.group(1).strip() if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip(" -•\t") for s in SENT_SPLIT.split(text) if len(s.strip()) > 15]


class DemoModel:
    name = "demo"

    def generate_json(self, *, task: str, system: str, user: str, schema: dict,
                      attachment: Attachment | None = None) -> dict:
        return getattr(self, f"_{task}")(user, attachment)

    # ------------------------------------------------------------- facts
    def _facts(self, user: str, attachment: Attachment | None) -> dict:
        current = section(user, "CURRENT FACTS")
        facts = json.loads(current) if current else empty_facts()
        source = section(user, "SOURCE TEXT") or (attachment.text if attachment else "")
        correction = section(user, "PM CORRECTION")

        def put(name, value, status="STATED"):
            if value:
                facts[name] = {"value": value.strip()[:300], "status": status}

        if not current:
            sents = _sentences(source)
            put("project_summary", sents[0] if sents else "", "INFERRED")
            services = [s for s in sents if ACTION.search(s) and not CONSTRUCTION.match(s)]
            put("services_requested", "; ".join(services[:4]), "INFERRED")
            m = re.search(r"\b(\d{2,5} [NSEW]\.? [A-Z][\w.]* (?:Ave|St|Rd|Blvd|Dr|Way)\.?)", source)
            put("project_location", m.group(1) if m else "")
            m = re.search(r"(?im)^(?:thanks|regards|sincerely),?\s*\n?\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*$", source)
            put("contact", m.group(1) if m else "", "INFERRED")
            m = re.search(r"\b([A-Z][\w.&]*(?: [A-Z][\w.&,]*){0,4} (?:Inc|LLC|Co|Company|Corporation|County|City|District)\b\.?)", source)
            if m:
                put("client_name", m.group(1), "UNCLEAR")
            if re.search(r"statement of qualifications|request for qualifications|\bRFQ\b", source, re.I):
                put("submittal_type", "qualifications")
            elif re.search(r"\b(attached|required) (bid|proposal) forms?\b|client'?s? forms", source, re.I):
                put("submittal_type", "client_forms")
            else:
                put("submittal_type", "letter", "INFERRED")
            m = re.search(r"(?i)\b(?:due|deadline)\b[^.\n]{0,40}", source)
            put("dates", m.group(0) if m else "")
            facts["missing_items"] = [FACT_FIELDS[k].split(":")[0] for k in ("client_name", "project_location")
                                      if facts[k]["status"] == "NOT STATED"]
            if attachment is not None:
                facts["scope_excerpt"] = source[:4000]
        if correction:
            for part in correction.split(" | "):
                m = re.match(r"(?i)\s*the (client|owner|contact|project|location) is (.+)", part)
                key = {"client": "client_name", "owner": "owner_name", "contact": "contact",
                       "project": "project_name", "location": "project_location"}.get(m.group(1).lower()) if m else None
                if m and key:
                    put(key, m.group(2).rstrip("."))
                m = re.match(r"\s*(\w+)\s*:\s*(.+)", part)
                if m and m.group(1) in FACT_FIELDS:
                    put(m.group(1), m.group(2))
        return facts

    # ------------------------------------------------------------- requirements
    def _requirements(self, user: str, attachment: Attachment | None) -> dict:
        source = section(user, "SOURCE TEXT") or (attachment.text if attachment else "")
        reqs = []
        for s in _sentences(source):
            low = s.lower()
            if CONSTRUCTION.match(s) or re.search(r"\b(supply and install|remove the existing|rework)\b", low):
                rtype = "construction"
            elif re.search(r"\b(fee|insurance|guarantee|accura|not exceed|liabilit)", low):
                rtype = "commercial"
            elif "meeting" in low:
                rtype = "meeting"
            elif re.search(r"\b(drawings?|report|plans|specifications|documents)\b", low):
                rtype = "deliverable"
            elif re.search(r"\b(next week|due|by [A-Z]?\w+ \d|schedule)\b", low):
                rtype = "schedule"
            elif ACTION.search(s):
                rtype = "task"
            else:
                continue
            reqs.append({"id": f"R{len(reqs) + 1}", "type": rtype, "text": s[:160], "page": "",
                         "optional": bool(re.search(r"\b(optional|alternate)\b", low))})
        return {"requirements": reqs[:40], "capped": len(reqs) > 40}

    # ------------------------------------------------------------- classifier
    def _classifier(self, user: str, attachment: Attachment | None) -> dict:
        text = (section(user, "CONFIRMED FACTS") + " " + section(user, "SOURCE TEXT")).lower()
        structural = re.search(r"\b(joist|beam|steel|structural|framing|column|slab|foundation|louver)", text)
        renovation = re.search(r"\b(existing|repair|damage|replace|renovat|retrofit|upgrade)", text)
        if re.search(r"\b(hvac|mechanical|electrical|plumbing|mep)\b", text):
            arch = "mep_renovation" if renovation else "mep_new"
        elif structural:
            arch = "structural_renovation" if renovation else "structural_eor_new"
        elif re.search(r"\b(site|grading|stormwater|parking lot|utility|paving)\b", text):
            arch = "civil_site"
        else:
            arch = "other"
        if re.search(r"\b(contractor|builders|construction company|cullen|fabricator)\b", text):
            ctype = "contractor_fabricator"
        elif "architect" in text:
            ctype = "architect"
        elif re.search(r"\b(county|city of|village|district|state of|department)\b", text):
            ctype = "public_agency"
        else:
            ctype = "developer_owner_private"
        return {"archetype": arch, "archetype_alt": "", "client_type": ctype,
                "confidence": "medium" if arch != "other" else "low",
                "reason": "Demo model keyword match."}

    # ------------------------------------------------------------- draft
    def _draft(self, user: str, attachment: Attachment | None) -> dict:
        facts = json.loads(section(user, "CONFIRMED FACTS") or "{}")
        reqs = [ln for ln in section(user, "REQUIREMENTS").splitlines() if ln.strip()]
        basic, additional = [], []
        for ln in reqs:
            m = re.match(r"(R\d+) \[(\w+)(, optional)?\] (.*?)(?: \(p\.[^)]*\))?$", ln.strip())
            if not m:
                continue
            rid, rtype, optional, text = m.groups()
            if rtype not in ("task", "deliverable", "meeting") and not optional:
                continue
            item = {"text": text if re.search(r"\d", text) else f"{text} (verify)", "covers": rid}
            (additional if optional else basic).append(item)
        services = facts.get("services_requested", {}).get("value", "") or "the requested engineering services"
        return {
            "based_on": "the request provided",
            "project_description": f"to provide engineering services for {services[:200].rstrip('.')}. Our proposal is based on the request provided.",
            "basic_services": basic or [{"text": "Field verify existing conditions (verify).", "covers": ""}],
            "assumptions": [{"text": "Construction, installation and procurement are by others.", "covers": ""}],
            "client_provided": [{"text": "Access to the site and any existing drawings.", "covers": ""}],
            "additional_services": additional[:6],
            "warnings": [DEMO_NOTE],
            "not_addressed": [],
        }

    # ------------------------------------------------------------- read_document
    def _read_document(self, user: str, attachment: Attachment | None) -> dict:
        if attachment is None:
            return {"text": ""}
        if attachment.text:
            return {"text": attachment.text}
        return {"text": f"[{attachment.filename}: the demo model cannot read images]"}
