"""Clean a MODES export before the experiment draws from it.

Two steps, both written to a working copy; the MODES file itself is never
changed, and the report doubles as a worklist for correcting the catalogue.

1. Record numbers are put into one format (numbers.clean_number).
2. Records left sharing a number are resolved. In the DLWP export these
   are one object catalogued twice: a full record in the documents file
   and a short legacy record from another file, told apart only by a
   bracketed note such as [BexGuide]. The record with the most filled
   fields is kept and the others are dropped from the working copy.
"""

import xml.etree.ElementTree as ET

from .modes import _tag, record_from_element
from .numbers import clean_number

REPORT_COLUMNS = ["MODES no. as exported", "Cleaned number", "Action", "Note moved out", "Changes",
                  "Check", "Filled fields", "Collection", "Brief description"]


def _field(record, suffix):
    return next((t for p, t in record.fields if p.endswith(suffix)), "")


def clean_export(in_path: str, out_path: str) -> list:
    """Write a cleaned copy of the export and return report rows for every record."""
    with open(in_path, "rb") as f:
        data = f.read()
    root = ET.fromstring(data)
    objects = [c for c in root if _tag(c) == "Object"]

    entries = []
    for obj in objects:
        record = record_from_element(obj)
        entries.append({"obj": obj, "record": record, "cleaned": clean_number(record.raw_number)})

    groups = {}
    for e in entries:
        groups.setdefault(e["cleaned"].clean, []).append(e)

    rows = []
    for e in entries:
        c, record = e["cleaned"], e["record"]
        group = groups[c.clean]
        action = "number cleaned" if c.changed else "unchanged"
        if len(group) > 1:
            keep = max(group, key=lambda x: len(x["record"].fields))
            if keep is e:
                action = "kept; duplicate record dropped"
            else:
                action = "dropped: duplicate of %r, which has more filled fields" % keep["record"].raw_number
                root.remove(e["obj"])
        if not action.startswith("dropped") and c.changed:
            number = e["obj"].find("./{*}ObjectIdentity/{*}Number")
            if len(number):
                c.review.append("Number has sub-elements; not rewritten")
            else:
                number.text = c.clean
        rows.append({
            "MODES no. as exported": c.raw, "Cleaned number": c.clean, "Action": action,
            "Note moved out": c.note, "Changes": "; ".join(c.changes), "Check": "; ".join(c.review),
            "Filled fields": len(record.fields),
            "Collection": _field(record, "Administration/CollectionName"),
            "Brief description": _field(record, "BriefDescription"),
        })

    declared = b'encoding="iso-8859-1"' in data[:100].lower()
    ET.ElementTree(root).write(out_path, encoding="iso-8859-1" if declared else "utf-8", xml_declaration=True)
    return rows
