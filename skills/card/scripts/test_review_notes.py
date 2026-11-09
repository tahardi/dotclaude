import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from review_notes import USAGE, general_comment, main, review_payload

HEADER = "**Reviewer note:** Other notes"

DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,4 @@
 one
+two
+three
 four
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -10,3 +12,5 @@
 twelve
+thirteen
+fourteen
 fifteen
 sixteen
"""

DELETED_FILE_DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
"""

NO_NEW_LINES_DIFF = """--- a/a.py
+++ b/a.py
@@ -5,2 +4,0 @@
-five
-six
"""

NO_COUNT_DIFF = """--- a/a.py
+++ b/a.py
@@ -3 +3 @@
-old
+new
"""

HEADER_LOOKALIKE_DIFF = """--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
 one
+++ b/c.py
@@ -9 +10 @@
-old
+new
"""


TWO_HUNKS_DIFF = """--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-old
+new
@@ -9 +9 @@
-old
+new
"""

NEW_FILE_DIFF = """--- /dev/null
+++ b/a.py
@@ -0,0 +1,2 @@
+one
+two
"""

NO_NEWLINE_DIFF = """--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
 one
-two
\\ No newline at end of file
+deux
\\ No newline at end of file
--- a/b.py
+++ b/b.py
@@ -3 +3 @@
-old
+new
"""

SPACE_PATH_DIFF = "--- a/a b.py\t\n+++ b/a b.py\t\n@@ -1 +1 @@\n-old\n+new\n"

QUOTED_PATH_DIFF = '--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -1 +1 @@\n-old\n+new\n'


def inline(path, line, text):
    return {"path": path, "line": line, "side": "RIGHT", "body": f"**Reviewer note:** {text}"}


def review(*comments):
    return {"commit_id": "abc123", "event": "COMMENT", "comments": list(comments)}


class ReviewPayloadTest(unittest.TestCase):
    def test_review_payload(self):
        # given
        cases = [
            ("line just past a hunk", [{"path": "a.py", "line": 5, "text": "x"}], DIFF, None),
            ("line just before a hunk", [{"path": "b.py", "line": 11, "text": "x"}], DIFF, None),
            (
                "last line of a hunk",
                [{"path": "a.py", "line": 4, "text": "x"}],
                DIFF,
                review(inline("a.py", 4, "x")),
            ),
            ("line between two hunks", [{"path": "a.py", "line": 5, "text": "x"}], TWO_HUNKS_DIFF, None),
            (
                "line in the second hunk",
                [{"path": "a.py", "line": 9, "text": "x"}],
                TWO_HUNKS_DIFF,
                review(inline("a.py", 9, "x")),
            ),
            (
                "new file",
                [{"path": "a.py", "line": 2, "text": "x"}],
                NEW_FILE_DIFF,
                review(inline("a.py", 2, "x")),
            ),
            (
                "file after a no-newline marker",
                [{"path": "b.py", "line": 3, "text": "x"}],
                NO_NEWLINE_DIFF,
                review(inline("b.py", 3, "x")),
            ),
            (
                "path with a space",
                [{"path": "a b.py", "line": 1, "text": "x"}],
                SPACE_PATH_DIFF,
                review(inline("a b.py", 1, "x")),
            ),
            ("quoted path", [{"path": "café.py", "line": 1, "text": "x"}], QUOTED_PATH_DIFF, None),
            (
                "only the inline note of a mix",
                [{"path": "a.py", "line": 2, "text": "in"}, {"path": "a.py", "line": 40, "text": "out"}],
                DIFF,
                review(inline("a.py", 2, "in")),
            ),
            (
                "note on an added line",
                [{"path": "a.py", "line": 2, "text": "why 5?"}],
                DIFF,
                review(inline("a.py", 2, "why 5?")),
            ),
            (
                "note on a context line inside a hunk",
                [{"path": "b.py", "line": 16, "text": "ok?"}],
                DIFF,
                review(inline("b.py", 16, "ok?")),
            ),
            ("note outside every hunk", [{"path": "a.py", "line": 40, "text": "why 40?"}], DIFF, None),
            ("note on a file not in the diff", [{"path": "c.py", "line": 1, "text": "c?"}], DIFF, None),
            ("note on a deleted file", [{"path": "a.py", "line": 1, "text": "gone?"}], DELETED_FILE_DIFF, None),
            ("note with no path", [{"path": None, "line": None, "text": "tests are slow"}], DIFF, None),
            ("hunk with no new lines", [{"path": "a.py", "line": 4, "text": "x"}], NO_NEW_LINES_DIFF, None),
            (
                "hunk header without a count",
                [{"path": "a.py", "line": 3, "text": "x"}],
                NO_COUNT_DIFF,
                review(inline("a.py", 3, "x")),
            ),
            (
                "notes on two files keep their order",
                [{"path": "b.py", "line": 13, "text": "first"}, {"path": "a.py", "line": 1, "text": "second"}],
                DIFF,
                review(inline("b.py", 13, "first"), inline("a.py", 1, "second")),
            ),
            (
                "added line that looks like a file header is not a file",
                [{"path": "c.py", "line": 10, "text": "x"}],
                HEADER_LOOKALIKE_DIFF,
                None,
            ),
        ]
        for name, notes, diff, expected in cases:
            with self.subTest(name):
                # when
                got = review_payload(notes, diff, "abc123")

                # then
                self.assertEqual(got, expected)

    def test_review_payload_rejects_a_note_without_text(self):
        # given
        good = {"path": None, "line": None, "text": "ok"}
        cases = [
            ("no text", [{"path": None, "line": None}], 1),
            ("empty text", [{"path": None, "line": None, "text": ""}], 1),
            ("whitespace text", [{"path": None, "line": None, "text": "   "}], 1),
            ("second note is numbered 2", [good, {"path": None, "line": None}], 2),
        ]
        for name, notes, number in cases:
            with self.subTest(name):
                # when
                with self.assertRaises(ValueError) as caught:
                    review_payload(notes, "", "abc123")

                # then
                self.assertEqual(str(caught.exception), f"reading notes: note {number} has no text")


class GeneralCommentTest(unittest.TestCase):
    def test_general_comment_with_no_diff_takes_every_note(self):
        # given
        notes = [{"path": "a.py", "line": 2, "text": "why 5?"}]

        # when
        got = general_comment(notes, "")

        # then
        self.assertEqual(got, f"{HEADER}\n\n1. `a.py:2` why 5?")

    def test_general_comment_rejects_a_note_without_text(self):
        # given
        notes = [{"path": None, "line": None, "text": "ok"}, {"path": None, "line": None, "text": " "}]

        # when
        with self.assertRaises(ValueError) as caught:
            general_comment(notes, DIFF)

        # then
        self.assertEqual(str(caught.exception), "reading notes: note 2 has no text")

    def test_general_comment(self):
        # given
        inline_note = {"path": "a.py", "line": 2, "text": "why 5?"}
        whole_pr_note = {"path": None, "line": None, "text": "tests are slow"}
        cases = [
            ("no notes", [], ""),
            ("every note is inline", [inline_note], ""),
            ("one note with no path", [whole_pr_note], f"{HEADER}\n\n1. tests are slow"),
            (
                "note outside the diff names its line",
                [{"path": "a.py", "line": 40, "text": "why 40?"}],
                f"{HEADER}\n\n1. `a.py:40` why 40?",
            ),
            (
                "note with a path and no line names its file",
                [{"path": "a.py", "line": None, "text": "split this file?"}],
                f"{HEADER}\n\n1. `a.py` split this file?",
            ),
            (
                "inline notes are left out of the numbering",
                [inline_note, whole_pr_note, {"path": "c.py", "line": 1, "text": "c?"}],
                f"{HEADER}\n\n1. tests are slow\n2. `c.py:1` c?",
            ),
        ]
        for name, notes, expected in cases:
            with self.subTest(name):
                # when
                got = general_comment(notes, DIFF)

                # then
                self.assertEqual(got, expected)


class MainTest(unittest.TestCase):
    def run_main(self, *args):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["review_notes.py", *args]), redirect_stdout(stdout):
            main()
        return stdout.getvalue()

    def write_files(self, directory, notes):
        notes_path = Path(directory) / "notes.json"
        diff_path = Path(directory) / "review.diff"
        notes_path.write_text(json.dumps(notes))
        diff_path.write_text(DIFF)
        return str(notes_path), str(diff_path)

    def test_main(self):
        inline_note = {"path": "a.py", "line": 2, "text": "why 5?"}
        whole_pr_note = {"path": None, "line": None, "text": "tests are slow"}
        cases = [
            (
                "review prints the payload",
                "review",
                [inline_note],
                json.dumps(review(inline("a.py", 2, "why 5?"))) + "\n",
            ),
            ("review prints nothing with no inline note", "review", [whole_pr_note], ""),
            ("comment prints the comment", "comment", [whole_pr_note], f"{HEADER}\n\n1. tests are slow\n"),
            ("comment prints nothing with no general note", "comment", [inline_note], ""),
        ]
        for name, command, notes, expected in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                notes_path, diff_path = self.write_files(directory, notes)
                extra = ["abc123"] if command == "review" else []

                # when
                got = self.run_main(command, notes_path, diff_path, *extra)

                # then
                self.assertEqual(got, expected)

    def test_main_reads_a_diff_that_is_not_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            # given
            notes_path, diff_path = self.write_files(directory, [{"path": "a.py", "line": 2, "text": "why 5?"}])
            Path(diff_path).write_bytes(DIFF.encode() + b"--- a/l.py\n+++ b/l.py\n@@ -0,0 +1 @@\n+caf\xe9\n")

            # when
            got = self.run_main("review", notes_path, diff_path, "abc123")

            # then
            self.assertEqual(got, json.dumps(review(inline("a.py", 2, "why 5?"))) + "\n")

    def test_main_stops_on_unreadable_notes(self):
        # given
        cases = [
            ("missing notes file", "comment", None, "reading notes: "),
            ("notes file is not JSON", "comment", "{", "reading notes: "),
            ("notes file is not JSON on review", "review", "{", "reading notes: "),
            ("notes are not a list", "comment", "{}", "reading notes: expected a list of notes"),
            ("a note is not an object", "comment", "[1]", "reading notes: expected a list of notes"),
            ("a note has no text", "comment", "[{}]", "reading notes: note 1 has no text"),
        ]
        for name, command, notes_text, expected in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                _, diff_path = self.write_files(directory, [])
                notes_path = Path(directory) / "notes.json"
                notes_path.unlink()
                if notes_text is not None:
                    notes_path.write_text(notes_text)
                extra = ["abc123"] if command == "review" else []
                argv = ["review_notes.py", command, str(notes_path), diff_path, *extra]

                # when
                stdout = io.StringIO()
                with self.assertRaises(SystemExit) as caught, mock.patch.object(sys, "argv", argv), redirect_stdout(
                    stdout
                ):
                    main()

                # then
                self.assertEqual(stdout.getvalue(), "")
                self.assertTrue(str(caught.exception.code).startswith(expected), caught.exception.code)

    def test_main_rejects_a_bad_command(self):
        cases = [
            ("unknown command", ["nope", "a", "b"]),
            ("no arguments", []),
            ("review without a commit", ["review", "a", "b"]),
            ("comment with a commit", ["comment", "a", "b", "c"]),
        ]
        for name, args in cases:
            with self.subTest(name):
                # given
                stderr = io.StringIO()

                # when
                with self.assertRaises(SystemExit) as caught, redirect_stderr(stderr):
                    self.run_main(*args)

                # then
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(stderr.getvalue().strip(), USAGE)


if __name__ == "__main__":
    unittest.main()
