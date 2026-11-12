import contextlib
import io
import shutil
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
USAGE = "usage: trust_model.py check DIR\n"


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


def checking(text):
    return [f"checking trust model: {text}"]


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
                + checking("attacker pr-author reaches unknown component ci"),
            ),
            ("empty attackers", model(empty("attackers")), checking("attackers needs at least one entry")),
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

    def test_problems_bad_yaml(self):
        cases = [
            ("model", MODEL, "assets: [\n"),
            ("security", SECURITY, "enabled: : true\n"),
            ("model not a mapping", MODEL, "- one\n"),
        ]

        for name, rel, text in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                copy_templates(repo)
                (repo / rel).write_text(text)

                # when
                result = problems(repo)

                # then
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0].startswith(f"reading trust model: {rel}: "), result[0])
                self.assertNotIn("\n", result[0])


class TestMain(unittest.TestCase):
    def test_main(self):
        cases = [
            ("problems", ["check", "DIR"], [remove(MODEL), remove(SECURITY)], 1, ""),
            ("no problems", ["check", "DIR"], [], 0, ""),
            ("no arguments", [], [], 2, USAGE),
            ("wrong command", ["fix", "DIR"], [], 2, USAGE),
        ]

        for name, args, changes, code, err in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                # given
                repo = Path(directory)
                copy_templates(repo)
                for change in changes:
                    change(repo)
                argv = ["trust_model.py", *[directory if arg == "DIR" else arg for arg in args]]
                stdout, stderr = io.StringIO(), io.StringIO()

                # when
                with (
                    mock.patch("sys.argv", argv),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    trust_model.main()

                # then
                self.assertEqual(raised.exception.code, code)
                if name == "problems":
                    self.assertEqual(
                        stdout.getvalue(),
                        f"checking trust model: {MODEL} is missing\nchecking trust model: {SECURITY} is missing\n",
                    )
                else:
                    self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), err)


if __name__ == "__main__":
    unittest.main()
