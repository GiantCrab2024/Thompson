"""Gate 2 (Sufficiency): Detail Score 0-3, scored before generation.

The score follows the planner's paper fallback (Appendix A, Gate 2), so the
module and Sheet B2 filled by hand always give the same number. Count how many
of five elements hold real content:

  (1) brief description of 15 words or more
  (2) date or period
  (3) maker, person or organisation
  (4) materials or format
  (5) acquisition or provenance note

0-1 elements = 0, 2 = 1, 3-4 = 2, 5 = 3.

The spec's extra Stage 1 checks (generic object-type label; no marks,
inscriptions or condition notes) are reported as notes and do not change the
score. No model calls are made here.
"""

import re
from dataclasses import dataclass, field

from .modes import ELEMENT_EXCLUDE, ELEMENT_RULES, MARKS_RULES, Record, match_rules, texts_for

STUB_TEXT = "Insufficient source material"
CAVEAT_TEXT = ("Caveat: this record holds limited source detail (Detail Score 2). "
               "Check every claim against the record before approval.")

MIN_DESCRIPTION_WORDS = 15
GENERIC_LABEL_MAX_WORDS = 4

# Values that count as absent. Compared after lower-casing and stripping
# surrounding punctuation and whitespace. The planner names "?" and "unknown";
# the rest are common MODES variants. Copy this list onto the paper fallback
# sheet so both routes score the same way.
PLACEHOLDERS = {
    "", "?", "??", "???", "unknown", "not known", "unk", "n/a", "na", "none",
    "nil", "-", "--", "tbc", "to be confirmed", "unrecorded", "not recorded",
    "no provenance", "provenance unknown", "unprovenanced",
    "n\\a", "not given", "none given", "undated", "not dated", "not checked",
}

# Bexhill's coin records mark an unknown designer by the coin side and a
# question mark: "R?" (reverse), "Ob?" (obverse), "Ob/R?".
SIDE_UNKNOWN = re.compile(r"(ob|obv|r|rev)(/(ob|obv|r|rev))?\s*\?+")

ELEMENT_ORDER = ["description", "date", "maker", "materials", "acquisition"]


def is_placeholder(text: str) -> bool:
    core = text.strip().lower().strip(" .,;:()[]\"'")
    if core in PLACEHOLDERS or SIDE_UNKNOWN.fullmatch(core):
        return True
    # Text made only of question marks, dashes and spaces.
    return re.fullmatch(r"[?\-\s]*", core) is not None


def real_texts(record: Record, element: str) -> list:
    rules, skip = ELEMENT_RULES[element], {t.lower() for t in ELEMENT_EXCLUDE.get(element, ())}
    texts = []
    for p, t in record.fields:
        if not match_rules(p, rules) or p.rsplit("/", 1)[-1].lower() in skip or is_placeholder(t):
            continue
        # A date Note counts only if it holds a date ("c1960"), not a
        # qualifier on its own ("circa", "undated").
        if element == "date" and p.lower().endswith("/note") and not re.search(r"\d", t):
            continue
        texts.append(t)
    return texts


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


@dataclass
class Gate2Result:
    record_number: str
    elements: dict            # element name -> bool
    element_count: int
    detail_score: int
    decision: str             # "Stop" or "Go" (Sheet B2 codes)
    caveat: str               # caveat shown to the reviewer, or ""
    notes: list = field(default_factory=list)

    @property
    def stub(self) -> str:
        return STUB_TEXT if self.decision == "Stop" else ""


def score_from_count(count: int) -> int:
    if count <= 1:
        return 0
    if count == 2:
        return 1
    if count <= 4:
        return 2
    return 3


def score_record(record: Record) -> Gate2Result:
    descriptions = real_texts(record, "description")
    longest = max(descriptions, key=word_count, default="")
    elements = {
        "description": word_count(longest) >= MIN_DESCRIPTION_WORDS,
        "date": bool(real_texts(record, "date")),
        "maker": bool(real_texts(record, "maker")),
        "materials": bool(real_texts(record, "materials")),
        "acquisition": bool(real_texts(record, "acquisition")),
    }
    count = sum(elements.values())
    score = score_from_count(count)

    notes = []
    missing = [e for e in ELEMENT_ORDER if not elements[e]]
    if missing:
        notes.append("missing: " + ", ".join(missing))
    if longest and word_count(longest) <= GENERIC_LABEL_MAX_WORDS:
        notes.append("description is a bare label: %r" % longest)
    if not [t for t in texts_for(record, MARKS_RULES) if not is_placeholder(t)]:
        notes.append("no marks, inscriptions or condition notes")
    if record.withheld:
        notes.append("withheld: " + ", ".join(record.withheld))

    return Gate2Result(
        record_number=record.number,
        elements=elements,
        element_count=count,
        detail_score=score,
        decision="Stop" if score <= 1 else "Go",
        caveat=CAVEAT_TEXT if score == 2 else "",
        notes=notes,
    )


def should_generate(result: Gate2Result, run: str) -> bool:
    """Run A records the score and stops nothing; Run B stops scores 0-1."""
    if run.upper() == "A":
        return True
    return result.decision == "Go"
