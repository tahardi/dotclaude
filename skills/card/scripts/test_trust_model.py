import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

import trust_model
from findings import code_hash
from trust_model import problems

TEMPLATES = Path(__file__).parent.parent / "trust-model"
MD = "docs/security/trust-model.md"
MODEL = ".maple/trust-model.yaml"
SECURITY = ".maple/security.yaml"
CODE = {"kind": "code", "class": "command-injection", "file": "api/run.go", "hash": "0123456789abcdef"}
DEPENDENCY = {"kind": "dependency", "advisory": "GHSA-35jh-r3h4-6jhm", "package": "lodash"}
USAGE = "usage: trust_model.py check DIR | base SHA | track DIR | apply KEY | diff KEY --base SHA\n"
REAL_RUN = subprocess.run
MISSING = f"checking trust model: {MODEL} is missing\nchecking trust model: {SECURITY} is missing\n"


def copy_templates(repo):
    for name, rel in [("trust-model.md", MD), ("trust-model.yaml", MODEL), ("security.yaml", SECURITY)]:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TEMPLATES / name, repo / rel)


def remove(rel):
    return lambda repo: (repo / rel).unlink()


def replace(rel, old, new):
    def change(repo):
        path = repo / rel
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, new))

    return change


def change_yaml(rel, update):
    def change(repo):
        path = repo / rel
        data = yaml.safe_load(path.read_text())
        update(data)
        path.write_text(yaml.safe_dump(data))

    return change


def model(update):
    return change_yaml(MODEL, update)


def security(update):
    return change_yaml(SECURITY, update)


def empty(key):
    return lambda data: data.update({key: []})


def drop_build(key):
    return lambda data: data["build"].pop(key)


def write(rel, text):
    return lambda repo: (repo / rel).write_text(text)


def checking(text):
    return [f"checking trust model: {text}"]


def commit_files(folder, files):
    git = ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    for rel, text in files.items():
        path = Path(folder) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    result = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class Reading:
    def __init__(self, rel):
        self.prefix = f"reading trust model: {rel}: "

    def __eq__(self, other):
        return isinstance(other, str) and other.startswith(self.prefix) and len(other) > len(self.prefix) and (
            "\n" not in other
        )

    def __repr__(self):
        return f"{self.prefix}<reason>"


def slow_show(command, **kwargs):
    if command[1] == "show":
        raise subprocess.TimeoutExpired(command, 30)
    return REAL_RUN(command, **kwargs)


def no_git(command, **kwargs):
    raise FileNotFoundError(2, "No such file or directory")


class Unfiltered:
    def __init__(self, rel=MODEL):
        self.rel = rel

    def __eq__(self, other):
        if not isinstance(other, str):
            return False
        data = json.loads(other)
        return (
            set(data) == {"optedIn", "warning"}
            and data["optedIn"] is False
            and data["warning"].startswith(f"reading trust model: {self.rel}: ")
            and data["warning"].endswith("; findings unfiltered")
        )

    def __repr__(self):
        return '{"optedIn": false, "warning": "reading trust model: ...; findings unfiltered"}'


class TestProblems(unittest.TestCase):
    def test_problems(self):
        cases = [
            ("templates pass", lambda repo: None, []),
            ("missing markdown", remove(MD), checking(f"{MD} is missing")),
            ("missing model", remove(MODEL), checking(f"{MODEL} is missing")),
            ("missing security", remove(SECURITY), checking(f"{SECURITY} is missing")),
            (
                "missing title",
                replace(MD, "# Trust Model\n", ""),
                checking('trust-model.md has no "# Trust Model" heading'),
            ),
            ("missing heading", replace(MD, "## Assets\n", ""), checking('trust-model.md has no "## Assets" heading')),
            ("empty assets", model(empty("assets")), checking("assets needs at least one entry")),
            (
                "empty components",
                model(empty("components")),
                checking("components needs at least one entry")
                + checking("attacker pr-author reaches unknown component ci")
                + checking("boundary renderer-to-main is between unknown component renderer")
                + checking("boundary renderer-to-main is between unknown component main-process"),
            ),
            ("empty attackers", model(empty("attackers")), checking("attackers needs at least one entry")),
            (
                "no attacker reaches a component",
                model(lambda d: d["attackers"][0].update(reaches=[])),
                checking("at least one attacker must reach a component"),
            ),
            ("empty boundaries", model(empty("boundaries")), checking("boundaries needs at least one entry")),
            ("empty users", model(empty("users")), checking("users needs at least one entry")),
            ("missing assets", model(lambda d: d.pop("assets")), checking("assets needs at least one entry")),
            ("missing build.built", model(drop_build("built")), checking("build.built is missing")),
            ("missing build.deployed", model(drop_build("deployed")), checking("build.deployed is missing")),
            (
                "missing build.monitored",
                model(drop_build("monitored")),
                checking("build.monitored is missing"),
            ),
            (
                "missing build",
                model(lambda d: d.pop("build")),
                checking("build.built is missing")
                + checking("build.deployed is missing")
                + checking("build.monitored is missing"),
            ),
            (
                "entry without a field",
                model(lambda d: d["assets"][0].pop("loss")),
                checking("assets entry 1 has no loss"),
            ),
            (
                "unknown component",
                model(lambda d: d["attackers"][0].update(reaches=["nope"])),
                checking("attacker pr-author reaches unknown component nope"),
            ),
            ("empty accepted", model(lambda d: d.update(accepted=[])), []),
            (
                "good accepted and overrides",
                model(
                    lambda d: d.update(
                        accepted=[{"identity": CODE, "title": "t", "reason": "r", "card": "MPL-340"}],
                        overrides=[{"identity": DEPENDENCY, "severity": "low", "title": "t", "card": "MPL-340"}],
                    )
                ),
                [],
            ),
            (
                "bad accepted identity",
                model(lambda d: d.update(accepted=[{"identity": {**CODE, "hash": "xyz"}, "title": "t"}])),
                checking("accepted entry 1 has a bad identity"),
            ),
            (
                "bad override identity",
                model(lambda d: d.update(overrides=[{"identity": {"kind": "other"}, "severity": "low"}])),
                checking("overrides entry 1 has a bad identity"),
            ),
            (
                "bad tracked identity",
                security(lambda d: d.update(tracked=[{"identity": {**DEPENDENCY, "extra": 1}, "card": None}])),
                checking("tracked entry 1 has a bad identity"),
            ),
            (
                "good tracked",
                security(lambda d: d.update(tracked=[{"identity": CODE, "title": "t", "card": None}])),
                [],
            ),
            (
                "enabled yes",
                replace(SECURITY, "enabled: true", "enabled: yes"),
                checking("enabled must be true or false"),
            ),
            ("enabled false", replace(SECURITY, "enabled: true", "enabled: false"), []),
            ("model version 2", replace(MODEL, "version: 1", "version: 2"), checking("version must be 1")),
            ("security version 2", replace(SECURITY, "version: 1", "version: 2"), checking("version must be 1")),
            ("unknown security key", security(lambda d: d.update(tools=["npm-audit"])), []),
            ("bad model yaml", write(MODEL, "assets: [\n"), [Reading(MODEL)]),
            ("bad security yaml", write(SECURITY, "enabled: : true\n"), [Reading(SECURITY)]),
            ("model not a mapping", write(MODEL, "- one\n"), [Reading(MODEL)]),
            ("security not a mapping", write(SECURITY, "true\n"), [Reading(SECURITY)]),
            (
                "heading out of order",
                replace(
                    MD,
                    "## Accepted Risks\n\nNone yet.\n\n## Severity Overrides",
                    "## Severity Overrides\n\nNone yet.\n\n## Accepted Risks",
                ),
                checking('trust-model.md has "## Severity Overrides" out of order'),
            ),
            (
                "entry not a mapping",
                model(lambda d: d.update(assets=["foo"])),
                checking("assets entry 1 is not a mapping"),
            ),
            (
                "reaches not a list",
                model(lambda d: d["attackers"][0].update(reaches="ci")),
                checking("attacker pr-author reaches must be a list")
                + checking("at least one attacker must reach a component"),
            ),
            (
                "duplicate id",
                model(lambda d: d["components"].append({"id": "ci", "what": "again"})),
                checking("components has id ci more than once"),
            ),
            (
                "boundary between unknown component",
                model(lambda d: d["boundaries"][0].update(between=["renderer", "nope"])),
                checking("boundary renderer-to-main is between unknown component nope"),
            ),
            (
                "override severity",
                model(lambda d: d.update(overrides=[{"identity": CODE, "severity": "critical"}])),
                checking("overrides entry 1 needs severity high, medium, or low"),
            ),
            (
                "override without severity",
                model(lambda d: d.update(overrides=[{"identity": CODE}])),
                checking("overrides entry 1 needs severity high, medium, or low"),
            ),
            (
                "accepted entry is a string",
                model(lambda d: d.update(accepted=["MPL-340 F3"])),
                checking("accepted entry 1 has a bad identity"),
            ),
            (
                "accepted entry without identity",
                model(lambda d: d.update(accepted=[{"title": "t"}])),
                checking("accepted entry 1 has a bad identity"),
            ),
            (
                "empty dependency package",
                model(lambda d: d.update(accepted=[{"identity": {**DEPENDENCY, "package": ""}}])),
                checking("accepted entry 1 has a bad identity"),
            ),
            (
                "bad class",
                model(lambda d: d.update(accepted=[{"identity": {**CODE, "class": "Command Injection"}}])),
                checking("accepted entry 1 has a bad identity"),
            ),
            (
                "repeated heading",
                replace(MD, "## Severity Overrides\n", "## Severity Overrides\n\n## Assets\n"),
                checking('trust-model.md has "## Assets" more than once'),
            ),
            ("missing enabled", security(lambda d: d.pop("enabled")), checking("enabled must be true or false")),
        ]

        for name, change, expected in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                copy_templates(repo)
                change(repo)

                # when
                result = problems(repo)

                # then
                self.assertEqual(result, expected)


def main_case(name, args, before, code, out, err, after=(), stored=None):
    return name, args, before, list(after), stored, code, out, err


class TestMain(unittest.TestCase):
    def test_main(self):
        decided = json.dumps(findings_file(ACCEPTED))
        no_model = [remove(MD), remove(MODEL), remove(SECURITY)]
        diff = ["diff", "MPL-340", "--base", "BASE"]
        cases = [
            main_case("problems", ["check", "DIR"], [remove(MODEL), remove(SECURITY)], 1, MISSING, ""),
            main_case("no problems", ["check", "DIR"], [], 0, "", ""),
            main_case("no arguments", [], [], 2, "", USAGE),
            main_case("wrong command", ["fix", "DIR"], [], 2, "", USAGE),
            main_case("base opted in", ["base", "BASE"], [], 0, '{"optedIn": true}\n', ""),
            main_case(
                "base with enabled yes",
                ["base", "BASE"],
                [replace(SECURITY, "enabled: true", "enabled: yes")],
                0,
                '{"optedIn": false}\n',
                "",
            ),
            main_case("base with bad yaml", ["base", "BASE"], [write(MODEL, "assets: [\n")], 0, Unfiltered(), ""),
            main_case(
                "base with a model that fails the check",
                ["base", "BASE"],
                [model(empty("attackers"))],
                0,
                Unfiltered(),
                "",
            ),
            main_case(
                "base with a security file that fails the check",
                ["base", "BASE"],
                [replace(SECURITY, "version: 1", "version: 2")],
                0,
                Unfiltered(SECURITY),
                "",
            ),
            main_case("base without a sha", ["base"], [], 2, "", USAGE),
            main_case("diff with no model at base", diff, no_model, 0, "[]\n", "", after=[copy_templates]),
            main_case(
                "diff of a hand edit to attackers",
                diff,
                [],
                0,
                json.dumps([{"file": MODEL, "lines": ["-    reaches: [ci]", "+    reaches: [ci, hook-server]"]}])
                + "\n",
                "",
                after=[replace(MODEL, "reaches: [ci]", "reaches: [ci, hook-server]")],
            ),
            main_case(
                "diff of a hand edit to a model marked binary",
                diff,
                [write(".gitattributes", "*.yaml binary\n*.yaml -diff\n")],
                0,
                json.dumps([{"file": MODEL, "lines": ["-    reaches: [ci]", "+    reaches: [ci, hook-server]"]}])
                + "\n",
                "",
                after=[replace(MODEL, "reaches: [ci]", "reaches: [ci, hook-server]")],
            ),
            main_case(
                "diff after apply",
                diff,
                [],
                0,
                "[]\n",
                "",
                after=[lambda repo: trust_model.apply(repo, json.loads(decided))],
                stored=decided,
            ),
            main_case(
                "diff with an unreadable findings file",
                diff,
                [],
                1,
                "",
                "reading findings: MPL-340.json: not valid JSON\n",
                stored="{",
            ),
            main_case(
                "diff with an unknown base",
                ["diff", "MPL-340", "--base", "0" * 40],
                [],
                1,
                "",
                f"base commit {'0' * 40} is not in this repo\n",
            ),
            main_case("diff with a bad card key", ["diff", "nope", "--base", "BASE"], [], 2, "", USAGE),
            main_case("diff without a base", ["diff", "MPL-340"], [], 2, "", USAGE),
            main_case("apply", ["apply", "MPL-340"], [], 0, '{"added": 2}\n', "", stored=decided),
            main_case("apply with no findings file", ["apply", "MPL-340"], [], 0, '{"added": 0}\n', ""),
            main_case("apply with a bad card key", ["apply", "mpl"], [], 2, "", USAGE),
        ]

        for name, args, before, after, stored, code, out, err in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as store:
                # given
                repo = Path(directory)
                copy_templates(repo)
                for change in before:
                    change(repo)
                base = commit_files(directory, {})
                for change in after:
                    change(repo)
                if stored is not None:
                    (Path(store) / "MPL-340.json").write_text(stored)
                argv = ["trust_model.py", *[{"DIR": directory, "BASE": base}.get(arg, arg) for arg in args]]
                stdout, stderr = io.StringIO(), io.StringIO()

                # when
                with (
                    contextlib.chdir(directory),
                    mock.patch.dict(os.environ, {"MAPLE_FINDINGS_DIR": store}),
                    mock.patch("sys.argv", argv),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    trust_model.main()

                # then
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(stdout.getvalue(), out)
                self.assertEqual(stderr.getvalue(), err)


class TestOptedIn(unittest.TestCase):
    def test_opted_in(self):
        cases = [
            ("both files with enabled true", {"version": 1}, {"enabled": True}, True),
            ("enabled false", {"version": 1}, {"enabled": False}, False),
            ("enabled text", {"version": 1}, {"enabled": "true"}, False),
            ("no model", None, {"enabled": True}, False),
            ("no security file", {"version": 1}, None, False),
        ]

        for name, model_data, security_data, want in cases:
            with self.subTest(name):
                # given
                # when
                got = trust_model.opted_in(model_data, security_data)

                # then
                self.assertEqual(got, want)


class TestAtBase(unittest.TestCase):
    def test_at_base(self):
        model_text = (TEMPLATES / "trust-model.yaml").read_text()
        security_text = (TEMPLATES / "security.yaml").read_text()
        model_data = yaml.safe_load(model_text)
        security_data = yaml.safe_load(security_text)
        cases = [
            (
                "reads both files",
                {MODEL: model_text, SECURITY: security_text},
                None,
                REAL_RUN,
                (model_data, security_data),
                None,
            ),
            ("missing model is None", {SECURITY: security_text}, None, REAL_RUN, (None, security_data), None),
            ("missing security is None", {MODEL: model_text}, None, REAL_RUN, (model_data, None), None),
            ("neither file", {}, None, REAL_RUN, (None, None), None),
            ("enabled yes stays text", {SECURITY: "enabled: yes\n"}, None, REAL_RUN, (None, {"enabled": "yes"}), None),
            ("bad model yaml", {MODEL: "assets: [\n"}, None, REAL_RUN, None, f"{MODEL}: "),
            ("security not a mapping", {SECURITY: "true\n"}, None, REAL_RUN, None, f"{SECURITY}: "),
            ("unknown base commit", {}, "0" * 40, REAL_RUN, None, "base commit "),
            ("git show times out", {}, None, slow_show, None, f"{MODEL}: git show timed"),
            ("git missing", {}, "0" * 40, no_git, None, f"base commit {'0' * 40}: running git: "),
        ]

        for name, files, base_override, run, want, want_error in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                base = base_override or commit_files(directory, files)
                (Path(directory) / SECURITY).parent.mkdir(parents=True, exist_ok=True)
                (Path(directory) / SECURITY).write_text("version: 1\nenabled: false\n")
                got = None
                error = None

                # when
                with contextlib.chdir(directory), mock.patch.object(trust_model.subprocess, "run", side_effect=run):
                    try:
                        got = trust_model.at_base(base)
                    except ValueError as raised:
                        error = str(raised)

                # then
                self.assertEqual(got, want)
                if want_error is None:
                    self.assertIsNone(error)
                else:
                    self.assertTrue(error and error.startswith(want_error) and len(error) > len(want_error), error)


def issue(severity="high", code='eval "$1"', title="Shell runs input"):
    return {
        "severity": severity,
        "identity": {"kind": "code", "class": "command-injection", "file": "run.sh", "code": code},
        "line": 3,
        "sources": ["security-pass"],
        "title": title,
        "what": "w",
        "how": "h",
        "impact": "i",
        "defense": "d",
        "chips": ["runs-code"],
    }


DEPENDENCY_INPUT = {"kind": "dependency", "advisory": "GHSA-35jh-r3h4-6jhm", "package": "lodash"}


DEPENDENCY_LINE = "  - " + json.dumps({"identity": DEPENDENCY, "title": "Shell runs input", "card": None})


def fail(*args, **kwargs):
    raise OSError(28, "No space left on device")


def tracked_line(code='eval "$1"', title="Shell runs input"):
    identity = {"kind": "code", "class": "command-injection", "file": "run.sh", "hash": code_hash(code)}
    return "  - " + json.dumps({"identity": identity, "title": title, "card": None})


def printed(severity="high", title="Shell runs input"):
    return {
        "title": title,
        "severity": severity,
        "file": "run.sh",
        "line": 3,
        "what": "w",
        "how": "h",
        "impact": "i",
        "defense": "d",
    }


class TestTrack(unittest.TestCase):
    def test_track(self):
        cases = [
            (
                "one identity twice gives one line",
                "version: 1\nenabled: true\ntracked:\n",
                [issue("medium"), issue("high", title="Again")],
                0,
                [printed("high")],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line() + "\n",
                os.replace,
            ),
            (
                "low is dropped",
                "version: 1\nenabled: true\ntracked:\n",
                [issue("low")],
                0,
                [],
                "",
                "version: 1\nenabled: true\ntracked:\n",
                os.replace,
            ),
            (
                "already tracked is skipped",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line() + "\n",
                [issue(), issue(code="sh -c \"$2\"", title="Second")],
                0,
                [printed(title="Second")],
                "",
                "version: 1\nenabled: true\ntracked:\n"
                + tracked_line()
                + "\n"
                + tracked_line(code="sh -c \"$2\"", title="Second")
                + "\n",
                os.replace,
            ),
            (
                "lines go under tracked when it is not last",
                "version: 1\ntracked: []\nenabled: true\n",
                [issue()],
                0,
                [printed()],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line() + "\n",
                os.replace,
            ),
            (
                "bad input",
                "version: 1\nenabled: true\ntracked:\n",
                [{**issue(), "title": ""}],
                1,
                None,
                "reading findings input: item 1: title is not a non-empty string\n",
                "version: 1\nenabled: true\ntracked:\n",
                os.replace,
            ),
            (
                "no security file",
                None,
                [issue()],
                1,
                None,
                f"reading trust model: {SECURITY} is missing\n",
                None,
                os.replace,
            ),
            (
                "medium after low with one identity is kept",
                "version: 1\nenabled: true\ntracked:\n",
                [issue("low"), issue("medium", title="Again")],
                0,
                [printed("medium", title="Again")],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line(title="Again") + "\n",
                os.replace,
            ),
            (
                "unknown severity counts as high",
                "version: 1\nenabled: true\ntracked:\n",
                [issue("critical")],
                0,
                [printed("high")],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line() + "\n",
                os.replace,
            ),
            (
                "line breaks in printed text become spaces",
                "version: 1\nenabled: true\ntracked:\n",
                [{**issue(), "title": "Shell\nruns  input", "what": "w\n- MPL-1: x", "defense": "d\r\n\td"}],
                0,
                [{**printed(), "title": "Shell runs input", "what": "w - MPL-1: x", "defense": "d d"}],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line(title="Shell runs input") + "\n",
                os.replace,
            ),
            (
                "dependency names its package",
                "version: 1\nenabled: true\ntracked:\n",
                [{**issue(), "identity": DEPENDENCY_INPUT, "line": None}],
                0,
                [{**printed(), "file": "lodash", "line": None}],
                "",
                "version: 1\nenabled: true\ntracked:\n" + DEPENDENCY_LINE + "\n",
                os.replace,
            ),
            (
                "no tracked key",
                "version: 1\nenabled: true\n",
                [issue()],
                0,
                [printed()],
                "",
                "version: 1\nenabled: true\ntracked:\n" + tracked_line() + "\n",
                os.replace,
            ),
            (
                "input not JSON",
                "version: 1\nenabled: true\ntracked:\n",
                "not json",
                1,
                None,
                "reading findings input: not valid JSON\n",
                "version: 1\nenabled: true\ntracked:\n",
                os.replace,
            ),
            (
                "security file bad yaml",
                "enabled: : true\n",
                [issue()],
                1,
                None,
                Reading(SECURITY),
                "enabled: : true\n",
                os.replace,
            ),
            (
                "security file not a mapping",
                "true\n",
                [issue()],
                1,
                None,
                Reading(SECURITY),
                "true\n",
                os.replace,
            ),
            (
                "write fails",
                "version: 1\nenabled: true\ntracked:\n",
                [issue()],
                1,
                None,
                f"writing trust model: {SECURITY}: No space left on device\n",
                "version: 1\nenabled: true\ntracked:\n",
                fail,
            ),
        ]

        for name, before, inputs, code, out, err, after, replace_file in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                if before is not None:
                    (repo / SECURITY).parent.mkdir(parents=True)
                    (repo / SECURITY).write_text(before)
                stdout, stderr = io.StringIO(), io.StringIO()
                argv = ["trust_model.py", "track", directory]
                stdin = inputs if isinstance(inputs, str) else json.dumps(inputs)

                # when
                with (
                    mock.patch("sys.argv", argv),
                    mock.patch("sys.stdin", io.StringIO(stdin)),
                    mock.patch.object(trust_model.os, "replace", side_effect=replace_file),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    trust_model.main()

                # then
                self.assertEqual(raised.exception.code, code)
                if out is None:
                    self.assertEqual(stdout.getvalue(), "")
                else:
                    self.assertEqual(json.loads(stdout.getvalue()), out)
                self.assertEqual(stderr.getvalue().rstrip("\n") if isinstance(err, Reading) else stderr.getvalue(), err)
                if after is not None:
                    self.assertEqual((repo / SECURITY).read_text(), after)
                    names = sorted(path.name for path in (repo / SECURITY).parent.iterdir())
                    self.assertEqual(names, ["security.yaml"])


DECIDED_AT = "2026-11-11T18:00:00+00:00"
ACCEPTED_LINE = (
    '  - {"identity": {"kind": "code", "class": "command-injection", "file": "api/run.go", '
    '"hash": "0123456789abcdef"}, '
    '"title": "Branch names reach a shell", "reason": "local only", "card": "MPL-340", "finding": "F1", '
    '"at": "2026-11-11"}'
)
ACCEPTED_BULLET = "- Branch names reach a shell (MPL-340 F1): local only"
OVERRIDE_LINE = (
    '  - {"identity": {"kind": "code", "class": "command-injection", "file": "api/run.go", '
    '"hash": "0123456789abcdef"}, '
    '"severity": "low", "title": "Branch names reach a shell", "card": "MPL-340", "finding": "F1", "at": "2026-11-11"}'
)
OVERRIDE_BULLET = "- Branch names reach a shell (MPL-340 F1): low"
TRACKED_LINE = (
    '  - {"identity": {"kind": "code", "class": "command-injection", "file": "api/run.go", '
    '"hash": "0123456789abcdef"}, '
    '"title": "Branch names reach a shell", "card": "MPL-400"}'
)
ACCEPTED_KEY = f"{MODEL}:accepted"
OVERRIDES_KEY = f"{MODEL}:overrides"
TRACKED_KEY = f"{SECURITY}:tracked"
ACCEPTED_HEADING = f"{MD}:## Accepted Risks"
OVERRIDES_HEADING = f"{MD}:## Severity Overrides"


def decision(kind, reason=None):
    return {"kind": kind, "reason": reason, "decidedAt": DECIDED_AT}


def finding(**changes):
    base = {
        "id": "F1",
        "identity": CODE,
        "title": "Branch names reach a shell",
        "severity": "high",
        "applied": None,
        "decision": None,
        "severityOverride": None,
    }
    return {**base, **changes}


def findings_file(*found):
    return {"version": 1, "round": 1, "card": "MPL-340", "findings": list(found)}


ACCEPTED = finding(decision=decision("accept-risk", "local only"))
OVERRIDDEN = finding(decision=decision("fix-now"), severityOverride="low")
TRACKED = finding(
    decision=decision("fix-later"),
    applied={"at": DECIDED_AT, "commit": None, "cardKey": "MPL-400"},
)


class TestEntryLines(unittest.TestCase):
    def test_entry_lines(self):
        model_class = {**CODE, "class": "trust-model-change"}
        update_class = {**CODE, "class": "trust-model-update"}
        cases = [
            ("accept risk", ACCEPTED, {ACCEPTED_KEY: [ACCEPTED_LINE], ACCEPTED_HEADING: [ACCEPTED_BULLET]}),
            ("severity override", OVERRIDDEN, {OVERRIDES_KEY: [OVERRIDE_LINE], OVERRIDES_HEADING: [OVERRIDE_BULLET]}),
            ("fix later with a card", TRACKED, {TRACKED_KEY: [TRACKED_LINE]}),
            ("fix later without a card", finding(decision=decision("fix-later")), {}),
            ("undecided", finding(severityOverride="low"), {}),
            ("not real", finding(decision=decision("not-real", "test code")), {}),
            ("fix now", finding(decision=decision("fix-now")), {}),
            (
                "accept risk with a multi-line reason",
                finding(decision=decision("accept-risk", "local\n only")),
                {
                    ACCEPTED_KEY: [ACCEPTED_LINE.replace("local only", "local\\n only")],
                    ACCEPTED_HEADING: [ACCEPTED_BULLET],
                },
            ),
            (
                "accept risk without a reason",
                finding(decision=decision("accept-risk")),
                {
                    ACCEPTED_KEY: [ACCEPTED_LINE.replace('"local only"', "null")],
                    ACCEPTED_HEADING: [ACCEPTED_BULLET.replace("local only", "none")],
                },
            ),
            (
                "multi-line title",
                finding(title="Branch names\n reach a shell", decision=decision("accept-risk", "local only")),
                {
                    ACCEPTED_KEY: [ACCEPTED_LINE.replace("Branch names reach", "Branch names\\n reach")],
                    ACCEPTED_HEADING: [ACCEPTED_BULLET],
                },
            ),
            (
                "multi-line title overridden",
                finding(title="Branch names\n reach a shell", decision=decision("fix-now"), severityOverride="low"),
                {
                    OVERRIDES_KEY: [OVERRIDE_LINE.replace("Branch names reach", "Branch names\\n reach")],
                    OVERRIDES_HEADING: [OVERRIDE_BULLET],
                },
            ),
            ("model change accepted", finding(identity=model_class, decision=decision("accept-risk", "ok")), {}),
            (
                "model update overridden",
                finding(identity=update_class, decision=decision("fix-now"), severityOverride="low"),
                {},
            ),
        ]

        for name, found, want in cases:
            with self.subTest(name):
                # given
                data = findings_file(found)

                # when
                got = trust_model.entry_lines(data)

                # then
                self.assertEqual(got, want)


class TestApply(unittest.TestCase):
    def test_apply(self):
        all_three = findings_file(ACCEPTED, {**OVERRIDDEN, "id": "F2"}, {**TRACKED, "id": "F3"})
        cases = [
            (
                "lines land under their key and heading",
                [],
                1,
                all_three,
                5,
                {
                    MODEL: [f"accepted:\n{ACCEPTED_LINE}\noverrides:\n{OVERRIDE_LINE.replace('F1', 'F2')}\n"],
                    SECURITY: [f"tracked:\n{TRACKED_LINE}\n"],
                    MD: [
                        f"## Accepted Risks\n\nNone yet.\n{ACCEPTED_BULLET}\n\n## Severity Overrides",
                        f"## Severity Overrides\n\nNone yet.\n{OVERRIDE_BULLET.replace('F1', 'F2')}\n",
                    ],
                },
            ),
            ("a second run adds nothing", [], 2, all_three, 0, {MODEL: [ACCEPTED_LINE]}),
            ("no model writes nothing", [remove(MODEL)], 1, all_three, 0, {}),
            ("nothing decided", [], 1, findings_file(finding()), 0, {}),
            (
                "an empty inline list becomes a block list",
                [replace(MODEL, "accepted:\n", "accepted: []\n")],
                1,
                findings_file(ACCEPTED),
                2,
                {MODEL: [f"accepted:\n{ACCEPTED_LINE}\noverrides:\n"]},
            ),
            (
                "a filled inline list stops with an error",
                [replace(MODEL, "accepted:\n", 'accepted: [{"title": "kept"}]\n')],
                1,
                findings_file(ACCEPTED),
                f"writing trust model: {MODEL}: accepted is an inline list",
                {},
            ),
            (
                "an error writes no file",
                [replace(MODEL, "overrides:\n", 'overrides: [{"title": "kept"}]\n')],
                1,
                all_three,
                f"writing trust model: {MODEL}: overrides is an inline list",
                {},
            ),
            (
                "new lines go after existing entries",
                [lambda repo: trust_model.apply(repo, findings_file(ACCEPTED))],
                1,
                findings_file({**ACCEPTED, "id": "F5"}),
                2,
                {
                    MODEL: [f"accepted:\n{ACCEPTED_LINE}\n{ACCEPTED_LINE.replace('F1', 'F5')}\noverrides:\n"],
                    MD: [
                        f"None yet.\n{ACCEPTED_BULLET}\n{ACCEPTED_BULLET.replace('F1', 'F5')}\n\n## Severity Overrides",
                    ],
                },
            ),
        ]

        for name, changes, runs, data, want, contains in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                copy_templates(repo)
                for change in changes:
                    change(repo)
                for _ in range(runs - 1):
                    trust_model.apply(repo, data)
                before = {rel: (repo / rel).read_text() for rel in (MD, MODEL, SECURITY) if (repo / rel).exists()}

                # when
                try:
                    got = trust_model.apply(repo, data)
                except ValueError as error:
                    got = str(error)

                # then
                self.assertEqual(got, want)
                after = {rel: (repo / rel).read_text() for rel in before}
                for rel, parts in contains.items():
                    for part in parts:
                        self.assertIn(part, after[rel])
                if want == 0 or isinstance(want, str):
                    self.assertEqual(after, before)
                if (repo / MODEL).exists() and not isinstance(want, str):
                    self.assertEqual(problems(repo), [])


DIFF_HEADER = f"diff --git a/{MODEL} b/{MODEL}\nindex 1111111..2222222 100644\n--- a/{MODEL}\n+++ b/{MODEL}\n"


class TestUnexplained(unittest.TestCase):
    def test_unexplained(self):
        cases = [
            ("an expected added line is left out", f"{DIFF_HEADER}@@ -30,0 +31 @@ accepted:\n+{ACCEPTED_LINE}\n", []),
            (
                "a removed line is kept",
                f"{DIFF_HEADER}@@ -20 +19,0 @@ attackers:\n-    reaches: [ci]\n",
                [{"file": MODEL, "lines": ["-    reaches: [ci]"]}],
            ),
            (
                "another added line is kept",
                f"{DIFF_HEADER}@@ -30,0 +31,2 @@ accepted:\n+{ACCEPTED_LINE}\n+  - {{\"title\": \"x\"}}\n",
                [{"file": MODEL, "lines": ['+  - {"title": "x"}']}],
            ),
            (
                "a removed line that looks like a header is kept",
                f"{DIFF_HEADER}@@ -40 +39,0 @@\n--- a/x\n",
                [{"file": MODEL, "lines": ["--- a/x"]}],
            ),
            (
                "other files are ignored",
                "diff --git a/api/run.go b/api/run.go\n--- a/api/run.go\n+++ b/api/run.go\n@@ -1 +1 @@\n-a\n+b\n",
                [],
            ),
            (
                "a deleted model file is kept",
                f"diff --git a/{SECURITY} b/{SECURITY}\ndeleted file mode 100644\n--- a/{SECURITY}\n+++ /dev/null\n"
                "@@ -1,2 +0,0 @@\n-version: 1\n-enabled: true\n",
                [{"file": SECURITY, "lines": ["-version: 1", "-enabled: true"]}],
            ),
        ]

        for name, diff_text, want in cases:
            with self.subTest(name):
                # given
                expected = {ACCEPTED_LINE}

                # when
                got = trust_model.unexplained(diff_text, expected)

                # then
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
