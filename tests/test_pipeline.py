import csv
import os
import tempfile
import unittest

from flagging import consistency, flag, sheets
from flagging.llm import CountingClient
from flagging.modes import load_export
from flagging.pipeline import load_outputs, load_samples, score_batch, select_records
from tests.fakes import FakeClient

HERE = os.path.join(os.path.dirname(__file__), "fixtures")
EXPORT = os.path.join(HERE, "synthetic_modes_export.xml")
OUTPUTS = os.path.join(HERE, "synthetic_outputs.jsonl")
SAMPLES = os.path.join(HERE, "synthetic_samples.csv")

UNGROUNDED = [
    "The photographer was Harold Smith.", "The band was led by Harry Roy.", "It was sent in 1951.",
    "The road is named after the Earl De La Warr.", "It was made by Pryce and Sons.",
    "It hung outside the Pavilion.", "It was installed in 1935.", "It was sold in the Pavilion shop.",
]
NAMES = ("Harold Smith", "Harry Roy", "Earl De La Warr", "Pryce")


def fake_client(**overrides):
    labels = {c: "UNGROUNDED" for c in UNGROUNDED}
    labels["This object was probably used at the Pavilion."] = "INFERRED"
    labels.update(overrides)
    return CountingClient(FakeClient(labels=labels, names=NAMES))


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


class FlagMatrix(unittest.TestCase):
    def test_matrix(self):
        cases = [(3, 0, flag.PASS), (3, 1, flag.PASS), (2, 0, flag.PASS_NOTE), (2, 1, flag.PASS_NOTE),
                 (3, 2, flag.AMBER), (2, 3, flag.AMBER), (1, 0, flag.RED), (0, 3, flag.RED),
                 (1, None, flag.RED), (3, None, "")]
        for detail, cr, expected in cases:
            self.assertEqual(flag.combine(detail, cr), expected, (detail, cr))


class Batch(unittest.TestCase):
    def setUp(self):
        self.client = fake_client()
        self.warnings = []
        selected = select_records(load_export(EXPORT), load_samples(SAMPLES))
        self.rows = score_batch(self.client, selected, load_outputs(OUTPUTS), log=self.warnings.append)
        self.by_no = {r.record.number: r for r in self.rows}

    def test_flags(self):
        got = {n: r.flag for n, r in self.by_no.items()}
        self.assertEqual(got, {
            "TEST:0001": "Pass", "TEST:0002": "Pass, with note", "TEST:0003": "Red",
            "TEST:0004": "Red", "TEST:0005": "Amber", "TEST:0006": "Pass, with note",
        })

    def test_stopped_record_run_b_output_ignored(self):
        self.assertIsNone(self.by_no["TEST:0004"].gate3_b)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("TEST:0004", self.warnings[0])

    def test_run_a_still_checked_on_stopped_records(self):
        self.assertEqual(self.by_no["TEST:0003"].gate3_a.cr_score, 3)   # invented date
        self.assertEqual(self.by_no["TEST:0004"].gate3_a.cr_score, 0)   # INFERRED only

    def test_model_calls(self):
        # 10 outputs scored (one Run B output ignored), 2 calls each.
        self.assertEqual(self.client.calls, 20)

    def test_b2_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b2.csv")
            sheets.write_b2(path, self.rows)
            rows = read_csv(path)
        header = rows[0]
        self.assertEqual(header[:len(sheets.B2_COLUMNS)], sheets.B2_COLUMNS)
        r = dict(zip(header, rows[5]))   # TEST:0005
        self.assertEqual((r["No."], r["MODES no."], r["Sample"], r["Detail"], r["Gate 2"]),
                         ("05", "TEST:0005", "N", "2", "Go"))
        self.assertEqual((r["A claims"], r["A ungr."], r["B claims"], r["B ungr."], r["CR"], r["Flag"]),
                         ("5", "4", "3", "2", "3", "Amber"))
        self.assertEqual((r["Review A"], r["Review B"], r["Gate right?"], r["Mins"]), ("", "", "", ""))
        stopped = dict(zip(header, rows[4]))   # TEST:0004
        self.assertEqual((stopped["Gate 2"], stopped["B claims"], stopped["CR"], stopped["Flag"]),
                         ("Stop", "", "", "Red"))

    def test_b3_csv(self):
        results = [r for row in self.rows for r in (row.gate3_a, row.gate3_b) if r]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b3.csv")
            sheets.write_b3(path, results, date="2026-10-06")
            rows = read_csv(path)
        header = rows[0]
        self.assertEqual(header[:len(sheets.B3_COLUMNS)], sheets.B3_COLUMNS)
        claims = [dict(zip(header, r)) for r in rows[1:]]
        self.assertEqual(len(claims), sum(r.claim_count for r in results))
        made_by = next(c for c in claims if c["Claim (as worded in the output)"] == "It was made by Pryce and Sons.")
        self.assertEqual((made_by["Output ID"], made_by["Run"], made_by["G / I / U"], made_by["Name or exact date"],
                          made_by["Checked by"], made_by["Corpus Reliance Score"]),
                         ("TEST:0005-A", "A", "U", "name", "module", "3"))


class Consistency(unittest.TestCase):
    def test_disagreements_reported(self):
        # Calls per output run in this order: full run 1, full run 2, then the
        # frozen reclassification. The fake labels this claim GROUNDED on the
        # first and UNGROUNDED after, to stand in for model drift.
        flaky = "It was sold in the Pavilion shop."
        client = fake_client(**{flaky: ["GROUNDED", "UNGROUNDED", "UNGROUNDED"]})
        records = {r.number: r for r in load_export(EXPORT)}
        outputs = [o for o in load_outputs(OUTPUTS) if o["run"] == "B" and o["record"] != "TEST:0004"]
        comps = [consistency.compare_output(client, records[o["record"]], o) for o in outputs]
        self.assertEqual(client.calls, 5 * len(outputs))

        claim_rows = consistency.claim_rows(comps)
        bad = [r for r in claim_rows if r["Agree?"] == "NO"]
        self.assertEqual([(r["Output ID"], r["Claim"]) for r in bad], [("TEST:0006-B", flaky)])

        out = {r["Output ID"]: r for r in consistency.output_rows(comps)}
        self.assertEqual(out["TEST:0006-B"]["Frozen: labels agree"], 1)
        self.assertEqual((out["TEST:0006-B"]["Frozen: CR 1"], out["TEST:0006-B"]["Frozen: CR 2"]), (0, 1))
        self.assertEqual((out["TEST:0006-B"]["Full: CR 1"], out["TEST:0006-B"]["Full: CR 2"]), (0, 1))
        self.assertEqual(out["TEST:0006-B"]["CR agree?"], "NO")
        self.assertEqual(out["TEST:0006-B"]["Flag agree?"], "yes")   # Pass, with note either way
        self.assertEqual(out["TEST:0001-B"]["CR agree?"], "yes")

        text = consistency.summary(comps)
        self.assertIn("claim labels agree: %d of %d" % (len(claim_rows) - 1, len(claim_rows)), text)
        self.assertIn("TEST:0006-B #2 G -> U", text)


if __name__ == "__main__":
    unittest.main()
