"""Consistency check: run Gate 3 twice on the same outputs and compare.

Two comparisons per output (5 model calls each):

  Frozen extraction  Call A once, then Call B twice on the same claim list.
                     Claims line up one to one, so label disagreements can be
                     listed claim by claim.
  Full re-run        Calls A and B both run twice. Claim lists differ between
                     runs and can't be aligned, so this compares the per-output
                     results: claim count, ungrounded count, CR and flag.

Run 1 of the full re-run supplies the first classification of the frozen
comparison, so no call is wasted.
"""

from dataclasses import dataclass

from . import flag
from .gate2 import score_record
from .gate3 import Gate3Result, run_gate3
from .pipeline import output_id


@dataclass
class OutputComparison:
    output_id: str
    detail_score: int
    run1: object       # Gate3Result, full run 1
    run2: object       # Gate3Result, full run 2
    reclassified: object  # Gate3Result, Call B again on run1's claims

    def flags(self):
        return (flag.combine(self.detail_score, self.run1.cr_score),
                flag.combine(self.detail_score, self.run2.cr_score))

    def frozen_pairs(self):
        """[(ClaimResult first, ClaimResult second)] for the frozen comparison."""
        if self.run1.error or self.reclassified.error or self.reclassified.cr_score is None:
            return []
        return list(zip(self.run1.claims, self.reclassified.claims))


def compare_output(client, record, output: dict) -> OutputComparison:
    oid = output_id(record.number, output["run"])
    text, passages, run = output["text"], output["passages"], output["run"]
    run1 = run_gate3(client, record, text, passages, oid, run)
    run2 = run_gate3(client, record, text, passages, oid, run)
    if run1.error:
        # No claim list to reclassify; the fault is already reported on run 1.
        reclassified = Gate3Result(oid, record.number, run)
    else:
        reclassified = run_gate3(client, record, text, passages, oid, run,
                                 claims=[c.claim for c in run1.claims])
    return OutputComparison(oid, score_record(record).detail_score, run1, run2, reclassified)


CLAIM_COLUMNS = ["Output ID", "No.", "Claim", "Label 1", "Label 2", "Agree?",
                 "Basis 1", "Basis 2", "Reason 1", "Reason 2"]
OUTPUT_COLUMNS = ["Output ID", "Detail",
                  "Frozen: claims", "Frozen: labels agree", "Frozen: CR 1", "Frozen: CR 2",
                  "Full: claims 1", "Full: claims 2", "Full: ungr. 1", "Full: ungr. 2",
                  "Full: CR 1", "Full: CR 2", "Full: flag 1", "Full: flag 2",
                  "CR agree?", "Flag agree?", "Errors"]


def claim_rows(comparisons: list) -> list:
    rows = []
    for comp in comparisons:
        for a, b in comp.frozen_pairs():
            rows.append({
                "Output ID": comp.output_id, "No.": a.claim.n, "Claim": a.claim.text,
                "Label 1": a.code, "Label 2": b.code, "Agree?": "yes" if a.label == b.label else "NO",
                "Basis 1": a.basis, "Basis 2": b.basis, "Reason 1": a.reason, "Reason 2": b.reason,
            })
    return rows


def _v(x):
    return "" if x is None else x


def output_rows(comparisons: list) -> list:
    rows = []
    for comp in comparisons:
        pairs = comp.frozen_pairs()
        f1, f2 = comp.flags()
        errors = "; ".join(r.error for r in (comp.run1, comp.run2, comp.reclassified) if r.error)
        both_scored = comp.run1.cr_score is not None and comp.run2.cr_score is not None
        rows.append({
            "Output ID": comp.output_id, "Detail": comp.detail_score,
            "Frozen: claims": len(pairs),
            "Frozen: labels agree": sum(1 for a, b in pairs if a.label == b.label),
            "Frozen: CR 1": _v(comp.run1.cr_score) if pairs else "",
            "Frozen: CR 2": _v(comp.reclassified.cr_score) if pairs else "",
            "Full: claims 1": comp.run1.claim_count, "Full: claims 2": comp.run2.claim_count,
            "Full: ungr. 1": comp.run1.ungrounded_count, "Full: ungr. 2": comp.run2.ungrounded_count,
            "Full: CR 1": _v(comp.run1.cr_score), "Full: CR 2": _v(comp.run2.cr_score),
            "Full: flag 1": f1, "Full: flag 2": f2,
            "CR agree?": ("yes" if comp.run1.cr_score == comp.run2.cr_score else "NO") if both_scored else "",
            "Flag agree?": ("yes" if f1 == f2 else "NO") if both_scored else "",
            "Errors": errors,
        })
    return rows


def summary(comparisons: list) -> str:
    pairs = [p for c in comparisons for p in c.frozen_pairs()]
    label_agree = sum(1 for a, b in pairs if a.label == b.label)
    scored = [c for c in comparisons if c.run1.cr_score is not None and c.run2.cr_score is not None]
    cr_agree = sum(1 for c in scored if c.run1.cr_score == c.run2.cr_score)
    flag_agree = sum(1 for c in scored if c.flags()[0] == c.flags()[1])
    frozen_cr = [c for c in comparisons if c.frozen_pairs()]
    frozen_cr_agree = sum(1 for c in frozen_cr if c.run1.cr_score == c.reclassified.cr_score)
    faults = sum(1 for c in comparisons for r in (c.run1, c.run2, c.reclassified) if r.error)

    lines = [
        "Gate 3 consistency check on %d outputs" % len(comparisons),
        "",
        "Frozen extraction (Call B run twice on the same claims):",
        "  claim labels agree: %d of %d" % (label_agree, len(pairs)),
        "  CR agrees:          %d of %d outputs" % (frozen_cr_agree, len(frozen_cr)),
        "Full re-run (Calls A and B both run twice):",
        "  CR agrees:          %d of %d outputs" % (cr_agree, len(scored)),
        "  flag agrees:        %d of %d outputs" % (flag_agree, len(scored)),
        "Tool faults: %d" % faults,
    ]
    disagreements = [(c.output_id, a, b) for c in comparisons for a, b in c.frozen_pairs() if a.label != b.label]
    if disagreements:
        lines += ["", "Claims labelled differently:"]
        for oid, a, b in disagreements:
            lines.append("  %s #%d %s -> %s: %s" % (oid, a.claim.n, a.code, b.code, a.claim.text))
    return "\n".join(lines)
