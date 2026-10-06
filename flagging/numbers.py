"""Clean MODES record numbers into one consistent format.

The Modes guide (1.160 Number, 1.162 ObjectIdentity) says the record number
is the file's unique primary key, written as an institution code then the
number, using only letters, digits and . / - _ : ( ) with no spaces.
Bexhill writes the code as "BEXHM : " throughout, so that house style is
kept.

clean_number() returns the cleaned number, any annotation it moved out of
the number, the changes it made, and whether a curator should check them.
It never changes MODES itself: the report it feeds is a worklist for
correcting the catalogue.
"""

import re
from dataclasses import dataclass, field

PREFIX = re.compile(r"^\s*([A-Z]{4,5})\s*:\s*(.*)$")


@dataclass
class CleanNumber:
    raw: str
    clean: str
    note: str = ""                                # annotation moved out, e.g. "BexGuide"
    changes: list = field(default_factory=list)   # what was changed, in words
    review: list = field(default_factory=list)    # why a curator should check it

    @property
    def changed(self) -> bool:
        return self.clean != self.raw


def clean_number(raw: str) -> CleanNumber:
    result = CleanNumber(raw=raw, clean=raw)
    m = PREFIX.match(raw or "")
    if not m:
        result.clean = " ".join((raw or "").split())
        result.review.append("no institution code")
        return result
    code, rest = m.group(1), m.group(2)

    # Bracketed annotations are notes about the record, not part of its number.
    notes = re.findall(r"\[([^\]]*)\]", rest)
    if notes:
        rest = re.sub(r"\s*\[[^\]]*\]", "", rest)
        result.note = "; ".join(n.strip() for n in notes)
        result.changes.append("moved [%s] out of the number" % result.note)
        if any("duplicate" in n.lower() for n in notes):
            result.review.append("marked as a duplicate")

    stripped = rest.strip().rstrip(".")
    if stripped != rest:
        result.changes.append("removed trailing space or full stop")
    rest = stripped

    # "2019,10.3": a comma straight after a four-digit year is a typing slip.
    fixed = re.sub(r"^(\d{4}),(\d)", r"\1.\2", rest)
    if fixed != rest:
        result.changes.append("comma after year changed to full stop")
        result.review.append("check comma was a typing slip")
        rest = fixed

    # "1987.36.l6": a lower-case l among digits. Not changed automatically:
    # in the DLWP export the "corrected" number belongs to another object.
    if re.search(r"(?<=[.\d])l(?=\d)", rest):
        result.review.append("lower-case l among digits; correct number unknown")

    # "LP 277": spaces are not allowed inside a number.
    fixed = re.sub(r"^([A-Z]+)\s+(\d)", r"\1\2", rest)
    if fixed != rest:
        result.changes.append("space removed after letter code")
        rest = fixed

    # "1992.280.12=49": "=" is not an allowed character; "-" marks a range.
    if "=" in rest:
        rest = rest.replace("=", "-")
        result.changes.append("'=' range changed to '-'")
        for start, end in re.findall(r"(\d+)-(\d+)", rest):
            if len(end) < len(start) or int(end) <= int(start):
                result.review.append("range end looks shortened (%s-%s)" % (start, end))

    if re.search(r"[,\s]", rest) or re.search(r"\d[a-z]-[a-z]$", rest):
        result.review.append("several items in one number")

    if not re.fullmatch(r"[A-Za-z0-9./\-_:()]+", rest):
        result.review.append("characters outside the Modes set")

    result.clean = "%s : %s" % (code, rest)
    return result
