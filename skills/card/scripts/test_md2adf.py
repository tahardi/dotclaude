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


def para(*content):
    return {"type": "paragraph", "content": list(content)}


def item(*content):
    return {"type": "listItem", "content": [para(*content)]}


def block_item(*blocks):
    return {"type": "listItem", "content": list(blocks)}


def link(value, href):
    return text(value, {"type": "link", "attrs": {"href": href}})


def code_block(value, language):
    return {"type": "codeBlock", "attrs": {"language": language}, "content": [text(value)]}


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
            (
                "numbered steps stay one list across a code block under a step",
                "1. Run:\n\n   ```bash\n   make try\n   ```\n\n2. Push.",
                [
                    {
                        "type": "orderedList",
                        "content": [
                            block_item(para(text("Run:")), code_block("make try", "bash")),
                            item(text("Push.")),
                        ],
                    }
                ],
            ),
            (
                "a step keeps an indented paragraph after a blank line",
                "- [ ] Step 1.\n\n  Run it and see it fail.\n- [ ] Step 2.",
                [
                    {
                        "type": "bulletList",
                        "content": [
                            block_item(para(text("[ ] Step 1.")), para(text("Run it and see it fail."))),
                            item(text("[ ] Step 2.")),
                        ],
                    }
                ],
            ),
            (
                "an indented bullet nests under the one above",
                "- A\n  - B\n- C",
                [
                    {
                        "type": "bulletList",
                        "content": [
                            block_item(para(text("A")), {"type": "bulletList", "content": [item(text("B"))]}),
                            item(text("C")),
                        ],
                    }
                ],
            ),
            (
                "an indented line continues the item above",
                "- A\n  more",
                [{"type": "bulletList", "content": [item(text("A more"))]}],
            ),
            (
                "a paragraph after a blank line ends the list",
                "- A\n\nText",
                [{"type": "bulletList", "content": [item(text("A"))]}, para(text("Text"))],
            ),
            (
                "a bare URL becomes a link without its trailing period",
                "See https://x.example/a.",
                [para(text("See "), link("https://x.example/a", "https://x.example/a"), text("."))],
            ),
            (
                "a Markdown link keeps its label and URL",
                "See [the PR](https://x.example/1).",
                [para(text("See "), link("the PR", "https://x.example/1"), text("."))],
            ),
            (
                "bold markers inside backticks stay code",
                "`a**b**`",
                [para(text("a**b**", CODE))],
            ),
            (
                "a table becomes a code block",
                "| a | b |\n| 1 | 2 |",
                [{"type": "codeBlock", "content": [text("| a | b |\n| 1 | 2 |")]}],
            ),
            ("empty input makes an empty document", "", []),
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
        cases = [
            (
                "summary and details",
                "- **Problem:** It crashes.\n- **Done when:** `make pre-pr` exits 0.\n\n**Details:** Text.",
            ),
            (
                "workflow steps with a code block under one",
                "1. Run:\n   ```bash\n   make try\n   ```\n"
                "2. Open https://x.example/pr and [the card](https://x.example/c).",
            ),
            ("steps with a nested list", "- [ ] **Step 1:** Test.\n   - Case A\n   - Case B\n- [ ] **Step 2:** Code."),
        ]
        for name, md in cases:
            with self.subTest(name):
                # given
                given = md

                # when
                got = render(convert(given))

                # then
                self.assertEqual(got, md)


if __name__ == "__main__":
    unittest.main()
