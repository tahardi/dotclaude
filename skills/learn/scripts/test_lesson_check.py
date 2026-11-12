import json
import os
import re
import unittest

from lesson_check import check

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
        ]
        for name, text, want in cases:
            with self.subTest(name):
                # given
                note = text

                # when
                got = check(note)

                # then
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
