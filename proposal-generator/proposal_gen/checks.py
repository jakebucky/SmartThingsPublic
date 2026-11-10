"""Deterministic checks on a draft (design doc sections 6 and 11).

None of them blocks a draft: each becomes a system warning and/or a HANDOFF
count, and the PM decides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import SCOPE_SECTIONS, Requirement

CONSTRUCTION_VERBS = ("install", "supply", "furnish", "remove", "demolish", "replace", "construct", "build",
                      "fabricate", "erect", "procure", "rework", "repair", "mount", "hang")
DESIGN_NOUNS = ("recommendations", "recommendation", "details", "detail", "design", "drawings", "documents",
                "options", "alternatives", "plans", "specifications", "cost", "estimate")
QTY_UNITS = ("days", "day", "weeks", "week", "months", "month", "visits", "visit", "meetings", "meeting",
             "hours", "hour", "copies", "copy", "sets", "set", "rounds", "round")
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20",
                "thirty": "30"}
OPEN_ENDED = ("as required", "as necessary", "as needed", "any and all")
OUTCOME_RE = re.compile(r"accura|guarantee|will not deviate|will not exceed", re.I)
VERIFY = "(verify)"
STOP = {"the", "and", "for", "with", "that", "this", "from", "will", "shall", "are", "any", "all", "not",
        "client", "graef", "project", "provide", "provided", "by", "of", "to", "in", "on", "or", "be", "as",
        "is", "an", "a", "at", "its", "their", "other", "others", "per"}


def items(draft: dict, *sections: str) -> list[dict]:
    out = []
    for s in sections or SCOPE_SECTIONS:
        for it in draft.get(s) or []:
            if isinstance(it, str):
                it = {"text": it, "covers": ""}
            out.append({**it, "section": s})
    return out


def _ids(covers: str) -> set[str]:
    return {c.strip().upper() for c in re.split(r"[,\s;]+", covers or "") if c.strip()}


def _words5(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) >= 5}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in STOP}


# ----------------------------------------------------------------- coverage

@dataclass
class Coverage:
    status: dict[str, str] = field(default_factory=dict)   # id -> covered | declined | missing | not_scored
    declined_reasons: dict[str, str] = field(default_factory=dict)
    weak: list[str] = field(default_factory=list)

    def ids(self, state: str) -> list[str]:
        return [i for i, s in self.status.items() if s == state]


def coverage(requirements: list[Requirement], draft: dict) -> Coverage:
    all_items = items(draft)
    covered_ids: set[str] = set()
    for it in all_items:
        covered_ids |= _ids(it.get("covers", ""))
    declined = {str(n.get("id", "")).upper(): n.get("reason", "") for n in draft.get("not_addressed") or []}
    cov = Coverage()
    for r in requirements:
        rid = r.id.upper()
        if not r.scored:
            cov.status[r.id] = "not_scored"
        elif rid in covered_ids:
            cov.status[r.id] = "covered"
            tagged = [it for it in all_items if rid in _ids(it.get("covers", ""))]
            if not any(_words5(r.text) & _words5(it["text"]) for it in tagged):
                cov.weak.append(r.id)
        elif rid in declined:
            cov.status[r.id] = "declined"
            cov.declined_reasons[r.id] = declined[rid]
        else:
            cov.status[r.id] = "missing"
    return cov


def coverage_warnings(requirements: list[Requirement], cov: Coverage) -> list[str]:
    by_id = {r.id: r for r in requirements}
    out = []
    missing = cov.ids("missing")
    if missing:
        listed = [f"{i} {by_id[i].text}" + (f" (p.{by_id[i].page})" if by_id[i].page else "") for i in missing[:8]]
        more = f"; +{len(missing) - 8} more" if len(missing) > 8 else ""
        out.append("Not addressed in the draft: " + "; ".join(listed) + more)
    declined = cov.ids("declined")
    if declined:
        out.append("Left out on purpose by the draft: " + "; ".join(
            f"{i} {by_id[i].text} ({cov.declined_reasons.get(i) or 'no reason given'})" for i in declined))
    return out


# ----------------------------------------------------------------- rule checks

def construction_verb_hits(draft: dict) -> list[str]:
    hits = []
    for it in items(draft, "basic_services", "additional_services"):
        words = re.findall(r"[A-Za-z]+", it["text"].lower())
        if words and words[0] in CONSTRUCTION_VERBS:
            nxt = words[1] if len(words) > 1 else ""
            if nxt not in DESIGN_NOUNS:
                hits.append(it["text"])
    return hits


def example_name_hits(draft: dict, selected_exemplars, current_names: list[str]) -> list[str]:
    """A selected exemplar's ClientName (or short form) appears in the draft."""
    text = " ".join([draft.get("project_description", "")] + [it["text"] for it in items(draft)]
                    + list(draft.get("warnings") or [])).lower()
    current = " ".join(n.lower() for n in current_names if n)
    hits = []
    for ex in selected_exemplars:
        names = [n.strip() for n in (ex.client_name or "").split(";") if len(n.strip()) >= 3]
        if any(n.lower() in current for n in names):
            continue  # that exemplar was written for this same client
        for n in names:
            if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", text):
                hits.append(n)
                break
    return hits


def _normalized_source_numbers(source: str) -> set[str]:
    low = source.lower()
    nums = set(re.findall(r"(?<![\d.])\d+(?![\d.])", low))
    for word, digit in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            nums.add(digit)
    return nums


def unsupported_quantity_hits(draft: dict, source_text: str) -> list[str]:
    source_nums = _normalized_source_numbers(source_text)
    unit_re = "|".join(QTY_UNITS)
    word_nums = "|".join(NUMBER_WORDS)
    pattern = re.compile(rf"\b(\d+|{word_nums})\s+(?:\w+\s+)?(?:{unit_re})\b", re.I)
    hits = []
    for it in items(draft):
        if VERIFY in it["text"].lower():
            continue
        for m in pattern.finditer(it["text"]):
            n = m.group(1).lower()
            n = NUMBER_WORDS.get(n, n)
            if n not in source_nums:
                hits.append(it["text"])
                break
    return hits


def open_ended_hits(draft: dict) -> list[str]:
    hits = []
    for it in items(draft, "basic_services"):
        low = it["text"].lower()
        if any(p in low for p in OPEN_ENDED) and VERIFY not in low and not re.search(r"\d", low):
            hits.append(it["text"])
    return hits


def outcome_requirements(requirements: list[Requirement]) -> list[Requirement]:
    return [r for r in requirements if OUTCOME_RE.search(r.text)]


def duplicate_pairs(draft: dict, limit: int = 3) -> list[tuple[str, str]]:
    """An assumption sharing >= 2 content words with a client-provided item or
    additional service, those words making up >= half of the shorter item."""
    pairs = []
    for a in items(draft, "assumptions"):
        aw = _content_words(a["text"])
        for b in items(draft, "client_provided", "additional_services"):
            bw = _content_words(b["text"])
            shared = aw & bw
            shorter = min(len(aw), len(bw)) or 1
            if len(shared) >= 2 and len(shared) >= shorter / 2:
                pairs.append((a["text"], b["text"]))
                break
    return pairs[:limit]


def verify_count(draft: dict) -> int:
    return sum(1 for it in items(draft) if VERIFY in it["text"].lower())


# ----------------------------------------------------------------- all together

@dataclass
class CheckResults:
    construction: list[str]
    example_names: list[str]
    unsupported_qty: list[str]
    open_ended: list[str]
    outcome: list[Requirement]
    duplicates: list[tuple[str, str]]
    verify_items: int
    additional_count: int

    def warnings(self) -> list[str]:
        w = []
        if self.construction:
            w.append("Possible construction work listed as a GRAEF service: " + "; ".join(self.construction))
        if self.example_names:
            w.append("Name from an example letter appears in the draft: " + ", ".join(self.example_names))
        if self.unsupported_qty:
            w.append("Quantity or duration not found in the request and not marked (verify): "
                     + "; ".join(self.unsupported_qty))
        if self.additional_count > 6:
            w.append(f"More than 6 additional services ({self.additional_count}).")
        if self.outcome:
            w.append("Accuracy or outcome expectation in the request: "
                     + "; ".join(f"{r.id} {r.text}" for r in self.outcome)
                     + ". Do not accept it as written.")
        if self.open_ended:
            w.append("Open-ended basic services with no limit: " + "; ".join(self.open_ended))
        if self.duplicates:
            w.append("Possible duplicates: " + "; ".join(f'"{a}" / "{b}"' for a, b in self.duplicates))
        return w

    def counts(self) -> dict:
        return {
            "check_construction_verbs": len(self.construction),
            "check_example_names": len(self.example_names),
            "check_unsupported_qty": len(self.unsupported_qty),
            "check_verify_items": self.verify_items,
            "check_additional_count": self.additional_count,
            "check_open_ended": len(self.open_ended),
            "check_outcome_terms": len(self.outcome),
            "check_duplicates": len(self.duplicates),
        }


def run_checks(draft: dict, *, requirements: list[Requirement], source_text: str,
               selected_exemplars, current_names: list[str]) -> CheckResults:
    return CheckResults(
        construction=construction_verb_hits(draft),
        example_names=example_name_hits(draft, selected_exemplars, current_names),
        unsupported_qty=unsupported_quantity_hits(draft, source_text),
        open_ended=open_ended_hits(draft),
        outcome=outcome_requirements(requirements),
        duplicates=duplicate_pairs(draft),
        verify_items=verify_count(draft),
        additional_count=len(draft.get("additional_services") or []),
    )
