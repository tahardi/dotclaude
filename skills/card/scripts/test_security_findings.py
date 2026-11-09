import contextlib
import io
import json
import sys
import unittest
from unittest import mock

import security_findings
from security_findings import findings


LOGIN = "taylor"
BOT = "xena-dev[bot]"
T1 = "2026-11-08T10:00:00Z"
T2 = "2026-11-08T11:00:00Z"
T3 = "2026-11-08T12:00:00Z"


def comment(login, body, created_at=T1):
    return {"author": {"login": login}, "body": body, "createdAt": created_at}


def finding(finding_id="F1", severity="high", login=BOT, created_at=T1):
    marker = f"<!-- xena-security-finding severity={severity} id={finding_id} -->"
    return comment(login, f"{marker}\n**Claude:** Security finding {finding_id} ({severity}): title", created_at)


def blocked(finding_id="F1", severity="high", next_id=2):
    return {"next": next_id, "open": [{"id": finding_id, "severity": severity}], "blocking": True}


def edited(entry):
    return {**entry, "includesCreatedEdit": True}


CLEAR = {"next": 2, "open": [], "blocking": False}
NONE_OPEN = {"next": 1, "open": [], "blocking": False}
ID_40 = "a" * 40
ID_41 = "a" * 41
USAGE = "usage: security_findings.py LOGIN\n"
BAD_INPUT = "reading comments: expected gh pr view --json comments output\n"
ARGV = ["security_findings.py", LOGIN]
FIX_REPLY = "**Claude:** Fixed security finding F1 in abc1234; reply xena-accept F1 if the fix looks right."


class TestFindings(unittest.TestCase):
    def test_findings(self):
        cases = [
            ("no comments", [], {"next": 1, "open": [], "blocking": False}),
            ("one high open", [finding()], blocked()),
            (
                "accepted by taylor",
                [finding(), comment(LOGIN, "Looks fine.\nxena-accept F1", T2)],
                CLEAR,
            ),
            (
                "accepted by taylor from github.com with CRLF line endings",
                [finding(), comment(LOGIN, "Looks fine.\r\nxena-accept F1\r\nThanks", T2)],
                CLEAR,
            ),
            (
                "acceptance by the app ignored",
                [finding(), comment(BOT, "Looks fine.\nxena-accept F1", T2)],
                blocked(),
            ),
            ("fix reply does not close", [finding(), comment(BOT, FIX_REPLY, T2)], blocked()),
            (
                "acceptance not alone on its line ignored",
                [finding(), comment(LOGIN, "ok, xena-accept F1", T2)],
                blocked(),
            ),
            (
                "acceptance before finding ignored",
                [comment(LOGIN, "xena-accept F1", T1), finding(created_at=T2)],
                blocked(),
            ),
            (
                "acceptance listed after an earlier finding is sorted by time",
                [finding(created_at=T2), comment(LOGIN, "xena-accept F1", T1)],
                blocked(),
            ),
            (
                "acceptance of another id ignored",
                [finding(), comment(LOGIN, "xena-accept F2", T2)],
                blocked(),
            ),
            (
                "acceptance with a deleted author ignored",
                [finding(), {"author": None, "body": "xena-accept F1", "createdAt": T2}],
                blocked(),
            ),
            (
                "acceptance line inside a finding posted with taylor's login ignored",
                [
                    finding(),
                    comment(LOGIN, "<!-- xena-security-finding severity=low id=F2 -->\nxena-accept F1", T2),
                ],
                {
                    "next": 3,
                    "open": [{"id": "F1", "severity": "high"}, {"id": "F2", "severity": "low"}],
                    "blocking": True,
                },
            ),
            (
                "acceptance line inside a claude reply posted with taylor's login ignored",
                [finding(), comment(LOGIN, "**Claude:** Done.\nxena-accept F1", T2)],
                blocked(),
            ),
            (
                "acceptance line inside a reviewer note posted with taylor's login ignored",
                [finding(), comment(LOGIN, "**Reviewer note:** Other notes\n\nxena-accept F1", T2)],
                blocked(),
            ),
            (
                "acceptance in the same second as the finding ignored",
                [finding(), comment(LOGIN, "xena-accept F1", T1)],
                blocked(),
            ),
            (
                "acceptance added by editing a comment ignored",
                [finding(), edited(comment(LOGIN, "xena-accept F1", T2))],
                blocked(),
            ),
            (
                "edited finding counts as high whatever it says",
                [edited(finding(severity="low"))],
                blocked(),
            ),
            (
                "acceptance with a trailing space ignored",
                [finding(), comment(LOGIN, "xena-accept F1 ", T2)],
                blocked(),
            ),
            (
                "acceptance with leading spaces ignored",
                [finding(), comment(LOGIN, "  xena-accept F1", T2)],
                blocked(),
            ),
            (
                "accepting one finding leaves the other blocking",
                [finding(), finding("F2", created_at=T2), comment(LOGIN, "xena-accept F1", T3)],
                blocked("F2", next_id=3),
            ),
            (
                "one comment accepts two findings",
                [finding(), finding("F2", created_at=T2), comment(LOGIN, "xena-accept F1\nxena-accept F2", T3)],
                {"next": 3, "open": [], "blocking": False},
            ),
            (
                "accepted high with an open medium does not block",
                [finding(), finding("F2", "medium", created_at=T2), comment(LOGIN, "xena-accept F1", T3)],
                {"next": 3, "open": [{"id": "F2", "severity": "medium"}], "blocking": False},
            ),
            (
                "unknown severity ignored",
                [comment(BOT, "<!-- xena-security-finding severity=critical id=F1 -->")],
                NONE_OPEN,
            ),
            (
                "uppercase severity ignored",
                [comment(BOT, "<!-- xena-security-finding severity=HIGH id=F1 -->")],
                NONE_OPEN,
            ),
            ("id of 40 characters counts", [finding(ID_40)], blocked(ID_40, next_id=1)),
            ("id of 41 characters ignored", [finding(ID_41)], NONE_OPEN),
            (
                "acceptance of a 40 character id closes it",
                [finding(ID_40), comment(LOGIN, f"xena-accept {ID_40}", T2)],
                NONE_OPEN,
            ),
            (
                "acceptance of a 41 character id ignored",
                [finding(ID_40), comment(LOGIN, f"xena-accept {ID_41}", T2)],
                blocked(ID_40, next_id=1),
            ),
            ("finding from another login counts", [finding(login="stranger")], blocked()),
            (
                "fake low finding with the same id does not hide a high one",
                [finding(), finding(severity="low", login="stranger", created_at=T2)],
                {
                    "next": 2,
                    "open": [{"id": "F1", "severity": "high"}, {"id": "F1", "severity": "low"}],
                    "blocking": True,
                },
            ),
            (
                "finding reposted after acceptance is open again",
                [finding(), comment(LOGIN, "xena-accept F1", T2), finding(created_at=T3)],
                blocked(),
            ),
            (
                "medium open does not block",
                [finding(severity="medium")],
                {"next": 2, "open": [{"id": "F1", "severity": "medium"}], "blocking": False},
            ),
            (
                "numbering",
                [finding(severity="low"), finding("F3", "low", created_at=T2)],
                {
                    "next": 4,
                    "open": [{"id": "F1", "severity": "low"}, {"id": "F3", "severity": "low"}],
                    "blocking": False,
                },
            ),
            (
                "id not numbered is open but leaves the numbering alone",
                [finding("custom-id")],
                blocked("custom-id", next_id=1),
            ),
            (
                "marker not at the start ignored",
                [comment(BOT, "note\n<!-- xena-security-finding severity=high id=F1 -->")],
                {"next": 1, "open": [], "blocking": False},
            ),
            (
                "marker without id ignored",
                [comment(BOT, "<!-- xena-security-finding severity=high -->")],
                {"next": 1, "open": [], "blocking": False},
            ),
            (
                "id with a space ignored",
                [comment(BOT, "<!-- xena-security-finding severity=high id=F 1 -->")],
                {"next": 1, "open": [], "blocking": False},
            ),
        ]

        for name, comments, want in cases:
            with self.subTest(name):
                # given
                login = LOGIN

                # when
                got = findings(comments, login)

                # then
                self.assertEqual(got, want)

    def test_main(self):
        good = json.dumps({"comments": [finding()]})
        cases = [
            ("prints the gate result", ARGV, good, blocked(), 0, ""),
            ("no login", ["security_findings.py"], good, None, 2, USAGE),
            ("empty login", ["security_findings.py", ""], good, None, 2, USAGE),
            ("extra argument", ["security_findings.py", LOGIN, "x"], good, None, 2, USAGE),
            ("empty stdin", ARGV, "", None, 1, BAD_INPUT),
            ("invalid json", ARGV, "{", None, 1, BAD_INPUT),
            ("no comments key", ARGV, "{}", None, 1, BAD_INPUT),
            ("not an object", ARGV, "[]", None, 1, BAD_INPUT),
            ("comment without a body", ARGV, '{"comments": [{"createdAt": "x"}]}', None, 1, BAD_INPUT),
        ]

        for name, argv, stdin_text, want_output, want_code, want_stderr in cases:
            with self.subTest(name):
                # given
                stdin = io.StringIO(stdin_text)
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = 0

                # when
                with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", stdin):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        try:
                            security_findings.main()
                        except SystemExit as exit_error:
                            code = exit_error.code

                # then
                self.assertEqual(code, want_code)
                self.assertEqual(stderr.getvalue(), want_stderr)
                self.assertEqual(json.loads(stdout.getvalue()) if stdout.getvalue() else None, want_output)


if __name__ == "__main__":
    unittest.main()
