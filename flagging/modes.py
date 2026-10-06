"""Read MODES exports into flat records for the flagging gates.

A record is a list of (path, text) pairs, one per element that holds text,
e.g. ("Object/Production/Person/PersonName", "Oliver Hill").

Tag names follow the MODES Object schema v6.5 (object65.xsd) and the guide
"Object elements in Modes" (7th edition, Modes Complete 1.6, 2024):

  * <Interchange> holds top-level <Object>s. An <Object> can also sit inside
    <ItemList>; those nested objects are left out of their parent's fields.
  * <key>, <emph>, <q> and <br> are inline markup inside text fields such as
    BriefDescription, so their text is joined into the parent field.
  * Many elements are mixed content (Person, Date, Material, Keyword), so the
    text after a child element also belongs to the parent.
  * Every element may carry a confidentiality attribute. Confidential
    elements, and everything inside them, are withheld from the gates and
    from any model prompt.
  * Every element may carry a currency attribute (added 2022), used to flag
    inaccurate, harmful or offensive content. Anything not marked current
    is withheld the same way.
  * A group's elementtype attribute becomes part of its path, as Modes
    shows it: "Production/Date (creation date)/DateBegin". An Aspect group
    with no elementtype is labelled by its Type, e.g. "Aspect (photo format)".
"""

import csv
import fnmatch
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Record:
    number: str
    fields: list = field(default_factory=list)    # [(path, text), ...]
    withheld: list = field(default_factory=list)  # "path (reason)" for each element left out

    def as_prompt_text(self) -> str:
        """Record fields as 'path: text' lines for model prompts. The
        generation step should send the same text, so Gate 3 checks against
        exactly what the generator saw."""
        return "\n".join("%s: %s" % (p, t) for p, t in self.fields)

    def has_path(self, path: str) -> bool:
        return any(p.lower() == path.lower() for p, _ in self.fields)


INLINE_TAGS = {"key", "emph", "q", "br"}

# confidentiality values that do NOT withhold an element. The schema leaves
# the attribute as free text, so any other non-empty value is treated as
# confidential. Check the values Bexhill's MODES install actually writes.
OPEN_CONFIDENTIALITY = {"", "public", "open", "none", "no", "false", "0", "unrestricted"}

# currency values that do NOT withhold an element. The guide's examples are
# current, previous, obsolete and archaic; only current content is used.
CURRENT_VALUES = {"", "current"}

# Sections never passed to the gates or to a model: storage locations,
# valuations, insurance, audit trails and personal contact details.
SKIP_TAGS = {"Valuation", "Insurance", "Audit", "ObjectLocation", "Location", "Movement",
             "Despatch", "Address", "Phone", "Email", "Price", "Recorder", "RecordProgress",
             "Object"}

# Gate 2 elements -> path patterns (case-insensitive). Each "/"-separated
# segment is an fnmatch pattern, so "Date*" matches "Date (creation date)"
# and "DateBegin". "**" spans any number of segments. A rule matches the
# element it names and everything inside it.
ELEMENT_RULES = {
    "description": [
        "**/Identification*/BriefDescription*",
        "**/Description*/SummaryText*",
    ],
    "date": [
        "**/Production*/Date*", "**/Production*/Period*",
        "**/FieldCollection*/Date*", "**/FieldCollection*/Period*",
    ],
    "maker": [
        "**/Production*/Person*", "**/Production*/Organisation*", "**/Production*/Group*",
        "**/FieldCollection*/Person*",
    ],
    # Form is for natural science specimens; the guide records format and
    # medium as Description/Aspect, e.g. Aspect Type "photo format".
    "materials": [
        "**/Description*/Material*", "**/Description*/Form*",
        "**/Description*/Aspect (*format*)", "**/Description*/Aspect (*medium*)",
        "**/Description*/Aspect (*material*)",
    ],
    # Ownership is "the provenance of the item" (guide 1.178).
    "acquisition": [
        "**/Acquisition*", "**/Ownership*",
    ],
}

# Child elements that qualify a value without being one. A Role of "maker"
# or a Date Type of "production" says nothing about who or when.
QUALIFIER_TAGS = ["Type", "System", "Authority", "References", "Role", "Accuracy",
                  "Part", "Language", "Consent", "Method", "Note"]
ELEMENT_EXCLUDE = {
    "date": QUALIFIER_TAGS,
    "maker": QUALIFIER_TAGS,
    "materials": QUALIFIER_TAGS,
    "acquisition": ["Authority", "References", "System"],
}

# Paths the spec's extra Stage 1 check looks for (informational only).
MARKS_RULES = ["**/Description*/Inscription*", "**/Description*/Condition*", "**/ConditionCheck*"]

IDENTIFIER_RULES = ["Object/ObjectIdentity*/Number", "**/ObjectIdentity*/Number", "**/ObjectNumber"]


def _match_segments(path_segs, rule_segs) -> bool:
    if not rule_segs:
        return not path_segs
    if rule_segs[0] == "**":
        return any(_match_segments(path_segs[i:], rule_segs[1:]) for i in range(len(path_segs) + 1))
    return (bool(path_segs) and fnmatch.fnmatchcase(path_segs[0], rule_segs[0])
            and _match_segments(path_segs[1:], rule_segs[1:]))


def match_rules(path: str, rules: list, descendants: bool = True) -> bool:
    segs = path.lower().split("/")
    for r in rules:
        rule_segs = r.lower().split("/") + (["**"] if descendants else [])
        if _match_segments(segs, rule_segs):
            return True
    return False


def _last(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def texts_for(record: Record, rules: list, exclude_tags: list = ()) -> list:
    skip = {t.lower() for t in exclude_tags}
    return [t for p, t in record.fields if match_rules(p, rules) and _last(p) not in skip]


def _tag(elem) -> str:
    return elem.tag.rsplit("}", 1)[-1]   # drop any XML namespace


def _inline_text(elem) -> str:
    if _tag(elem) == "br":
        return " "
    parts = [elem.text or ""]
    for child in elem:
        parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _withhold_reason(elem) -> str:
    conf = (elem.get("confidentiality") or "").strip().lower()
    if conf not in OPEN_CONFIDENTIALITY:
        return "confidentiality=" + conf
    cur = (elem.get("currency") or "").strip().lower()
    if cur not in CURRENT_VALUES:
        return "currency=" + cur
    return ""


# "material :bronze" -- a short label, a colon, then the value. Bexhill's
# coin records write Aspect this way instead of using a Type child.
LABEL_PREFIX = re.compile(r"\s*([A-Za-z][A-Za-z /-]{0,29}?)\s*:")


def _segment(elem) -> str:
    label = (elem.get("elementtype") or "").strip()
    if not label and _tag(elem) == "Aspect":
        t = next((c for c in elem if _tag(c) == "Type"), None)
        label = " ".join((t.text or "").split()) if t is not None else ""
        if not label:
            m = LABEL_PREFIX.match(elem.text or "")
            label = m.group(1).strip().lower() if m else ""
    return "%s (%s)" % (_tag(elem), label) if label else _tag(elem)


def _flatten(elem, prefix, out, withheld, top=False):
    path = "%s/%s" % (prefix, _segment(elem)) if prefix else _segment(elem)
    reason = _withhold_reason(elem)
    if reason:
        withheld.append("%s (%s)" % (path, reason))
        return
    if not top and _tag(elem) in SKIP_TAGS:
        return
    own = [elem.text or ""]
    blocks = []
    for child in elem:
        if _tag(child) in INLINE_TAGS:
            own.append(_inline_text(child))
        else:
            blocks.append(child)
        own.append(child.tail or "")
    text = " ".join("".join(own).split())
    if text:
        out.append((path, text))
    for child in blocks:
        _flatten(child, path, out, withheld)


def _record_number(fields) -> str:
    for rule in IDENTIFIER_RULES:
        for p, t in fields:
            if match_rules(p, [rule], descendants=False):
                return t
    return ""


def record_from_element(obj) -> Record:
    reason = _withhold_reason(obj)
    if reason:
        # Whole record withheld: keep only its number so it still appears on B2.
        num = obj.find("./{*}ObjectIdentity/{*}Number")
        number = " ".join((num.text or "").split()) if num is not None else ""
        return Record(number=number, fields=[], withheld=["Object (%s)" % reason])
    fields, withheld = [], []
    _flatten(obj, "", fields, withheld, top=True)
    return Record(number=_record_number(fields), fields=fields, withheld=withheld)


def parse_modes_xml(data) -> list:
    """Parse a MODES XML export (bytes or str). Each top-level <Object> is one Record.
    Pass bytes where possible so the file's own encoding declaration is used;
    MODES files are often ISO-8859-1."""
    root = ET.fromstring(data)
    if _tag(root) == "Object":
        objects = [root]
    else:
        objects = [c for c in root if _tag(c) == "Object"]
    return [record_from_element(o) for o in objects]


def parse_modes_csv(path: str, number_column: str = "ObjectIdentity/Number") -> list:
    """Parse a CSV export. Column headers must be element paths below Object,
    e.g. "Identification/BriefDescription"; "." and ">" also work as separators."""
    records = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fields = []
            for k, v in row.items():
                if k and v and v.strip():
                    p = k.strip().replace(">", "/").replace(".", "/")
                    fields.append(("Object/" + p, " ".join(v.split())))
            records.append(Record(number=(row.get(number_column) or "").strip(), fields=fields))
    return records


def load_export(path: str) -> list:
    if path.lower().endswith(".csv"):
        return parse_modes_csv(path)
    with open(path, "rb") as f:
        return parse_modes_xml(f.read())
