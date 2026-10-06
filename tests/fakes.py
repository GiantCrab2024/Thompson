"""A scripted stand-in for a model client, so tests make no network calls."""

import json
import re

from flagging.gate3 import CLASSIFICATION_SYSTEM, EXTRACTION_SYSTEM


class FakeClient:
    """Extraction splits the generated text into sentences. Classification
    looks each claim up in `labels` (claim text -> label or [label per call])
    and defaults to GROUNDED on the record's BriefDescription.

    Every call is kept in self.log as (system, user) for context checks."""

    def __init__(self, labels=None, names=(), raw_replies=None):
        self.labels = labels or {}
        self.names = names
        self.raw_replies = list(raw_replies or [])
        self.log = []
        self.calls = 0
        self._seen = {}

    def complete(self, system, user):
        self.calls += 1
        self.log.append((system, user))
        if self.raw_replies:
            return self.raw_replies.pop(0)
        if system == EXTRACTION_SYSTEM:
            text = user.split("GENERATED TEXT\n", 1)[1].split("\n\nRules:", 1)[0]
            sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
            claims = [{"n": i, "claim": s,
                       "has_name": any(n in s for n in self.names),
                       "has_exact_date": bool(re.search(r"\b1[89]\d\d\b", s))}
                      for i, s in enumerate(sentences, start=1)]
            return "```json\n%s\n```" % json.dumps({"claims": claims})
        if system == CLASSIFICATION_SYSTEM:
            block = user.split("CLAIMS\n", 1)[1].split("\n\nLabels:", 1)[0]
            out = []
            for line in block.splitlines():
                n, claim = line.split(". ", 1)
                label = self.labels.get(claim, "GROUNDED")
                if isinstance(label, list):
                    k = self._seen.get(claim, 0)
                    self._seen[claim] = k + 1
                    label = label[k % len(label)]
                basis = "" if label == "UNGROUNDED" else "Object/Identification/BriefDescription"
                out.append({"n": int(n), "label": label, "basis": basis, "reason": "fake"})
            return json.dumps({"classifications": out})
        raise AssertionError("unexpected system prompt")
