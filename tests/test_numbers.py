import unittest

from flagging.numbers import clean_number

# Invented numbers that follow the patterns found in the DLWP export.


class CleanNumber(unittest.TestCase):
    def check(self, raw, clean, note="", review=False):
        r = clean_number(raw)
        self.assertEqual(r.clean, clean, raw)
        self.assertEqual(r.note, note, raw)
        self.assertEqual(bool(r.review), review, (raw, r.review))

    def test_standard_numbers_unchanged(self):
        for raw in ["ABCDE : 2001.5.3", "ABCDE : 1999.12", "ABCDE : L12", "ABCDE : 2001.5.3.1"]:
            r = clean_number(raw)
            self.assertFalse(r.changed, raw)
            self.assertEqual((r.changes, r.review), ([], []))

    def test_bracketed_note_moved_out(self):
        self.check("ABCDE : 2001.5.3 [Guide]", "ABCDE : 2001.5.3", note="Guide")
        self.check("ABCDE : 2001.5.4 [duplicate]", "ABCDE : 2001.5.4", note="duplicate", review=True)

    def test_trailing_space_and_stop(self):
        self.check("ABCDE : 2001.5.3 ", "ABCDE : 2001.5.3")
        self.check("ABCDE : 2001.5.3.", "ABCDE : 2001.5.3")

    def test_equals_range(self):
        self.check("ABCDE : 2001.5.12=49", "ABCDE : 2001.5.12-49")
        self.check("ABCDE : 2001.5.74=5", "ABCDE : 2001.5.74-5", review=True)

    def test_typing_slips(self):
        self.check("ABCDE : 2001,5.3", "ABCDE : 2001.5.3", review=True)
        self.check("ABCDE : 2001.5.l6", "ABCDE : 2001.5.l6", review=True)

    def test_space_after_letter_code(self):
        self.check("ABCDE : LP 27", "ABCDE : LP27")

    def test_several_items(self):
        self.check("ABCDE : 2001.5.1,4,5", "ABCDE : 2001.5.1,4,5", review=True)
        self.check("ABCDE : 600, 600a", "ABCDE : 600, 600a", review=True)
        self.check("ABCDE : 601a-d", "ABCDE : 601a-d", review=True)

    def test_house_spacing_around_code(self):
        self.check("ABCDE:2001.5.3", "ABCDE : 2001.5.3")


if __name__ == "__main__":
    unittest.main()
