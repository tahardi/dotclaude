import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

import trust_model
from trust_model import problems

TEMPLATES = Path(__file__).parent.parent / "trust-model"
MD = "docs/security/trust-model.md"
MODEL = ".maple/trust-model.yaml"
SECURITY = ".maple/security.yaml"
CODE = {"kind": "code", "class": "command-injection", "file": "api/run.go", "hash": "0123456789abcdef"}
DEPENDENCY = {"kind": "dependency", "advisory": "GHSA-35jh-r3h4-6jhm", "package": "lodash"}
USAGE = "usage: trust_model.py check DIR | base SHA\n"
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


class TestMain(unittest.TestCase):
    def test_main(self):
        cases = [
            ("problems", ["check", "DIR"], [remove(MODEL), remove(SECURITY)], 1, MISSING, ""),
            ("no problems", ["check", "DIR"], [], 0, "", ""),
            ("no arguments", [], [], 2, "", USAGE),
            ("wrong command", ["fix", "DIR"], [], 2, "", USAGE),
            ("base opted in", ["base", "BASE"], [], 0, '{"optedIn": true}\n', ""),
            (
                "base with enabled yes",
                ["base", "BASE"],
                [replace(SECURITY, "enabled: true", "enabled: yes")],
                0,
                '{"optedIn": false}\n',
                "",
            ),
            (
                "base with bad yaml",
                ["base", "BASE"],
                [write(MODEL, "assets: [\n")],
                0,
                Unfiltered(),
                "",
            ),
            ("base with a model that fails the check", ["base", "BASE"], [model(empty("attackers"))], 0, Unfiltered(), ""),
            (
                "base with a security file that fails the check",
                ["base", "BASE"],
                [replace(SECURITY, "version: 1", "version: 2")],
                0,
                Unfiltered(SECURITY),
                "",
            ),
            ("base without a sha", ["base"], [], 2, "", USAGE),
        ]

        for name, args, changes, code, out, err in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                copy_templates(repo)
                for change in changes:
                    change(repo)
                base = commit_files(directory, {})
                argv = ["trust_model.py", *[{"DIR": directory, "BASE": base}.get(arg, arg) for arg in args]]
                stdout, stderr = io.StringIO(), io.StringIO()

                # when
                with (
                    contextlib.chdir(directory),
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


if __name__ == "__main__":
    unittest.main()
