"""Draw the experiment's record sample from a MODES export (planner, Action).

The DLWP export holds every record that mentions "De La Warr", so records
are first sorted into groups by the raw text of the whole record:

  pavilion  mentions the Pavilion or "DLWP"
  road      mentions De La Warr Road but not the Pavilion (noise, code N)
  other     mentions De La Warr in some other sense (the Earl, the Parade)
  none      no mention at all

The raw text is used only to sort records here; it is never sent anywhere.

Draw, from a fixed seed so the sample can be reproduced:
  R  random records from the pavilion group
  T  thin records: pavilion records with Detail Score 0-1, not already drawn
  N  noise records from the road group

The planner's fourth awkward kind, S ("best source refused"), depends on
Gate 1 decisions and is chosen by hand after admission.
"""

import random
import re
import xml.etree.ElementTree as ET

from .gate2 import score_record
from .modes import _tag, record_from_element

PAVILION = re.compile(r"pavilion|\bdlwp\b", re.IGNORECASE)
ROAD = re.compile(r"de la warr r(oa)?d", re.IGNORECASE)
DE_LA_WARR = re.compile(r"de la warr", re.IGNORECASE)


def group_of(raw_text: str) -> str:
    if PAVILION.search(raw_text):
        return "pavilion"
    if ROAD.search(raw_text):
        return "road"
    if DE_LA_WARR.search(raw_text):
        return "other"
    return "none"


def grouped_records(path: str) -> list:
    """[(Record, group)] for each top-level Object in a MODES XML export."""
    with open(path, "rb") as f:
        root = ET.fromstring(f.read())
    objects = [root] if _tag(root) == "Object" else [c for c in root if _tag(c) == "Object"]
    return [(record_from_element(o), group_of(" ".join(o.itertext()))) for o in objects]


def draw(grouped: list, seed: int, n_random=30, n_thin=5, n_noise=5) -> list:
    """Return [(Record, code, group)] in a shuffled order for Sheet B2."""
    counts = {}
    for r, _ in grouped:
        counts[r.number] = counts.get(r.number, 0) + 1
    # Records without a number, sharing a number, or wholly withheld can't be used.
    usable = sorted(((r, g) for r, g in grouped if r.number and counts[r.number] == 1 and r.fields),
                    key=lambda rg: rg[0].number)
    rng = random.Random(seed)

    pavilion = [r for r, g in usable if g == "pavilion"]
    picked = rng.sample(pavilion, min(n_random, len(pavilion)))
    chosen = {r.number for r in picked}
    sample = [(r, "R", "pavilion") for r in picked]

    thin_pool = [r for r in pavilion if r.number not in chosen and score_record(r).detail_score <= 1]
    sample += [(r, "T", "pavilion") for r in rng.sample(thin_pool, min(n_thin, len(thin_pool)))]

    road = [r for r, g in usable if g == "road"]
    sample += [(r, "N", "road") for r in rng.sample(road, min(n_noise, len(road)))]

    rng.shuffle(sample)
    return sample
