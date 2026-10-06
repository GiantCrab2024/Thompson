"""Gate 3 (Grounding): Corpus Reliance Score 0-3, scored after generation.

Two separate model calls, each with its own fresh context:

  Call A (extraction):     record fields + generated text -> atomic claims
  Call B (classification): claims + record fields + admitted source passages
                           -> GROUNDED / INFERRED / UNGROUNDED per claim

Call B never sees the generated prose or the generation prompt.

Scoring (Appendix A, Gate 3): 0 ungrounded claims = 0, 1-2 = 1, 3-4 = 2,
five or more, or any ungrounded claim holding a name or exact date = 3.
"""

import re
from dataclasses import dataclass, field

from .llm import ModelError, parse_json_reply
from .modes import Record

LABELS = ("GROUNDED", "INFERRED", "UNGROUNDED")
LABEL_CODES = {"GROUNDED": "G", "INFERRED": "I", "UNGROUNDED": "U"}


@dataclass
class Passage:
    source_id: str   # admission ID from Sheet B1, e.g. "S03"
    text: str


@dataclass
class Claim:
    n: int
    text: str
    has_name: bool = False
    has_exact_date: bool = False


@dataclass
class ClaimResult:
    claim: Claim
    label: str
    basis: str
    reason: str
    basis_verified: object = None   # True / False, or None for UNGROUNDED

    @property
    def code(self) -> str:
        return LABEL_CODES[self.label]

    @property
    def invented_name_or_date(self) -> bool:
        return self.label == "UNGROUNDED" and (self.claim.has_name or self.claim.has_exact_date)


@dataclass
class Gate3Result:
    output_id: str
    record_number: str
    run: str
    claims: list = field(default_factory=list)   # [ClaimResult]
    cr_score: object = None                      # int, or None on tool fault
    model_calls: int = 0
    error: str = ""

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    @property
    def ungrounded_count(self) -> int:
        return sum(1 for c in self.claims if c.label == "UNGROUNDED")

    @property
    def has_invented_name_or_date(self) -> bool:
        return any(c.invented_name_or_date for c in self.claims)


EXTRACTION_SYSTEM = (
    "You split museum interpretation text into atomic factual claims. "
    "You do not judge whether the claims are true or supported."
)

EXTRACTION_PROMPT = """The museum record below is given only to help you resolve references. Extract claims from the GENERATED TEXT alone, including claims that repeat the record.

RECORD FIELDS
{record}

GENERATED TEXT
{text}

Rules:
- One fact per claim. Split any sentence that joins several facts.
- Keep the text's own wording where you can, but make each claim readable on its own: replace pronouns with what they refer to.
- Keep hedges. "Probably made in the 1930s" stays hedged.
- Leave out framing and style that makes no factual claim, such as "This is an interesting object".
- has_name is true if the claim names a person or an organisation (a maker, architect, firm, owner or donor).
- has_exact_date is true if the claim gives a single year or a calendar date. Decades, centuries, periods, ranges and "circa" dates are false.

Reply with JSON only, in this form:
{{"claims": [{{"n": 1, "claim": "...", "has_name": false, "has_exact_date": false}}]}}"""

CLASSIFICATION_SYSTEM = (
    "You check claims against a museum's own evidence. "
    "You have not seen the text the claims came from, and you must not use general knowledge as evidence."
)

CLASSIFICATION_PROMPT = """Classify each claim against the evidence below and nothing else.

RECORD FIELDS (MODES)
{record}

ADMITTED SOURCE PASSAGES
{passages}

CLAIMS
{claims}

Labels:
- GROUNDED: traceable to a record field or an admitted source passage above.
- INFERRED: a reasonable reading of those fields or passages, worded with caution.
- UNGROUNDED: no traceable basis in the fields or passages above. A claim that is true from general knowledge but absent from the evidence is UNGROUNDED.
If you are unsure between INFERRED and UNGROUNDED, choose UNGROUNDED.

How the record fields are written (Modes conventions):
- Dates are day.month.year with no leading zeros: "5.4.1935" is 5 April 1935, "4.1935" is April 1935.
- A qualifier such as "about", "circa", "before" or "after" is often recorded in a Note field under the date. A claim that states the date without that qualifier is UNGROUNDED.
- Names may be recorded surname first: "Smith, John" is John Smith.
- A label in brackets in a field path, such as "Date (creation date)", says what kind of value the field holds.

For GROUNDED and INFERRED, give the basis: either the field path exactly as written above, or the source ID followed by a short verbatim quote, e.g. S03: "opened in December 1935". For UNGROUNDED, give an empty basis.

Reply with JSON only, one entry per claim, in this form:
{{"classifications": [{{"n": 1, "label": "GROUNDED", "basis": "...", "reason": "one line"}}]}}"""


def format_passages(passages: list) -> str:
    if not passages:
        return "(none retrieved)"
    return "\n".join("[%s] %s" % (p.source_id, " ".join(p.text.split())) for p in passages)


def format_claims(claims: list) -> str:
    return "\n".join("%d. %s" % (c.n, c.text) for c in claims)


def extract_claims(client, record: Record, text: str) -> list:
    """Call A. Returns claims numbered 1..n in the order the model gave them."""
    raw = client.complete(EXTRACTION_SYSTEM,
                          EXTRACTION_PROMPT.format(record=record.as_prompt_text(), text=text.strip()))
    data = parse_json_reply(raw)
    items = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ModelError("extraction reply has no 'claims' list", raw)
    claims = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("claim", "")).strip():
            raise ModelError("extraction item %d has no claim text" % i, raw)
        claims.append(Claim(n=i, text=str(item["claim"]).strip(),
                            has_name=bool(item.get("has_name")),
                            has_exact_date=bool(item.get("has_exact_date"))))
    return claims


def classify_claims(client, record: Record, passages: list, claims: list) -> list:
    """Call B. Sees claims, record fields and passages; never the generated prose."""
    if not claims:
        return []
    raw = client.complete(CLASSIFICATION_SYSTEM,
                          CLASSIFICATION_PROMPT.format(record=record.as_prompt_text(),
                                                       passages=format_passages(passages),
                                                       claims=format_claims(claims)))
    data = parse_json_reply(raw)
    items = data.get("classifications") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ModelError("classification reply has no 'classifications' list", raw)

    by_n = {}
    for item in items:
        try:
            n = int(item["n"])
        except (KeyError, TypeError, ValueError):
            raise ModelError("classification item without a claim number", raw)
        label = str(item.get("label", "")).strip().upper()
        if label not in LABELS:
            raise ModelError("claim %d has unknown label %r" % (n, label), raw)
        if n in by_n:
            raise ModelError("claim %d classified twice" % n, raw)
        by_n[n] = (label, str(item.get("basis") or "").strip(), str(item.get("reason") or "").strip())

    missing = [c.n for c in claims if c.n not in by_n]
    if missing:
        raise ModelError("claims not classified: %s" % missing, raw)

    results = []
    for c in claims:
        label, basis, reason = by_n[c.n]
        if label == "UNGROUNDED":
            basis = ""
        verified = None if label == "UNGROUNDED" else verify_basis(basis, record, passages)
        results.append(ClaimResult(claim=c, label=label, basis=basis, reason=reason, basis_verified=verified))
    return results


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[“”\"'‘’]", "", s).lower().split())


def verify_basis(basis: str, record: Record, passages: list) -> bool:
    """Check that a cited basis exists: a real field path, or a real source ID
    whose passage contains the quoted words. This never changes a label; a
    failed check is shown to the reviewer."""
    if not basis:
        return False
    m = re.match(r"\s*\[?(S\d+)\]?\s*[:\-]?\s*(.*)$", basis, re.DOTALL | re.IGNORECASE)
    if m:
        sid, quote = m.group(1).upper(), m.group(2)
        texts = [p.text for p in passages if p.source_id.upper() == sid]
        if not texts:
            return False
        quoted = re.findall(r"[\"“](.+?)[\"”]", quote)
        return all(any(_norm(q) in _norm(t) for t in texts) for q in quoted)
    path = basis.split(":")[0].strip()
    return record.has_path(path)


def corpus_reliance_score(results: list) -> int:
    ungrounded = sum(1 for r in results if r.label == "UNGROUNDED")
    if ungrounded >= 5 or any(r.invented_name_or_date for r in results):
        return 3
    if ungrounded >= 3:
        return 2
    if ungrounded >= 1:
        return 1
    return 0


def run_gate3(client, record: Record, text: str, passages: list, output_id: str, run: str,
              claims: list = None) -> Gate3Result:
    """Run both calls for one output. Pass claims to reuse an earlier
    extraction and run classification only (used by the consistency check).
    Model failures are caught and reported in result.error (Tool fault)."""
    result = Gate3Result(output_id=output_id, record_number=record.number, run=run)
    start = getattr(client, "calls", None)
    try:
        if claims is None:
            claims = extract_claims(client, record, text)
        result.claims = classify_claims(client, record, passages, claims)
        result.cr_score = corpus_reliance_score(result.claims)
    except ModelError as e:
        result.error = "TF: %s" % e
    if start is not None:
        result.model_calls = client.calls - start
    return result
