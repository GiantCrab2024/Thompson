"""CSV copies of Sheet B2 (records) and Sheet B3 (claim table), Appendix B.

The sheet columns come first, in the planner's order and with its headings.
Columns the module can't fill (reviewer decisions, minutes) are left blank
for Rohan. Extra module columns are appended after the sheet columns, so the
sheet layout stays intact.

Sheet B3 is one table per output on paper. Here it is a single long table: the
B3 header fields (Output ID, Record, Run, Checked by, Date) repeat on each row.
"""

import csv

B2_COLUMNS = ["No.", "MODES no.", "Sample", "Detail", "Gate 2", "A claims", "A ungr.",
              "B claims", "B ungr.", "CR", "Flag", "Review A", "Review B", "Gate right?", "Mins"]
B2_EXTRA = ["CR A", "Gate 3 model calls A", "Gate 3 model calls B", "Gate 2 notes", "Gate 3 errors"]

B3_COLUMNS = ["Output ID", "Record", "Run", "Checked by", "Date", "No.",
              "Claim (as worded in the output)", "Basis (MODES field, or source ID and passage)",
              "G / I / U", "Reviewer agrees?", "Note"]
B3_EXTRA = ["Name or exact date", "Basis verified", "Model reason", "Corpus Reliance Score"]


def _blank_if_none(v):
    return "" if v is None else v


def b2_row(row) -> dict:
    """row is a pipeline.RecordRow."""
    g2, a, b = row.gate2, row.gate3_a, row.gate3_b
    errors = "; ".join("%s %s" % (r.run, r.error) for r in (a, b) if r is not None and r.error)
    return {
        "No.": "%02d" % row.index,
        "MODES no.": row.record.number,
        "Sample": row.sample,
        "Detail": g2.detail_score,
        "Gate 2": g2.decision,
        "A claims": a.claim_count if a and not a.error else "",
        "A ungr.": a.ungrounded_count if a and not a.error else "",
        "B claims": b.claim_count if b and not b.error else "",
        "B ungr.": b.ungrounded_count if b and not b.error else "",
        "CR": _blank_if_none(b.cr_score) if b else "",
        "Flag": row.flag,
        "Review A": "", "Review B": "", "Gate right?": "", "Mins": "",
        "CR A": _blank_if_none(a.cr_score) if a else "",
        "Gate 3 model calls A": a.model_calls if a else "",
        "Gate 3 model calls B": b.model_calls if b else "",
        "Gate 2 notes": "; ".join(g2.notes),
        "Gate 3 errors": errors,
    }


def b3_rows(result, checked_by="module", date="") -> list:
    """Rows for one output's claim table (result is a gate3.Gate3Result)."""
    head = {"Output ID": result.output_id, "Record": result.record_number, "Run": result.run,
            "Checked by": checked_by, "Date": date}
    cr = _blank_if_none(result.cr_score)
    if result.error or not result.claims:
        return [dict(head, **{"Model reason": result.error or "no claims extracted",
                              "Corpus Reliance Score": cr})]
    rows = []
    for c in result.claims:
        kinds = [k for k, on in (("name", c.claim.has_name), ("exact date", c.claim.has_exact_date)) if on]
        rows.append(dict(head, **{
            "No.": c.claim.n,
            "Claim (as worded in the output)": c.claim.text,
            "Basis (MODES field, or source ID and passage)": c.basis,
            "G / I / U": c.code,
            "Name or exact date": ", ".join(kinds),
            "Basis verified": {True: "yes", False: "NO", None: ""}[c.basis_verified],
            "Model reason": c.reason,
            "Corpus Reliance Score": cr,
        }))
    return rows


def write_csv(path, columns, rows):
    # utf-8-sig so Excel opens accented names correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_b2(path, record_rows):
    write_csv(path, B2_COLUMNS + B2_EXTRA, [b2_row(r) for r in record_rows])


def write_b3(path, gate3_results, date=""):
    rows = []
    for res in gate3_results:
        rows.extend(b3_rows(res, date=date))
    write_csv(path, B3_COLUMNS + B3_EXTRA, rows)
