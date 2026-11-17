import unittest

from adf import render


def doc(*content):
    return {"type": "doc", "content": list(content)}


def text(value, *marks):
    return {"type": "text", "text": value, "marks": list(marks)}


def paragraph(*content):
    return {"type": "paragraph", "content": list(content)}


def code_block(value, language=None):
    attrs = {"language": language} if language is not None else {}
    return {"type": "codeBlock", "attrs": attrs, "content": [text(value)]}


CODE = {"type": "code"}


def link(href):
    return {"type": "link", "attrs": {"href": href}}


class RenderTest(unittest.TestCase):
    def test_render(self):
        cases = [
            ("code block with language", doc(code_block("const x = 1;", "ts")), "```ts\nconst x = 1;\n```"),
            ("code block without a language", doc(code_block("a")), "```\na\n```"),
            (
                "code block whose text has three backticks in a longer fence",
                doc(code_block("a\n```\n[x](https://evil.example)", "ts")),
                "````ts\na\n```\n[x](https://evil.example)\n````",
            ),
            (
                "code block whose text has a single backtick in a three-backtick fence",
                doc(code_block("x = `y`", "ts")),
                "```ts\nx = `y`\n```",
            ),
            (
                "code block whose longest backtick run is not the first",
                doc(code_block("````\n`")),
                "`````\n````\n`\n`````",
            ),
            (
                "code block with an unsafe language label dropped",
                doc(code_block("a", "ts\n[x](https://evil.example)")),
                "```\na\n```",
            ),
            ("code block with a trailing newline in its label trimmed", doc(code_block("a", "ts\n")), "```ts\na\n```"),
            (
                "code block keeps a label with every allowed punctuation mark",
                doc(code_block("x", "a+b#c.d-e")),
                "```a+b#c.d-e\nx\n```",
            ),
            (
                "code block keeps the first word of a label with spaces",
                doc(code_block("a", " ts title=x.ts")),
                "```ts\na\n```",
            ),
            (
                "code block with an unsafe first word in its label dropped",
                doc(code_block("a", "ts` title")),
                "```\na\n```",
            ),
            ("inline code", doc(paragraph(text("run "), text("make", CODE))), "run `make`"),
            (
                "link with a label",
                doc(paragraph(text("the PR", link("https://x.example/1")))),
                "[the PR](https://x.example/1)",
            ),
            (
                "link whose text is its URL",
                doc(paragraph(text("https://x.example", link("https://x.example")))),
                "https://x.example",
            ),
            (
                "inline code whose text has backticks in a longer delimiter",
                doc(paragraph(text("a`[x](https://evil.example)``b", CODE))),
                "```a`[x](https://evil.example)``b```",
            ),
            (
                "inline code that starts and ends with a backtick padded with spaces",
                doc(paragraph(text("`a`", CODE))),
                "`` `a` ``",
            ),
        ]
        for name, node, want in cases:
            with self.subTest(name):
                # given
                adf = node

                # when
                got = render(adf)

                # then
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
