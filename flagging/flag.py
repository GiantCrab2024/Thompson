"""Flag matrix combining gates 2 and 3 (Appendix A)."""

PASS = "Pass"
PASS_NOTE = "Pass, with note"
AMBER = "Amber"
RED = "Red"

ACTIONS = {
    PASS: "Goes to the review queue.",
    PASS_NOTE: "Goes to the review queue and shows the caveat.",
    AMBER: "Review before any publication. Ungrounded claims are highlighted for the reviewer.",
    RED: "Stopped at gate 2. Stub only.",
}


def combine(detail_score: int, cr_score) -> str:
    """Return the flag, or "" when Gate 3 could not score the output."""
    if detail_score <= 1:
        return RED
    if cr_score is None:
        return ""
    if cr_score >= 2:
        return AMBER
    return PASS if detail_score == 3 else PASS_NOTE
