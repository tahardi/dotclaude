import unittest

from ideas import list_ideas, remove_idea

NOTE = "# Ideas  (Ideas.md)\n- First\n- Second\n\t- detail\n\t\t- deeper\n- Third"


class TestIdeas(unittest.TestCase):
    def test_list_ideas(self):
        # given
        note = NOTE

        # when
        got = list_ideas(note)

        # then
        self.assertEqual(got, ["1. First", "2. Second", "3. Third"])

    def test_remove_idea(self):
        cases = [
            ("happy path - removes idea with sub-bullets", 2, "- First\n- Third"),
            ("happy path - removes first idea", 1, "- Second\n\t- detail\n\t\t- deeper\n- Third"),
            ("happy path - removes last idea", 3, "- First\n- Second\n\t- detail\n\t\t- deeper"),
        ]
        for name, n, want in cases:
            with self.subTest(name):
                # given
                note = NOTE

                # when
                got = remove_idea(note, n)

                # then
                self.assertEqual(got, want)

    def test_remove_idea_out_of_range(self):
        # given
        note = NOTE

        # when / then
        with self.assertRaises(SystemExit):
            remove_idea(note, 4)


if __name__ == "__main__":
    unittest.main()
