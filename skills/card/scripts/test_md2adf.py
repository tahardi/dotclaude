import unittest

from adf import render
from md2adf import convert

STRONG = {"type": "strong"}
CODE = {"type": "code"}


def text(value, *marks):
    node = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def item(*content):
    return {"type": "listItem", "content": [{"type": "paragraph", "content": list(content)}]}


class ConvertTest(unittest.TestCase):
    def test_convert(self):
        cases = [
            (
                "summary bullets become a list with bold labels",
                "- **Problem:** It crashes.\n- **Goal:** It runs.",
                [
                    {
                        "type": "bulletList",
                        "content": [
                            item(text("Problem:", STRONG), text(" It crashes.")),
                            item(text("Goal:", STRONG), text(" It runs.")),
                        ],
                    }
                ],
            ),
            (
                "workflow steps become an ordered list with inline code",
                "1. Run `npm ci`.\n2. Push.",
                [
                    {
                        "type": "orderedList",
                        "content": [item(text("Run "), text("npm ci", CODE), text(".")), item(text("Push."))],
                    }
                ],
            ),
            (
                "a fenced block becomes a code block with its language",
                "```bash\nmake try\n```",
                [{"type": "codeBlock", "attrs": {"language": "bash"}, "content": [text("make try")]}],
            ),
            (
                "a heading keeps its level",
                "## Steps",
                [{"type": "heading", "attrs": {"level": 2}, "content": [text("Steps")]}],
            ),
            (
                "a bold label paragraph keeps its text",
                "**Details:** One paragraph.",
                [{"type": "paragraph", "content": [text("Details:", STRONG), text(" One paragraph.")]}],
            ),
        ]
        for name, md, want in cases:
            with self.subTest(name):
                # given
                given = md

                # when
                got = convert(given)

                # then
                self.assertEqual(got, {"type": "doc", "version": 1, "content": want})

    def test_convert_round_trips_through_render(self):
        # given
        md = "- **Problem:** It crashes.\n- **Done when:** `make pre-pr` exits 0.\n\n**Details:** Text."

        # when
        got = render(convert(md))

        # then
        self.assertEqual(got, md)


if __name__ == "__main__":
    unittest.main()
