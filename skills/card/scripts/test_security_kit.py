import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

KIT = Path(__file__).parent.parent / "security-kit"
REPO = Path(__file__).parents[3]
TOOLS = {
    "gitleaks": r"gitleaks",
    "actionlint": r"actionlint",
    "zizmor": r"zizmor",
    "osv-scanner": r"osv-scanner",
    "govulncheck": r"govulncheck",
    "npm audit": r"npm audit(?! signatures)",
    "npm audit signatures": r"npm audit signatures",
}
BASE = {"gitleaks", "actionlint", "zizmor", "osv-scanner"}
PACKAGE_JSON = '{"name": "x", "version": "1.0.0", "dependencies": {"lodash": "%s"}}'
DEV_PACKAGE_JSON = '{"name": "x", "version": "1.0.0", "devDependencies": {"lodash": "%s"}}'
NPM = {"package.json": PACKAGE_JSON % "1.0.0", "package-lock.json": "{}"}


def fake_bin(root, **exits):
    bin_dir = root / "fake-bin"
    bin_dir.mkdir()
    for name, code in exits.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\nexit {code}\n")
        path.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


class KitTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        shutil.copy(KIT / "security.mk", self.repo / "security.mk")

    def write(self, files):
        for name, text in files.items():
            (self.repo / name).write_text(text)

    def make(self, *args, env=None):
        return subprocess.run(
            ["make", "--no-print-directory", "-f", "security.mk", *args],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
        )


class TestSecurityMk(KitTestCase):
    def test_targets(self):
        cases = [
            ("empty dir", {}, BASE),
            ("go", {"go.mod": "module x\n"}, BASE | {"govulncheck"}),
            (
                "npm",
                {"package.json": PACKAGE_JSON % "1.0.0", "package-lock.json": "{}"},
                BASE | {"npm audit", "npm audit signatures"},
            ),
            ("rust", {"Cargo.lock": ""}, BASE),
            ("python", {"requirements.txt": "requests==2.32.0\n"}, BASE),
        ]
        for name, files, want in cases:
            with self.subTest(name):
                # given
                self.setUp()
                self.write(files)

                # when
                result = self.make("-n", "security")

                # then
                self.assertEqual(result.returncode, 0, result.stderr)
                got = {tool for tool, pattern in TOOLS.items() if re.search(pattern, result.stdout)}
                self.assertEqual(got, want)

    def test_offline(self):
        cases = [
            ("deps in empty dir", {}, "security-deps", ["osv-scanner"]),
            (
                "everything",
                {"go.mod": "module x\n", **NPM},
                "security",
                ["gitleaks", "actionlint", "zizmor", "npm audit signatures", "osv-scanner", "govulncheck", "npm audit"],
            ),
        ]
        for name, files, target, tools in cases:
            with self.subTest(name):
                # given
                self.setUp()
                self.write(files)
                env = fake_bin(self.repo, curl=7)

                # when
                result = self.make(target, env=env)

                # then
                self.assertEqual(result.returncode, 0, result.stderr)
                for tool in tools:
                    self.assertIn(f"warning: skipping {tool}: cannot reach", result.stdout)

    def test_tool_failure(self):
        cases = [
            ("secrets gate", "security-secrets", False, []),
            ("workflows gate", "security-workflows", False, []),
            (
                "deps report",
                "security-deps",
                True,
                [
                    "warning: osv-scanner failed: exit 3",
                    "osv-scanner results: security-results/osv-scanner.json",
                    "warning: govulncheck failed: exit 3",
                    "govulncheck results: security-results/govulncheck.json",
                    "warning: npm audit failed: exit 3",
                    "npm audit results: security-results/npm-audit.json",
                ],
            ),
        ]
        for name, target, passes, lines in cases:
            with self.subTest(name):
                # given
                self.setUp()
                self.write({"go.mod": "module x\n", **NPM})
                env = fake_bin(self.repo, curl=0, go=3, npm=3, uvx=3)

                # when
                result = self.make(target, env=env)

                # then
                self.assertEqual(result.returncode == 0, passes, result.stdout + result.stderr)
                for line in lines:
                    self.assertIn(line, result.stdout)

    def test_pins(self):
        cases = [
            ("npm caret", {"package.json": PACKAGE_JSON % "^1.0.0", "package-lock.json": "{}"}, False),
            ("npm exact", NPM, True),
            ("npm dev caret", {"package.json": DEV_PACKAGE_JSON % "^1.0.0", "package-lock.json": "{}"}, False),
            ("npm without lockfile", {"package.json": PACKAGE_JSON % "1.0.0"}, False),
            ("requirements range", {"requirements.txt": "requests>=2\n"}, False),
            ("requirements exact", {"requirements.txt": "# deps\nrequests==2.32.0\n"}, True),
            ("requirements dev range", {"requirements-dev.txt": "pytest~=8.0\n"}, False),
            (
                "requirements options",
                {"requirements.txt": "-r base.txt\n\nrequests==2.32.0 \\\n    --hash=sha256:abc\n"},
                True,
            ),
            ("cargo without lockfile", {"Cargo.toml": "[package]\n"}, False),
            ("cargo with lockfile", {"Cargo.toml": "[package]\n", "Cargo.lock": ""}, True),
        ]
        for name, files, passes in cases:
            with self.subTest(name):
                # given
                self.setUp()
                self.write(files)
                env = fake_bin(self.repo, curl=0, npm=0)

                # when
                result = self.make("security-pins", env=env)

                # then
                self.assertEqual(result.returncode == 0, passes, result.stdout + result.stderr)


class TestSecurityWorkflow(unittest.TestCase):
    def test_workflow(self):
        # given
        text = (KIT / "security.yml").read_text()

        # when
        workflow = yaml.safe_load(text)

        # then
        uses = re.findall(r"uses:\s*(\S+)", text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        uploads = [s for s in workflow["jobs"]["fast"]["steps"] if "upload-artifact" in s.get("uses", "")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["with"]["name"], "security-fast")
        self.assertEqual(uploads[0]["if"], "always()")



class TestInstalledKit(unittest.TestCase):
    def test_installed_matches_kit(self):
        cases = [
            ("security.mk", REPO / "security.mk"),
            ("security.yml", REPO / ".github" / "workflows" / "security.yml"),
        ]
        for name, installed in cases:
            with self.subTest(name):
                # given
                source = KIT / name

                # when
                same = installed.read_bytes() == source.read_bytes()

                # then
                self.assertTrue(same, f"{installed} differs from {source}; copy the kit again")


if __name__ == "__main__":
    unittest.main()
