import os
import tempfile
import unittest

from flagging.gate2 import STUB_TEXT, is_placeholder, score_from_count, score_record, should_generate
from flagging.modes import Record, load_export, parse_modes_csv, parse_modes_xml

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_modes_export.xml")


def by_number():
    return {r.number: r for r in load_export(FIXTURE)}


class ScoreBands(unittest.TestCase):
    def test_paper_fallback_bands(self):
        self.assertEqual([score_from_count(n) for n in range(6)], [0, 0, 1, 2, 2, 3])


class SyntheticExport(unittest.TestCase):
    # (Detail Score, decision, elements present) expected for each fixture record.
    EXPECTED = {
        "TEST:0001": (3, "Go", 5),
        "TEST:0002": (2, "Go", 3),   # maker is "unknown"; Role alone doesn't count
        "TEST:0003": (1, "Stop", 2),  # description is a bare label
        "TEST:0004": (0, "Stop", 1),  # placeholders everywhere
        "TEST:0005": (2, "Go", 4),   # "De La Warr Road" noise record; maker "not known"
        "TEST:0006": (2, "Go", 3),   # description is 13 words, under the 15-word bar
        "TEST:0007": (2, "Go", 4),   # inline markup and mixed-content maker
        "TEST:0008": (2, "Go", 4),   # acquisition marked confidential
        "TEST:0009": (0, "Stop", 1),  # nested ItemList object doesn't count
        "TEST:0010": (0, "Stop", 0),  # whole record confidential
    }

    def test_all_records_parsed(self):
        self.assertEqual(sorted(by_number()), sorted(self.EXPECTED))

    def test_scores(self):
        records = by_number()
        for number, (score, decision, count) in self.EXPECTED.items():
            with self.subTest(number):
                r = score_record(records[number])
                self.assertEqual((r.detail_score, r.decision, r.element_count), (score, decision, count), r.elements)

    def test_stub_and_caveat(self):
        records = by_number()
        self.assertEqual(score_record(records["TEST:0004"]).stub, STUB_TEXT)
        self.assertEqual(score_record(records["TEST:0001"]).stub, "")
        self.assertTrue(score_record(records["TEST:0002"]).caveat)
        self.assertEqual(score_record(records["TEST:0001"]).caveat, "")

    def test_spec_checks_are_notes_only(self):
        records = by_number()
        notes3 = score_record(records["TEST:0003"]).notes
        self.assertTrue(any("bare label" in n for n in notes3))
        self.assertTrue(any("no marks" in n for n in notes3))
        self.assertFalse(any("no marks" in n for n in score_record(records["TEST:0001"]).notes))

    def test_run_a_never_stops(self):
        r = score_record(by_number()["TEST:0004"])
        self.assertTrue(should_generate(r, "A"))
        self.assertFalse(should_generate(r, "B"))


class SchemaHandling(unittest.TestCase):
    def setUp(self):
        self.records = by_number()

    def fields(self, number):
        return dict(self.records[number].fields)

    def test_inline_markup_joined_into_parent(self):
        f = self.fields("TEST:0007")
        self.assertEqual(f["Object/Identification/BriefDescription"],
                         "A signed poster advertising the opening of the De La Warr Pavilion in "
                         "December with a drawing of the terrace.")
        self.assertEqual(f["Object/Production/Person"], "Edward McKnight Kauffer")
        self.assertNotIn("Object/Identification/BriefDescription/emph", f)

    def test_confidential_and_admin_fields_withheld(self):
        rec = self.records["TEST:0008"]
        text = rec.as_prompt_text()
        for hidden in ("private seller", "purchase", "Insured value", "B4"):
            self.assertNotIn(hidden, text)
        self.assertEqual(rec.withheld, ["Object/Acquisition (confidentiality=confidential)"])
        self.assertTrue(any("withheld" in n for n in score_record(rec).notes))

    def test_nested_object_not_a_record_or_parent_field(self):
        self.assertNotIn("TEST:0009.1", self.records)
        self.assertNotIn("studio photographer", self.records["TEST:0009"].as_prompt_text())

    def test_whole_record_confidential(self):
        rec = self.records["TEST:0010"]
        self.assertEqual((rec.fields, rec.withheld), ([], ["Object (confidentiality=restricted)"]))

    def test_latin1_and_namespaces(self):
        data = ('<?xml version="1.0" encoding="iso-8859-1"?>'
                '<t:Interchange xmlns:t="http://www.w3.org/namespace/"><t:Object>'
                '<t:ObjectIdentity><t:Number>N1</t:Number></t:ObjectIdentity>'
                '<t:Production><t:Person><t:PersonName>Ren\u00e9e Caf\u00e9</t:PersonName></t:Person></t:Production>'
                '</t:Object></t:Interchange>').encode("iso-8859-1")
        [rec] = parse_modes_xml(data)
        self.assertEqual(rec.number, "N1")
        self.assertIn(("Object/Production/Person/PersonName", "Ren\u00e9e Caf\u00e9"), rec.fields)

    def test_elementtype_and_aspect_labels(self):
        data = ('<Object><ObjectIdentity><Number>E1</Number></ObjectIdentity>'
                '<Production><Date elementtype="creation date"><DateBegin>4.1935</DateBegin></Date>'
                '<Person><PersonName>A maker</PersonName><Dates>1890-1960</Dates></Person></Production>'
                '<Description><Aspect><Type>photo format</Type><Reading>35 mm</Reading></Aspect>'
                '<Aspect><Type>colour</Type><Keyword>blue</Keyword></Aspect></Description>'
                '</Object>').encode()
        [rec] = parse_modes_xml(data)
        f = dict(rec.fields)
        self.assertEqual(f["Object/Production/Date (creation date)/DateBegin"], "4.1935")
        self.assertEqual(f["Object/Description/Aspect (photo format)/Reading"], "35 mm")
        r = score_record(rec)
        self.assertTrue(r.elements["date"])
        self.assertTrue(r.elements["materials"])   # via the photo format Aspect

    def test_maker_life_dates_are_not_a_production_date(self):
        rec = Record("L", [("Object/Production/Person/PersonName", "A maker"),
                           ("Object/Production/Person/Dates", "1890-1960")])
        self.assertFalse(score_record(rec).elements["date"])

    def test_colour_aspect_is_not_format(self):
        rec = Record("C", [("Object/Description/Aspect (colour)/Keyword", "blue")])
        self.assertFalse(score_record(rec).elements["materials"])

    def test_non_current_content_withheld(self):
        data = ('<Object><ObjectIdentity><Number>K1</Number></ObjectIdentity>'
                '<Identification><ObjectName><Keyword currency="obsolete">an outdated term</Keyword>'
                '<Keyword currency="current">figure</Keyword></ObjectName></Identification></Object>').encode()
        [rec] = parse_modes_xml(data)
        self.assertNotIn("outdated", rec.as_prompt_text())
        self.assertIn("figure", rec.as_prompt_text())
        self.assertEqual(rec.withheld, ["Object/Identification/ObjectName/Keyword (currency=obsolete)"])

    def test_qualifiers_alone_are_not_values(self):
        rec = Record("Q", [("Object/Production/Person/Role", "maker"),
                           ("Object/Production/Date/Type", "production"),
                           ("Object/Production/Date/Note", "date uncertain")])
        r = score_record(rec)
        self.assertFalse(r.elements["maker"])
        self.assertFalse(r.elements["date"])


class DescriptionLength(unittest.TestCase):
    def record(self, words):
        desc = " ".join("word%d" % i for i in range(words))
        return Record("X", [("Object/Identification/BriefDescription", desc)])

    def test_fifteen_word_boundary(self):
        self.assertFalse(score_record(self.record(14)).elements["description"])
        self.assertTrue(score_record(self.record(15)).elements["description"])


class Placeholders(unittest.TestCase):
    def test_placeholders(self):
        for v in ["?", "Unknown", "unknown.", " ?? ", "N/A", "-", "(not known)"]:
            self.assertTrue(is_placeholder(v), v)
        for v in ["c. 1935?", "1930s", "Unknown maker's mark on base"]:
            self.assertFalse(is_placeholder(v), v)


class CsvExport(unittest.TestCase):
    def test_csv_columns_map_to_elements(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("ObjectIdentity/Number,Identification/BriefDescription,Production.Date,"
                    "Production>Person>PersonName,Description/Material,Acquisition/Method\n")
            f.write("C1,%s,1935,Unknown,paper,gift\n" % " ".join(["w"] * 16))
        try:
            [rec] = parse_modes_csv(f.name)
        finally:
            os.unlink(f.name)
        r = score_record(rec)
        self.assertEqual(rec.number, "C1")
        self.assertEqual(r.elements, {"description": True, "date": True, "maker": False,
                                      "materials": True, "acquisition": True})
        self.assertEqual(r.detail_score, 2)


if __name__ == "__main__":
    unittest.main()
