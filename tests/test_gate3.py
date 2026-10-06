import json
import unittest

from flagging.gate3 import (CLASSIFICATION_SYSTEM, EXTRACTION_SYSTEM, Claim, ClaimResult, Passage,
                            corpus_reliance_score, run_gate3, verify_basis)
from flagging.llm import CountingClient
from flagging.modes import Record
from tests.fakes import FakeClient

RECORD = Record("TEST : 0001", [
    ("Object/Identification/BriefDescription", "Photograph of the south staircase of the De La Warr Pavilion."),
    ("Object/Production/Date/DateBegin", "1936"),
])
PASSAGES = [Passage("S03", "The Pavilion opened to the public in December 1935.")]
TEXT = ("This photograph shows the south staircase. The Pavilion opened in December 1935. "
        "It was designed by Erich Mendelsohn and Serge Chermayeff.")


def results(labels, name=False, date=False):
    return [ClaimResult(Claim(i, "c%d" % i, has_name=name, has_exact_date=date), lab, "", "")
            for i, lab in enumerate(labels, start=1)]


class Scoring(unittest.TestCase):
    def test_bands(self):
        for ungrounded, expected in [(0, 0), (1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (7, 3)]:
            labels = ["UNGROUNDED"] * ungrounded + ["GROUNDED", "INFERRED"]
            self.assertEqual(corpus_reliance_score(results(labels)), expected, ungrounded)

    def test_invented_name_or_date_scores_3(self):
        self.assertEqual(corpus_reliance_score(results(["UNGROUNDED"], name=True)), 3)
        self.assertEqual(corpus_reliance_score(results(["UNGROUNDED"], date=True)), 3)

    def test_grounded_name_does_not_score_3(self):
        self.assertEqual(corpus_reliance_score(results(["GROUNDED", "INFERRED"], name=True, date=True)), 0)


class TwoCalls(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient(
            labels={"It was designed by Erich Mendelsohn and Serge Chermayeff.": "UNGROUNDED"},
            names=("Mendelsohn",))
        self.client = CountingClient(self.fake)
        self.res = run_gate3(self.client, RECORD, TEXT, PASSAGES, "TEST : 0001-B", "B")

    def test_two_separate_calls(self):
        self.assertEqual(self.res.model_calls, 2)
        (sys_a, user_a), (sys_b, user_b) = self.fake.log
        self.assertEqual(sys_a, EXTRACTION_SYSTEM)
        self.assertEqual(sys_b, CLASSIFICATION_SYSTEM)

    def test_extraction_sees_record_and_text_only(self):
        _, user_a = self.fake.log[0]
        self.assertIn(TEXT, user_a)
        self.assertIn("BriefDescription", user_a)
        self.assertNotIn(PASSAGES[0].text, user_a)

    def test_classification_never_sees_prose(self):
        _, user_b = self.fake.log[1]
        self.assertNotIn(TEXT, user_b)
        self.assertNotIn("GENERATED TEXT", user_b)
        self.assertIn("[S03] " + PASSAGES[0].text, user_b)
        self.assertIn("Object/Production/Date/DateBegin: 1936", user_b)
        self.assertIn("day.month.year", user_b)

    def test_result(self):
        self.assertEqual(self.res.claim_count, 3)
        self.assertEqual(self.res.ungrounded_count, 1)
        self.assertTrue(self.res.has_invented_name_or_date)
        self.assertEqual(self.res.cr_score, 3)
        self.assertEqual([c.code for c in self.res.claims], ["G", "G", "U"])

    def test_frozen_claims_skip_extraction(self):
        claims = [c.claim for c in self.res.claims]
        again = run_gate3(self.client, RECORD, TEXT, PASSAGES, "TEST : 0001-B", "B", claims=claims)
        self.assertEqual(again.model_calls, 1)
        self.assertEqual(self.fake.log[-1][0], CLASSIFICATION_SYSTEM)


class ToolFaults(unittest.TestCase):
    def run_with(self, *replies):
        return run_gate3(CountingClient(FakeClient(raw_replies=replies)), RECORD, TEXT, PASSAGES, "X-B", "B")

    def test_malformed_json(self):
        res = self.run_with("Here are the claims: 1. ...")
        self.assertIsNone(res.cr_score)
        self.assertTrue(res.error.startswith("TF:"))

    def test_unclassified_claim(self):
        claims = json.dumps({"claims": [{"n": 1, "claim": "a"}, {"n": 2, "claim": "b"}]})
        labels = json.dumps({"classifications": [{"n": 1, "label": "GROUNDED", "basis": "x"}]})
        res = self.run_with(claims, labels)
        self.assertIn("not classified", res.error)
        self.assertEqual(res.model_calls, 2)

    def test_unknown_label(self):
        claims = json.dumps({"claims": [{"n": 1, "claim": "a"}]})
        labels = json.dumps({"classifications": [{"n": 1, "label": "PROBABLY", "basis": ""}]})
        self.assertIn("unknown label", self.run_with(claims, labels).error)

    def test_no_claims_scores_zero(self):
        res = self.run_with(json.dumps({"claims": []}))
        self.assertEqual((res.cr_score, res.model_calls, res.error), (0, 1, ""))


class BasisCheck(unittest.TestCase):
    def test_field_path(self):
        self.assertTrue(verify_basis("Object/Production/Date/DateBegin", RECORD, PASSAGES))
        self.assertFalse(verify_basis("Object/Production/Person/PersonName", RECORD, PASSAGES))

    def test_source_quote(self):
        self.assertTrue(verify_basis('S03: "opened to the public in December 1935"', RECORD, PASSAGES))
        self.assertFalse(verify_basis('S03: "opened in 1934"', RECORD, PASSAGES))
        self.assertFalse(verify_basis('S07: "opened"', RECORD, PASSAGES))


if __name__ == "__main__":
    unittest.main()
