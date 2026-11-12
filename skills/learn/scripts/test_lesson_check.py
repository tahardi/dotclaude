import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from lesson_check import check, main

OK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "lesson_ok.md")


def ok():
    with open(OK) as f:
        return f.read()


def block(text, kind):
    return re.search(rf"```{kind}\n(.*?)\n```", text, re.S).group(1)


def with_block(kind, change):
    text = ok()
    data = json.loads(block(text, kind))
    change(data)
    return text.replace(block(text, kind), json.dumps(data))


def step_past_end(data):
    data["steps"][1]["lines"] = [4, 9]


def thirteen_steps(data):
    data["steps"] = [{"lines": [1, 1], "text": "step"}] * 13


def two_questions(data):
    data["questions"] = data["questions"][:2]


def answer_out_of_range(data):
    data["questions"][0]["answer"] = 3


def long_why(data):
    data["questions"][1]["why"] = "x" * 601


def step_from_zero(data):
    data["steps"][0]["lines"] = [0, 1]


def step_backwards(data):
    data["steps"][0]["lines"] = [3, 2]


def long_code(data):
    data["code"] = "\n".join(["x"] * 61)


def wide_code(data):
    data["code"] = "x" * 4001


def long_step_text(data):
    data["steps"][0]["text"] = "x" * 601


def long_question(data):
    data["questions"][0]["question"] = "x" * 301


def long_choice(data):
    data["questions"][0]["choices"][0] = "x" * 201


def one_choice(data):
    data["questions"][0]["choices"] = ["a"]


def six_choices(data):
    data["questions"][0]["choices"] = ["a", "b", "c", "d", "e", "f"]


def bool_answer(data):
    data["questions"][0]["answer"] = True


class TestLessonCheck(unittest.TestCase):
    def test_check(self):
        cases = [
            ("happy path - lesson passes", ok(), []),
            ("happy path - no lesson passes", ok().split("## Lesson")[0] + "## Findings\n", []),
            ("error - bad JSON", ok().replace('{"lang"', '{lang', 1),
             ["checking lesson: maple-trace block is not valid JSON"]),
            ("error - step past the end of the code", with_block("maple-trace", step_past_end),
             ["checking lesson: trace step 2: lines 4-9 are past the end of the code (5 lines)"]),
            ("error - 13 steps", with_block("maple-trace", thirteen_steps),
             ["checking lesson: trace has 13 steps, want 2 to 12"]),
            ("error - 2 questions", with_block("maple-quiz", two_questions),
             ["checking lesson: quiz has 2 questions, want 3 to 5"]),
            ("error - answer out of range", with_block("maple-quiz", answer_out_of_range),
             ["checking lesson: quiz question 1: answer 3 is not a choice index (3 choices)"]),
            ("error - why too long", with_block("maple-quiz", long_why),
             ["checking lesson: quiz question 2: why is 601 characters, want at most 600"]),
            ("error - two quiz blocks", ok().replace("## Findings", "```maple-quiz\n{}\n```\n\n## Findings"),
             ["checking lesson: found 2 maple-quiz blocks, want 1"]),
            ("error - no trace block", re.sub(r"```maple-trace\n.*?\n```\n", "", ok(), flags=re.S),
             ["checking lesson: found 0 maple-trace blocks, want 1"]),
            ("error - step starts at 0", with_block("maple-trace", step_from_zero),
             ["checking lesson: trace step 1: lines 0-1 are not a 1-based range"]),
            ("error - step runs backwards", with_block("maple-trace", step_backwards),
             ["checking lesson: trace step 1: lines 3-2 are not a 1-based range"]),
            ("error - code over 60 lines", with_block("maple-trace", long_code),
             ["checking lesson: trace code is 61 lines, want at most 60"]),
            ("error - code over 4000 characters", with_block("maple-trace", wide_code),
             ["checking lesson: trace: code is 4001 characters, want at most 4000"]),
            ("error - step text too long", with_block("maple-trace", long_step_text),
             ["checking lesson: trace step 1: text is 601 characters, want at most 600"]),
            ("error - question too long", with_block("maple-quiz", long_question),
             ["checking lesson: quiz question 1: question is 301 characters, want at most 300"]),
            ("error - choice too long", with_block("maple-quiz", long_choice),
             ["checking lesson: quiz question 1: choice 1 is 201 characters, want at most 200"]),
            ("error - one choice", with_block("maple-quiz", one_choice),
             ["checking lesson: quiz question 1 has 1 choices, want 2 to 5"]),
            ("error - six choices", with_block("maple-quiz", six_choices),
             ["checking lesson: quiz question 1 has 6 choices, want 2 to 5"]),
            ("error - answer is a boolean", with_block("maple-quiz", bool_answer),
             ["checking lesson: quiz question 1: answer True is not a choice index (3 choices)"]),
            ("error - block is a list", ok().replace(block(ok(), "maple-quiz"), "[]"),
             ["checking lesson: quiz is not an object"]),
        ]
        for name, text, want in cases:
            with self.subTest(name):
                # given
                note = text

                # when
                got = check(note)

                # then
                self.assertEqual(got, want)

    def test_main(self):
        bad = with_block("maple-quiz", two_questions)
        cases = [
            ("happy path - lesson passes", ok(), None, 0, "", ""),
            ("error - lesson fails", bad, None, 1, "checking lesson: quiz has 2 questions, want 3 to 5\n", ""),
            ("error - missing file", None, None, 1, "", "checking lesson: reading {path}: No such file or directory\n"),
            ("error - wrong arguments", None, ["lesson_check.py"], 2, "", "usage: python3 lesson_check.py NOTE\n"),
        ]
        for name, text, argv, want_code, want_out, want_err in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as folder:
                # given
                path = os.path.join(folder, "note.md")
                if text is not None:
                    with open(path, "w") as f:
                        f.write(text)
                out, err = io.StringIO(), io.StringIO()

                # when
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(argv or ["lesson_check.py", path])

                # then
                self.assertEqual(code, want_code)
                self.assertEqual(out.getvalue(), want_out)
                self.assertEqual(err.getvalue(), want_err.format(path=path))


if __name__ == "__main__":
    unittest.main()
