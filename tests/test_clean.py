import csv
import os
import tempfile
import unittest

from flagging.clean import clean_export
from flagging.modes import load_export

# Invented records that follow the patterns found in the DLWP export.
EXPORT = b"""<?xml version="1.0" encoding="iso-8859-1"?>
<Interchange>
<Object><ObjectIdentity><Number>ABCDE : 2001.5.1</Number></ObjectIdentity>
  <Identification><BriefDescription>A full record of a printed programme with many fields filled in.</BriefDescription></Identification>
  <Production><Date>1950</Date></Production><Description><Material><Keyword>paper</Keyword></Material></Description>
  <Administration><CollectionName>documents</CollectionName></Administration></Object>
<Object><ObjectIdentity><Number>ABCDE : 2001.5.1 [Guide]</Number></ObjectIdentity>
  <Identification><BriefDescription>Short legacy record.</BriefDescription></Identification></Object>
<Object><ObjectIdentity><Number>ABCDE : 2001.5.2=4</Number></ObjectIdentity>
  <Identification><BriefDescription>Three programmes.</BriefDescription></Identification></Object>
<Object><ObjectIdentity><Number>ABCDE : 2001.5.l6</Number></ObjectIdentity>
  <Identification><BriefDescription>Odd number.</BriefDescription></Identification></Object>
</Interchange>"""


class CleanExport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.dir.name, "in.xml")
        self.out = os.path.join(self.dir.name, "out.xml")
        with open(self.src, "wb") as f:
            f.write(EXPORT)
        self.rows = {r["MODES no. as exported"]: r for r in clean_export(self.src, self.out)}

    def tearDown(self):
        self.dir.cleanup()

    def test_working_copy(self):
        numbers = [r.number for r in load_export(self.out)]
        self.assertEqual(numbers, ["ABCDE : 2001.5.1", "ABCDE : 2001.5.2-4", "ABCDE : 2001.5.l6"])
        with open(self.out, "rb") as f:
            self.assertIn(b"iso-8859-1", f.read(60))

    def test_report(self):
        self.assertEqual(self.rows["ABCDE : 2001.5.1"]["Action"], "kept; duplicate record dropped")
        self.assertTrue(self.rows["ABCDE : 2001.5.1 [Guide]"]["Action"].startswith("dropped"))
        self.assertEqual(self.rows["ABCDE : 2001.5.1 [Guide]"]["Note moved out"], "Guide")
        self.assertEqual(self.rows["ABCDE : 2001.5.2=4"]["Action"], "number cleaned")
        self.assertIn("correct number unknown", self.rows["ABCDE : 2001.5.l6"]["Check"])

    def test_source_untouched(self):
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), EXPORT)


if __name__ == "__main__":
    unittest.main()
