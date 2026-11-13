import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import findings
from findings import code_hash


KEY = "MPL-1"
HEAD = "a" * 40
OLD_HEAD = "b" * 40
NOW = "2026-11-12T18:00:00+00:00"
EARLIER = "2026-11-11T18:00:00+00:00"
CODE = "run(input)"
OTHER_CODE = "spawn(input)"
DECIDED = {"kind": "accept-risk", "reason": "local only", "decidedAt": EARLIER}
FIX_NOW = {"kind": "fix-now", "reason": None, "decidedAt": EARLIER}
APPLIED = {"at": EARLIER, "commit": "c" * 40, "cardKey": None}
LESSON = {"note": "Learning/Security/command-injection.md", "mode": "later", "at": EARLIER}
RESUME = {"round": 1, "sentAt": EARLIER}
USAGE = "usage: findings.py write KEY --head SHA | read KEY | applied KEY ID [--commit SHA] [--card KEY]\n"


def item(**changes):
    base = {
        "severity": "high",
        "handling": "decide",
        "identity": {"kind": "code", "class": "command-injection", "file": "src/x.ts", "code": CODE},
        "line": 3,
        "sources": ["security-pass"],
        "title": "Branch names reach a shell",
        "what": "what text",
        "how": "how text",
        "impact": "impact text",
        "defense": "defense text",
        "chips": ["runs-code"],
    }
    return {**base, **changes}


def other_item(**changes):
    identity = {"kind": "code", "class": "command-injection", "file": "src/y.ts", "code": OTHER_CODE}
    return item(identity=identity, **changes)


def stored(finding_id, code=CODE, file="src/x.ts", **changes):
    base = {
        "id": finding_id,
        "identity": {"kind": "code", "class": "command-injection", "file": file, "hash": code_hash(code)},
        "line": 3,
        "severity": "high",
        "sources": ["security-pass"],
        "title": "Branch names reach a shell",
        "what": "what text",
        "how": "how text",
        "impact": "impact text",
        "defense": "defense text",
        "chips": ["runs-code"],
        "applied": None,
        "decision": None,
        "severityOverride": None,
    }
    return {**base, **changes}


def other_stored(finding_id, **changes):
    return stored(finding_id, code=OTHER_CODE, file="src/y.ts", **changes)


def file(round_number, found, head=HEAD, updated=NOW, resume=None):
    return {
        "version": 1,
        "card": KEY,
        "round": round_number,
        "headSha": head,
        "updatedAt": updated,
        "resume": resume,
        "findings": found,
    }


def old_file(found, resume=None):
    return file(1, found, head=OLD_HEAD, updated=EARLIER, resume=resume)


class TestWrite(unittest.TestCase):
    def test_write(self):
        cases = [
            (
                "no file creates round 1",
                None,
                [item(), other_item()],
                file(1, [stored("F1"), other_stored("F2")]),
                {"round": 1, "ids": ["F1", "F2"], "dropped": 0},
            ),
            (
                "low is dropped",
                None,
                [item(severity="low"), other_item()],
                file(1, [other_stored("F1")]),
                {"round": 1, "ids": ["F1"], "dropped": 1},
            ),
            (
                "unknown severity becomes high",
                None,
                [item(severity="critical")],
                file(1, [stored("F1")]),
                {"round": 1, "ids": ["F1"], "dropped": 0},
            ),
            (
                "two inputs with one identity merge their sources",
                None,
                [item(), item(severity="medium", sources=["agent-review", "security-pass"])],
                file(1, [stored("F1", sources=["security-pass", "agent-review"])]),
                {"round": 1, "ids": ["F1"], "dropped": 0},
            ),
            (
                "undecided finding missing from input is removed",
                old_file([stored("F1")]),
                [other_item()],
                file(2, [other_stored("F2")]),
                {"round": 2, "ids": ["F2"], "dropped": 0},
            ),
            (
                "decided finding is kept and its repeat skipped",
                old_file([stored("F1", decision=DECIDED)]),
                [item(title="New title")],
                file(2, [stored("F1", decision=DECIDED)]),
                {"round": 2, "ids": [], "dropped": 0},
            ),
            (
                "applied fix-now finding that repeats gets a new id",
                old_file([stored("F1", decision=FIX_NOW, applied=APPLIED)]),
                [item()],
                file(2, [stored("F1", decision=FIX_NOW, applied=APPLIED), stored("F2")]),
                {"round": 2, "ids": ["F2"], "dropped": 0},
            ),
            (
                "ids continue from the highest used",
                old_file([other_stored("F7", decision=DECIDED), stored("F9")]),
                [item(identity={"kind": "dependency", "advisory": "GHSA-1", "package": "lodash"})],
                file(
                    2,
                    [
                        other_stored("F7", decision=DECIDED),
                        {
                            **stored("F10"),
                            "identity": {"kind": "dependency", "advisory": "GHSA-1", "package": "lodash"},
                        },
                    ],
                ),
                {"round": 2, "ids": ["F10"], "dropped": 0},
            ),
            (
                "code hash ignores indentation and blank lines",
                old_file([stored("F4", code="if x:\n    run(x)")]),
                [item(identity={**item()["identity"], "code": "  if x:\n\n        run(x)  \n"}, title="New")],
                file(2, [stored("F4", code="if x:\n    run(x)", title="New")]),
                {"round": 2, "ids": ["F4"], "dropped": 0},
            ),
            (
                "merged repeats keep the higher severity",
                None,
                [item(severity="medium"), item(sources=["agent-review"])],
                file(1, [stored("F1", sources=["security-pass", "agent-review"])]),
                {"round": 1, "ids": ["F1"], "dropped": 0},
            ),
            (
                "a later medium repeat keeps high",
                None,
                [item(), item(severity="medium", sources=["agent-review"])],
                file(1, [stored("F1", sources=["security-pass", "agent-review"])]),
                {"round": 1, "ids": ["F1"], "dropped": 0},
            ),
            (
                "null severity becomes high and repeated chips collapse",
                None,
                [item(severity=None, chips=["runs-code", "runs-code"])],
                file(1, [stored("F1")]),
                {"round": 1, "ids": ["F1"], "dropped": 0},
            ),
            (
                "empty input clears undecided findings and keeps decided ones",
                old_file([stored("F1", decision=DECIDED), other_stored("F2")]),
                [],
                file(2, [stored("F1", decision=DECIDED)]),
                {"round": 2, "ids": [], "dropped": 0},
            ),
            (
                "maple fields are kept on an update",
                old_file([stored("F1", severityOverride="low", lesson=LESSON)], resume=RESUME),
                [item(severity="medium", title="New")],
                file(
                    2,
                    [stored("F1", severity="medium", title="New", severityOverride="low", lesson=LESSON)],
                    resume=RESUME,
                ),
                {"round": 2, "ids": ["F1"], "dropped": 0},
            ),
        ]

        for name, existing, items, want_file, want_summary in cases:
            with self.subTest(name):
                # given
                with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
                    os.environ, {"MAPLE_FINDINGS_DIR": folder}
                ):
                    path = os.path.join(folder, f"{KEY}.json")
                    if existing is not None:
                        with open(path, "w") as handle:
                            json.dump(existing, handle)

                    # when
                    got = findings.write(KEY, HEAD, items, NOW)

                    # then
                    with open(path) as handle:
                        self.assertEqual(json.load(handle), want_file)
                    self.assertEqual(got, want_summary)
                    self.assertEqual(os.listdir(folder), [f"{KEY}.json"])


class TestMain(unittest.TestCase):
    def test_main(self):
        good = json.dumps([item()])
        argv = ["findings.py", "write", KEY, "--head", HEAD]
        newer = json.dumps({**file(1, []), "version": 2})
        cases = [
            ("writes to MAPLE_FINDINGS_DIR", argv, good, None, 0, "", {"round": 1, "ids": ["F1"], "dropped": 0}),
            (
                "bad key",
                ["findings.py", "write", "mpl-1", "--head", HEAD],
                good,
                None,
                1,
                "reading findings input: bad card key mpl-1\n",
                None,
            ),
            (
                "unknown chip",
                argv,
                json.dumps([item(chips=["scary"])]),
                None,
                1,
                "reading findings input: item 1: unknown chip scary\n",
                None,
            ),
            (
                "prose over 600 characters",
                argv,
                json.dumps([item(what="x" * 601)]),
                None,
                1,
                "reading findings input: item 1: what is over 600 characters\n",
                None,
            ),
            (
                "missing field",
                argv,
                json.dumps([{key: value for key, value in item().items() if key != "how"}]),
                None,
                1,
                "reading findings input: item 1: missing how\n",
                None,
            ),
            (
                "over 3 chips",
                argv,
                json.dumps([item(chips=["runs-code", "leaks-data", "costs-money", "supply-chain"])]),
                None,
                1,
                "reading findings input: item 1: chips is not a list of up to 3\n",
                None,
            ),
            (
                "unknown source",
                argv,
                json.dumps([item(sources=["someone"])]),
                None,
                1,
                "reading findings input: item 1: unknown source someone\n",
                None,
            ),
            (
                "empty sources",
                argv,
                json.dumps([item(sources=[])]),
                None,
                1,
                "reading findings input: item 1: sources is not a non-empty list\n",
                None,
            ),
            (
                "line 0",
                argv,
                json.dumps([item(line=0)]),
                None,
                1,
                "reading findings input: item 1: line is not a positive number or null\n",
                None,
            ),
            (
                "line true",
                argv,
                json.dumps([item(line=True)]),
                None,
                1,
                "reading findings input: item 1: line is not a positive number or null\n",
                None,
            ),
            (
                "line text",
                argv,
                json.dumps([item(line="3")]),
                None,
                1,
                "reading findings input: item 1: line is not a positive number or null\n",
                None,
            ),
            (
                "unknown identity kind",
                argv,
                json.dumps([item(identity={"kind": "other"})]),
                None,
                1,
                "reading findings input: item 1: identity kind is not code or dependency\n",
                None,
            ),
            (
                "class not kebab-case",
                argv,
                json.dumps([item(identity={**item()["identity"], "class": "Command Injection"})]),
                None,
                1,
                "reading findings input: item 1: identity class is not a kebab-case slug\n",
                None,
            ),
            (
                "identity without code",
                argv,
                json.dumps([item(identity={"kind": "code", "class": "x", "file": "a.ts"})]),
                None,
                1,
                "reading findings input: item 1: identity code is not a non-empty string\n",
                None,
            ),
            (
                "title over 120 characters",
                argv,
                json.dumps([item(title="x" * 121)]),
                None,
                1,
                "reading findings input: item 1: title is over 120 characters\n",
                None,
            ),
            (
                "existing file not json",
                argv,
                good,
                "{",
                1,
                f"reading findings: {KEY}.json: not valid JSON\n",
                None,
            ),
            (
                "existing file without findings",
                argv,
                good,
                json.dumps({"version": 1}),
                1,
                f"reading findings: {KEY}.json: not a findings file\n",
                None,
            ),
            (
                "existing file without a round",
                argv,
                good,
                json.dumps({k: v for k, v in file(1, []).items() if k != "round"}),
                1,
                f"reading findings: {KEY}.json: not a findings file\n",
                None,
            ),
            (
                "existing finding with a text identity",
                argv,
                good,
                json.dumps(file(1, [stored("F1", identity="x")])),
                1,
                f"reading findings: {KEY}.json: not a findings file\n",
                None,
            ),
            (
                "existing finding with a text decision",
                argv,
                good,
                json.dumps(file(1, [stored("F1", decision="fix-now")])),
                1,
                f"reading findings: {KEY}.json: not a findings file\n",
                None,
            ),
            (
                "existing finding without an id",
                argv,
                good,
                json.dumps(file(1, [{"decision": None}])),
                1,
                f"reading findings: {KEY}.json: not a findings file\n",
                None,
            ),
            ("not json", argv, "{", None, 1, "reading findings input: not valid JSON\n", None),
            ("not an array", argv, "{}", None, 1, "reading findings input: expected a JSON array\n", None),
            (
                "newer file version",
                argv,
                good,
                newer,
                1,
                f"reading findings: {KEY}.json is from a newer version\n",
                None,
            ),
            ("no arguments", ["findings.py"], good, None, 2, USAGE, None),
            ("no head", ["findings.py", "write", KEY], good, None, 2, USAGE, None),
            (
                "rename fails",
                argv,
                good,
                None,
                1,
                f"writing findings: {KEY}.json: Permission denied\n",
                None,
            ),
        ]
        rename_errors = {"rename fails": OSError(13, "Permission denied")}

        for name, args, stdin_text, existing, want_code, want_stderr, want_output in cases:
            with self.subTest(name):
                # given
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = 0
                with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
                    os.environ, {"MAPLE_FINDINGS_DIR": folder}
                ):
                    path = os.path.join(folder, f"{KEY}.json")
                    if existing is not None:
                        with open(path, "w") as handle:
                            handle.write(existing)

                    rename = mock.patch.object(findings.os, "replace", side_effect=rename_errors.get(name, os.replace))

                    # when
                    with mock.patch.object(sys, "argv", args), mock.patch.object(
                        sys, "stdin", io.StringIO(stdin_text)
                    ), rename:
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            try:
                                findings.main()
                            except SystemExit as exit_error:
                                code = exit_error.code

                    # then
                    self.assertEqual(code, want_code)
                    self.assertEqual(stderr.getvalue(), want_stderr)
                    self.assertEqual(json.loads(stdout.getvalue()) if stdout.getvalue() else None, want_output)
                    self.assertEqual(os.path.exists(path), want_code == 0 or existing is not None)
                    self.assertEqual([entry for entry in os.listdir(folder) if entry.endswith(".tmp")], [])


def run_main(args, existing):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"MAPLE_FINDINGS_DIR": folder}):
        path = os.path.join(folder, f"{KEY}.json")
        if existing is not None:
            with open(path, "w") as handle:
                json.dump(existing, handle)
        with mock.patch.object(sys, "argv", ["findings.py", *args]), mock.patch.object(
            findings, "now", return_value=NOW
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    findings.main()
                except SystemExit as exit_error:
                    code = exit_error.code
        saved = None
        if os.path.exists(path):
            with open(path) as handle:
                saved = json.load(handle)
        leftovers = [entry for entry in os.listdir(folder) if entry.endswith(".tmp")]
    return code, stdout.getvalue(), stderr.getvalue(), saved, leftovers


class TestRead(unittest.TestCase):
    def test_read(self):
        fix_later = {"kind": "fix-later", "reason": None, "decidedAt": EARLIER}
        cases = [
            ("missing file prints an empty list", None, []),
            ("file with no findings prints an empty list", file(1, []), []),
            (
                "lists decided unapplied findings only",
                file(
                    2,
                    [
                        stored("F1"),
                        stored("F2", decision=FIX_NOW, applied=APPLIED),
                        other_stored("F3", decision=fix_later),
                    ],
                ),
                [other_stored("F3", decision=fix_later)],
            ),
            (
                "override replaces the severity",
                file(1, [stored("F1", decision=DECIDED, severityOverride="medium", lesson=LESSON)]),
                [stored("F1", decision=DECIDED, severity="medium", severityOverride="medium", lesson=LESSON)],
            ),
            (
                "override can lower to low",
                file(1, [stored("F1", decision=FIX_NOW, severityOverride="low")]),
                [stored("F1", decision=FIX_NOW, severity="low", severityOverride="low")],
            ),
        ]

        for name, existing, want in cases:
            with self.subTest(name):
                # given
                args = ["read", KEY]

                # when
                code, stdout, stderr, _, _ = run_main(args, existing)

                # then
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), want)


def stamp(commit, card):
    return {"at": NOW, "commit": commit, "cardKey": card}


class TestApplied(unittest.TestCase):
    def test_applied(self):
        fix_later = {"kind": "fix-later", "reason": None, "decidedAt": EARLIER}
        maple = {"severityOverride": "medium", "lesson": LESSON, "visual": {"kind": "flow"}}
        existing = file(
            2,
            [stored("F1", decision=FIX_NOW, **maple), other_stored("F2", decision=fix_later), stored("F3")],
            resume=RESUME,
        )
        cases = [
            (
                "stamps a commit and keeps Maple's fields",
                ["applied", KEY, "F1", "--commit", "abc1234"],
                0,
                "",
                file(
                    2,
                    [
                        stored("F1", decision=FIX_NOW, applied=stamp("abc1234", None), **maple),
                        other_stored("F2", decision=fix_later),
                        stored("F3"),
                    ],
                    resume=RESUME,
                ),
            ),
            (
                "stamps a card key",
                ["applied", KEY, "F2", "--card", "MPL-400"],
                0,
                "",
                file(
                    2,
                    [
                        stored("F1", decision=FIX_NOW, **maple),
                        other_stored("F2", decision=fix_later, applied=stamp(None, "MPL-400")),
                        stored("F3"),
                    ],
                    resume=RESUME,
                ),
            ),
            (
                "stamps with neither",
                ["applied", KEY, "F2"],
                0,
                "",
                file(
                    2,
                    [
                        stored("F1", decision=FIX_NOW, **maple),
                        other_stored("F2", decision=fix_later, applied=stamp(None, None)),
                        stored("F3"),
                    ],
                    resume=RESUME,
                ),
            ),
            (
                "unknown id",
                ["applied", KEY, "F9", "--commit", "abc1234"],
                1,
                "marking finding applied: no finding F9\n",
                existing,
            ),
            (
                "undecided finding",
                ["applied", KEY, "F3", "--commit", "abc1234"],
                1,
                "marking finding applied: F3 is not decided\n",
                existing,
            ),
            ("unknown flag", ["applied", KEY, "F1", "--sha", "abc1234"], 2, USAGE, existing),
            ("bad card key", ["applied", KEY, "F2", "--card", "mpl-400"], 2, USAGE, existing),
        ]

        for name, args, want_code, want_stderr, want_file in cases:
            with self.subTest(name):
                # given
                given = json.loads(json.dumps(existing))

                # when
                code, _, stderr, saved, leftovers = run_main(args, given)

                # then
                self.assertEqual(code, want_code)
                self.assertEqual(stderr, want_stderr)
                self.assertEqual(saved, want_file)
                self.assertEqual(leftovers, [])


class TestFindingsPath(unittest.TestCase):
    def test_findings_path(self):
        # given
        environ = {key: value for key, value in os.environ.items() if key != "MAPLE_FINDINGS_DIR"}

        # when
        with mock.patch.dict(os.environ, environ, clear=True):
            got = findings.findings_path(KEY)

        # then
        self.assertEqual(str(got), os.path.expanduser(f"~/.config/maple/findings/{KEY}.json"))


if __name__ == "__main__":
    unittest.main()
