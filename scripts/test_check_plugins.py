import contextlib
import copy
import io
import json
import os
import tempfile
import unittest

import yaml

from check_plugins import (
    check,
    check_warnings,
    load_allowlist,
    load_installed,
    load_marketplaces,
    load_mcp_servers,
    main,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

ALLOWLIST = {
    "version": 1,
    "plugins": [
        {
            "name": "alpha@market-a",
            "source": "github:example/market-a",
            "version": "1.0.0",
            "commit": SHA_A,
            "hosts": [],
            "disabled_features": [],
        },
        {
            "name": "beta@market-b",
            "source": "github:example/market-b",
            "version": "2.0.0",
            "hosts": [],
            "disabled_features": [],
        },
    ],
    "mcp_servers": [
        {"name": "notes", "scope": "desktop", "command": ["/usr/bin/notes"], "hosts": []},
        {"name": "docs", "scope": "desktop", "url": "https://docs.example.com/mcp", "hosts": []},
    ],
}

INSTALLED = {
    "version": 2,
    "plugins": {
        "alpha@market-a": [{"scope": "user", "installPath": "/x/alpha", "version": "1.0.0", "gitCommitSha": SHA_A}],
        "beta@market-b": [{"scope": "user", "installPath": "/x/beta", "version": "2.0.0", "gitCommitSha": SHA_B}],
    },
}

MARKETPLACES = {
    "market-a": {"source": {"source": "github", "repo": "example/market-a"}},
    "market-b": {"source": {"source": "github", "repo": "example/market-b"}},
}

CLAUDE_JSON = {
    "mcpServers": {"notes": {"type": "stdio", "command": "/usr/bin/notes", "args": []}},
    "projects": {"/x": {"mcpServers": {"docs": {"type": "http", "url": "https://docs.example.com/mcp"}}}},
}

SYNC_FEATURE = {
    "name": "cloud-sync",
    "hosts": ["sync.example.com"],
    "file": "~/.alpha/settings.json",
    "key": "SYNC_TOKEN",
    "want": "",
}

DENY_FEATURE = {
    "name": "cloud-skills",
    "hosts": ["gateway.example.com"],
    "file": "$SETTINGS",
    "key": "permissions.deny",
    "contains": ["Skill(alpha:cloud)", "Skill(alpha:gateway)"],
}

TRACK_FEATURE = {
    "name": "telemetry",
    "hosts": ["telemetry.example.com"],
    "file": "$SETTINGS",
    "key": "env.DO_NOT_TRACK",
    "want": "1",
}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.allowlist = copy.deepcopy(ALLOWLIST)
        self.installed = copy.deepcopy(INSTALLED)
        self.marketplaces = copy.deepcopy(MARKETPLACES)
        self.claude_json = copy.deepcopy(CLAUDE_JSON)
        self.managed_mcp = None
        self.settings = {"env": {}, "permissions": {"deny": []}}
        self.home_files = {}

        self.home = os.path.join(root, "home")
        self.allowlist_path = os.path.join(root, "plugins.yaml")
        self.installed_path = os.path.join(root, "installed_plugins.json")
        self.marketplaces_path = os.path.join(root, "known_marketplaces.json")
        self.claude_json_path = os.path.join(root, ".claude.json")
        self.managed_mcp_path = os.path.join(root, "managed-mcp.json")
        self.settings_path = os.path.join(root, "settings.json")

    def write(self):
        os.makedirs(self.home, exist_ok=True)

        with open(self.allowlist_path, "w") as f:
            yaml.safe_dump(self.allowlist, f)
        write_json(self.installed_path, self.installed)
        write_json(self.marketplaces_path, self.marketplaces)
        write_json(self.claude_json_path, self.claude_json)
        write_json(self.settings_path, self.settings)
        if self.managed_mcp is not None:
            write_json(self.managed_mcp_path, self.managed_mcp)
        for rel, data in self.home_files.items():
            write_json(os.path.join(self.home, rel), data)

    def run_check(self, scope="desktop"):
        self.write()
        managed = self.managed_mcp_path if self.managed_mcp is not None else None
        return check(
            load_allowlist(self.allowlist_path),
            load_installed(self.installed_path),
            load_marketplaces(self.marketplaces_path),
            load_mcp_servers(self.claude_json_path, managed),
            self.settings_path,
            self.home,
            scope,
        )

    def argv(self, scope="vm"):
        self.write()
        return [
            "--allowlist", self.allowlist_path,
            "--scope", scope,
            "--installed", self.installed_path,
            "--marketplaces", self.marketplaces_path,
            "--settings", self.settings_path,
            "--claude-json", self.claude_json_path,
            "--managed-mcp", self.managed_mcp_path,
            "--home", self.home,
        ]


def alpha(f):
    return f.allowlist["plugins"][0]


def unlisted_plugin(f):
    f.installed["plugins"]["gamma@market-a"] = [{"scope": "user", "version": "1.0.0", "gitCommitSha": SHA_C}]


def missing_plugin(f):
    del f.installed["plugins"]["beta@market-b"]


def version_drift(f):
    f.installed["plugins"]["alpha@market-a"][0]["version"] = "1.1.0"


def commit_drift(f):
    f.installed["plugins"]["alpha@market-a"][0]["gitCommitSha"] = SHA_C


def two_install_scopes(f):
    f.installed["plugins"]["alpha@market-a"].append(
        {"scope": "project", "projectPath": "/x", "version": "1.2.0", "gitCommitSha": SHA_A},
    )


def marketplace_swapped(f):
    f.marketplaces["market-a"]["source"]["repo"] = "evil/market-a"


def feature_on_want(f):
    alpha(f)["disabled_features"] = [SYNC_FEATURE]
    f.home_files[".alpha/settings.json"] = {"SYNC_TOKEN": "made-up"}


def feature_off_key_missing(f):
    alpha(f)["disabled_features"] = [SYNC_FEATURE]
    f.home_files[".alpha/settings.json"] = {"OTHER": "x"}


def feature_off_file_missing(f):
    alpha(f)["disabled_features"] = [SYNC_FEATURE]


def feature_on_file_missing(f):
    alpha(f)["disabled_features"] = [dict(SYNC_FEATURE, want="1")]


def feature_on_contains(f):
    alpha(f)["disabled_features"] = [DENY_FEATURE]
    f.settings["permissions"]["deny"] = ["Skill(alpha:cloud)"]


def feature_dotted_env_key(f):
    alpha(f)["disabled_features"] = [TRACK_FEATURE]
    f.settings["env"]["DO_NOT_TRACK"] = "1"


def feature_want_number(f):
    alpha(f)["disabled_features"] = [dict(TRACK_FEATURE, want=1)]
    f.settings["env"]["DO_NOT_TRACK"] = "1"


def marketplace_missing(f):
    del f.marketplaces["market-a"]


def two_drift_kinds(f):
    version_drift(f)
    unlisted_mcp(f)


def mcp_args_drift(f):
    f.claude_json["mcpServers"]["notes"]["args"] = ["--token", "made-up"]


def mcp_url_drift(f):
    f.claude_json["projects"]["/x"]["mcpServers"]["docs"]["url"] = "https://evil.example.com/mcp?key=made-up"


def unlisted_mcp(f):
    del f.allowlist["mcp_servers"][1]


def mcp_command_drift(f):
    f.claude_json["mcpServers"]["notes"]["command"] = "/tmp/notes"


def mcp_scope(f):
    f.managed_mcp = {"mcpServers": {"notes": {"type": "stdio", "command": "/usr/bin/notes", "args": []}}}
    f.claude_json = {}


def unlisted_marketplace(f):
    f.marketplaces["market-c"] = {"source": {"source": "github", "repo": "example/market-c"}}


def mcp_home_variable(f):
    f.allowlist["mcp_servers"][0]["command"] = ["$HOME/bin/notes", "--home", "$HOME"]
    f.claude_json["mcpServers"]["notes"] = {"command": f"{f.home}/bin/notes", "args": ["--home", f.home]}


class TestCheck(unittest.TestCase):
    def test_check(self):
        cases = [
            ("clean", None, "desktop", []),
            (
                "unlisted plugin",
                unlisted_plugin,
                "desktop",
                [{"kind": "unlisted-plugin", "name": "gamma@market-a", "want": "", "got": "1.0.0"}],
            ),
            (
                "missing plugin",
                missing_plugin,
                "desktop",
                [{"kind": "missing-plugin", "name": "beta@market-b", "want": "2.0.0", "got": ""}],
            ),
            (
                "version drift",
                version_drift,
                "desktop",
                [{"kind": "version", "name": "alpha@market-a", "want": "1.0.0", "got": "1.1.0"}],
            ),
            (
                "commit drift",
                commit_drift,
                "desktop",
                [{"kind": "commit", "name": "alpha@market-a", "want": SHA_A, "got": SHA_C}],
            ),
            (
                "two install scopes",
                two_install_scopes,
                "desktop",
                [{"kind": "version", "name": "alpha@market-a", "want": "1.0.0", "got": "1.2.0"}],
            ),
            (
                "marketplace swapped",
                marketplace_swapped,
                "desktop",
                [
                    {
                        "kind": "source",
                        "name": "alpha@market-a",
                        "want": "github:example/market-a",
                        "got": "github:evil/market-a",
                    },
                ],
            ),
            (
                "feature on, want",
                feature_on_want,
                "desktop",
                [{"kind": "feature-on", "name": "alpha@market-a/cloud-sync", "want": "", "got": "set"}],
            ),
            ("feature off, key missing", feature_off_key_missing, "desktop", []),
            ("feature off, file missing", feature_off_file_missing, "desktop", []),
            (
                "feature on, file missing",
                feature_on_file_missing,
                "desktop",
                [{"kind": "feature-on", "name": "alpha@market-a/cloud-sync", "want": "1", "got": "unset"}],
            ),
            (
                "feature on, contains",
                feature_on_contains,
                "desktop",
                [
                    {
                        "kind": "feature-on",
                        "name": "alpha@market-a/cloud-skills",
                        "want": "contains",
                        "got": "missing Skill(alpha:gateway)",
                    },
                ],
            ),
            ("feature dotted env key", feature_dotted_env_key, "desktop", []),
            (
                "unlisted mcp",
                unlisted_mcp,
                "desktop",
                [{"kind": "unlisted-mcp", "name": "docs", "want": "", "got": "docs.example.com"}],
            ),
            (
                "mcp args drift",
                mcp_args_drift,
                "desktop",
                [{"kind": "mcp-command", "name": "notes", "want": "/usr/bin/notes", "got": "/usr/bin/notes"}],
            ),
            (
                "mcp url drift",
                mcp_url_drift,
                "desktop",
                [{"kind": "mcp-command", "name": "docs", "want": "docs.example.com", "got": "evil.example.com"}],
            ),
            ("feature want number", feature_want_number, "desktop", []),
            (
                "marketplace missing",
                marketplace_missing,
                "desktop",
                [{"kind": "source", "name": "alpha@market-a", "want": "github:example/market-a", "got": ""}],
            ),
            (
                "two drift kinds",
                two_drift_kinds,
                "desktop",
                [
                    {"kind": "unlisted-mcp", "name": "docs", "want": "", "got": "docs.example.com"},
                    {"kind": "version", "name": "alpha@market-a", "want": "1.0.0", "got": "1.1.0"},
                ],
            ),
            (
                "mcp command drift",
                mcp_command_drift,
                "desktop",
                [{"kind": "mcp-command", "name": "notes", "want": "/usr/bin/notes", "got": "/tmp/notes"}],
            ),
            (
                "mcp scope",
                mcp_scope,
                "vm",
                [{"kind": "unlisted-mcp", "name": "notes", "want": "", "got": "/usr/bin/notes"}],
            ),
            (
                "unlisted marketplace",
                unlisted_marketplace,
                "desktop",
                [{"kind": "unlisted-marketplace", "name": "market-c", "want": "", "got": "github:example/market-c"}],
            ),
            ("mcp home variable", mcp_home_variable, "desktop", []),
        ]
        for name, change, scope, want in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    # given
                    f = Fixture(root)
                    if change:
                        change(f)

                    # when
                    got = f.run_check(scope)

                    # then
                    self.assertEqual(got, want)


class TestCheckWarnings(unittest.TestCase):
    def test_check_warnings(self):
        cases = [
            ("clean", None, "desktop", []),
            (
                "unlisted mcp not warned",
                unlisted_mcp,
                "desktop",
                [],
            ),
            (
                "listed mcp not configured",
                lambda f: f.claude_json["mcpServers"].pop("notes"),
                "desktop",
                [{"kind": "missing-mcp", "name": "notes", "want": "/usr/bin/notes", "got": ""}],
            ),
            (
                "other scope not expected",
                lambda f: f.claude_json["mcpServers"].pop("notes"),
                "vm",
                [],
            ),
        ]
        for name, change, scope, want in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    # given
                    f = Fixture(root)
                    if change:
                        change(f)
                    f.write()

                    # when
                    got = check_warnings(
                        load_allowlist(f.allowlist_path),
                        load_mcp_servers(f.claude_json_path, None),
                        scope,
                    )

                    # then
                    self.assertEqual(got, want)


def vm_fixture(root):
    f = Fixture(root)
    f.allowlist["mcp_servers"] = [{"name": "notes", "scope": "vm", "command": ["/usr/bin/notes"], "hosts": []}]
    f.claude_json = {}
    f.managed_mcp = {"mcpServers": {"notes": {"type": "stdio", "command": "/usr/bin/notes", "args": []}}}
    return f


def run_main(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestMain(unittest.TestCase):
    def test_main(self):
        cases = [
            ("happy path - clean", None, 0, ""),
            ("happy path - one drift", version_drift, 1, ""),
            (
                "error - unknown installed format",
                lambda f: f.installed.update(version=3),
                2,
                "check_plugins: reading installed plugins: unknown format version 3",
            ),
            ("error - missing allowlist", "missing-allowlist", 2, "check_plugins: reading allowlist:"),
            (
                "error - unknown allowlist format",
                lambda f: f.allowlist.update(version=2),
                2,
                "check_plugins: reading allowlist: unknown format version 2",
            ),
            ("error - missing marketplaces", "missing-marketplaces", 2, "check_plugins: reading marketplaces:"),
            ("error - bad managed mcp", "bad-managed-mcp", 2, "check_plugins: reading mcp servers:"),
            ("error - bad settings", "bad-settings", 2, "check_plugins: reading settings:"),
            (
                "happy path - missing mcp only warns",
                lambda f: f.managed_mcp.update(mcpServers={}),
                0,
                "",
            ),
            (
                "error - allowlist plugin missing source",
                lambda f: alpha(f).pop("source"),
                2,
                "check_plugins: reading allowlist: plugin alpha@market-a: missing source",
            ),
            (
                "error - allowlist feature unknown file",
                lambda f: alpha(f).update(disabled_features=[dict(TRACK_FEATURE, file="/etc/x.json")]),
                2,
                "check_plugins: reading allowlist: feature alpha@market-a/telemetry: unknown file /etc/x.json",
            ),
            (
                "error - allowlist feature without want or contains",
                lambda f: alpha(f).update(disabled_features=[{k: v for k, v in TRACK_FEATURE.items() if k != "want"}]),
                2,
                "check_plugins: reading allowlist: feature alpha@market-a/telemetry: missing want or contains",
            ),
            (
                "error - allowlist mcp server without command or url",
                lambda f: f.allowlist["mcp_servers"][0].pop("command"),
                2,
                "check_plugins: reading allowlist: mcp server notes: missing command or url",
            ),
            (
                "error - installed plugin missing version",
                lambda f: f.installed["plugins"]["alpha@market-a"][0].pop("version"),
                2,
                "check_plugins: reading installed plugins: alpha@market-a: missing version",
            ),
        ]
        files = {
            "missing-allowlist": lambda f: os.remove(f.allowlist_path),
            "missing-marketplaces": lambda f: os.remove(f.marketplaces_path),
            "bad-managed-mcp": lambda f: open(f.managed_mcp_path, "w").write("{"),
            "bad-settings": lambda f: open(f.settings_path, "w").write("{"),
        }
        for name, change, want_code, want_err in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    # given
                    f = vm_fixture(root)
                    if name == "error - bad settings":
                        alpha(f)["disabled_features"] = [TRACK_FEATURE]
                    if callable(change):
                        change(f)
                    argv = f.argv()
                    if change in files:
                        files[change](f)

                    # when
                    code, out, err = run_main(argv)

                    # then
                    self.assertEqual(code, want_code)
                    if name == "happy path - clean":
                        self.assertEqual(json.loads(out), {"version": 1, "scope": "vm", "drift": [], "warnings": []})
                        self.assertEqual(err, "")
                    if name == "happy path - missing mcp only warns":
                        self.assertEqual(json.loads(out)["drift"], [])
                        self.assertEqual([w["kind"] for w in json.loads(out)["warnings"]], ["missing-mcp"])
                    if want_code == 1:
                        self.assertEqual(len(json.loads(out)["drift"]), 1)
                    if want_code == 2:
                        self.assertEqual(out, "")
                    self.assertTrue(err.startswith(want_err), err)


if __name__ == "__main__":
    unittest.main()
