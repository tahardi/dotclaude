import os
import unittest

from check_spec import problems

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "spec-template.md")


def template():
    with open(TEMPLATE) as f:
        return f.read()


def filled():
    text = template().replace("Status: Draft <YYYY-MM-DD>", "Status: Approved 2026-10-24")
    lines = []
    for line in text.split("\n"):
        if line.startswith("> Guide:"):
            lines.append("Filled in.")
        elif not line.startswith("> "):
            lines.append(line)
    text = "\n".join(lines)
    text = text.replace("## Requirements\n\nFilled in.", "## Requirements\n\n- **R-F-1:** Logs an attack.")
    text = text.replace("### Secrets\n\nFilled in.", "### Secrets\n\n- **R-SEC-1:** Secrets stay out of the repo.")
    text = text.replace("### Data Handling\n\nFilled in.", "### Data Handling\n\n- **R-PRIV-1:** No health logs.")
    text = text.replace("### Deployment\n\nFilled in.", "### Deployment\n\n- **R-OPS-1:** Starts on boot.")
    return text.replace("## Open Questions\n\nFilled in.", "## Open Questions\n\nNone.")


class TestProblems(unittest.TestCase):
    def test_problems(self):
        cases = [
            ("happy path - filled spec passes approval", filled(), True, []),
            ("error - template has guide lines", template(), False, "unfinished"),
            ("error - missing subsection", filled().replace("### Host", "### Hosting"), False,
             "missing section: ### Host under ## Security and Privacy"),
            ("error - no ops requirement", filled().replace("**R-OPS-1:**", "**R-F-2:**"), False,
             "no R-OPS-n requirement defined"),
            ("error - duplicate id", filled().replace("**R-PRIV-1:**", "**R-F-1:**"), False,
             "requirement defined twice: R-F-1"),
            ("error - open questions left", filled().replace("\nNone.", "\nWhich port?"), True,
             "## Open Questions must say None before approval"),
            ("error - TBD", filled() + "\nPort is TBD\n", False, "unfinished"),
        ]
        for name, text, approved, want in cases:
            with self.subTest(name):
                # given
                spec = text

                # when
                got = problems(spec, approved)

                # then
                if want == []:
                    self.assertEqual(got, [])
                else:
                    self.assertTrue(any(want in p for p in got), got)


if __name__ == "__main__":
    unittest.main()
