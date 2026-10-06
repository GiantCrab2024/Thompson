"""Read MODES exports into flat records for the flagging gates.

A record is a list of (path, text) pairs, one per element that holds text,
e.g. ("Object/Production/Person/PersonName", "Oliver Hill").

MODES exports differ between installations, so the tag names the gates look
for live in ELEMENT_RULES below. Check them against the real Bexhill export
before the experiment runs.
"""

import csv
import fnmatch
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Record:
    number: str
    fields: list = field(default_factory=list)  # [(path, text), ...]

    def as_prompt_text(self) -> str:
        """Record fields as numbered-free 'path: text' lines for model prompts."""
        return "\n".join("%s: %s" % (p, t) for p, t in self.fields)

    def has_path(self, path: str) -> bool:
        return any(p.lower() == path.lower() for p, _ in self.fields)


# Gate 2 elements -> fnmatch patterns over record paths (case-insensitive).
# '*' also matches '/', so "*Production*Date*" covers Production/Date/DateBegin.
ELEMENT_RULES = {
    "description": [
        "*/BriefDescription", "*/Identification/Description", "*/PhysicalDescription",
        "*/Description/Summary", "*/Description",
    ],
    "date": [
        "*Production*Date*", "*Production*Period*", "*/DateMade*", "*/Period",
    ],
    "maker": [
        "*Production*Person*", "*Production*Organisation*", "*/Maker*", "*/Creator*",
        "*/Artist*", "*/Author*", "*/Photographer*", "*/Manufacturer*", "*/Architect*",
    ],
    "materials": [
        "*/Material*", "*/Medium*", "*/Format*", "*/Technique*",
    ],
    "acquisition": [
        "*Acquisition*", "*/Provenance*", "*/History*",
    ],
}

# Paths that never count as content for an element, even when a rule matches.
# A Role of "maker" says nothing about who the maker was.
ELEMENT_EXCLUDE = {
    "maker": ["*/Role", "*/Type"],
}

# Paths the spec's extra Stage 1 check looks for (informational only).
MARKS_RULES = ["*Inscription*", "*/Marks*", "*/Mark", "*Condition*"]

IDENTIFIER_RULES = ["*ObjectIdentity/Number", "*/ObjectNumber", "*/Number", "*/Identifier"]


def match_rules(path: str, rules: list) -> bool:
    lowered = path.lower()
    return any(fnmatch.fnmatchcase(lowered, r.lower()) for r in rules)


def texts_for(record: Record, rules: list, exclude: list = ()) -> list:
    return [t for p, t in record.fields if match_rules(p, rules) and not match_rules(p, list(exclude))]


def _flatten(elem, prefix, out):
    path = "%s/%s" % (prefix, elem.tag) if prefix else elem.tag
    text = " ".join((elem.text or "").split())
    if text:
        out.append((path, text))
    for child in elem:
        _flatten(child, path, out)


def _record_number(fields) -> str:
    for rule in IDENTIFIER_RULES:
        for p, t in fields:
            if match_rules(p, [rule]):
                return t
    return ""


def parse_modes_xml(text: str, tag_name: str = "Object") -> list:
    """Parse a MODES XML export; every <Object> element becomes one Record."""
    root = ET.fromstring(text)
    objects = [root] if root.tag == tag_name else list(root.iter(tag_name))
    records = []
    for obj in objects:
        fields = []
        _flatten(obj, "", fields)
        records.append(Record(number=_record_number(fields), fields=fields))
    return records


def parse_modes_csv(path: str, number_column: str = "ObjectNumber") -> list:
    """Parse a CSV export: each column header is treated as a field path."""
    records = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fields = [("Object/" + k, " ".join(v.split())) for k, v in row.items() if k and v and v.strip()]
            records.append(Record(number=(row.get(number_column) or "").strip(), fields=fields))
    return records


def load_export(path: str) -> list:
    if path.lower().endswith(".csv"):
        return parse_modes_csv(path)
    with open(path, encoding="utf-8") as f:
        return parse_modes_xml(f.read())
