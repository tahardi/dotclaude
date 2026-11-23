import fnmatch
import json
import os
import posixpath
import re
import tempfile
import unittest

import yaml

from check_plugins import feature_off

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VM_MANAGED = os.path.join(REPO, "settings", "vm-managed.json")
VM_MANAGED_MCP = os.path.join(REPO, "settings", "vm-managed-mcp.json")
DESKTOP = os.path.join(REPO, "settings", "desktop.json")
PLUGINS = os.path.join(REPO, "plugins.yaml")


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_plugins():
    with open(PLUGINS) as f:
        return yaml.safe_load(f)["plugins"]


def hook_command(event, notification_type):
    return (
        "printf '{\"tabId\":\"%s\",\"event\":\"" + event + "\",\"notificationType\":" + notification_type + "}\\n' "
        + "\"$MAPLE_TAB_ID\" >> '/home/dev/.xena/hooks.jsonl'"
    )


def reaches_xena(path):
    if not re.match(r"^(~|~/.*|/.*)$", path) or re.search(r"[$*?\[{]", path):
        return True

    full = posixpath.normpath("/home/dev" + path[1:] if path.startswith("~") else path).lstrip("/")
    xena = "home/dev/.xena"
    return full == "" or full == xena or full.startswith(xena + "/") or xena.startswith(full + "/")


class TestVmSettings(unittest.TestCase):
    def test_vm_managed(self):
        # given
        settings = read_json(VM_MANAGED)
        plugins = read_plugins()
        sandbox = settings["sandbox"]

        # when
        deny = settings["permissions"]["deny"]
        hooks = settings["hooks"]
        marketplaces = {m["repo"] for m in settings["strictKnownMarketplaces"]}

        # then
        self.assertIs(sandbox["enabled"], True)
        self.assertIs(sandbox["failIfUnavailable"], True)
        for key in [
            "allowUnsandboxedCommands",
            "enableWeakerNestedSandbox",
            "enableWeakerNetworkIsolation",
            "allowNestedUserNamespaces",
        ]:
            self.assertIs(sandbox[key], False, key)
        self.assertIs(sandbox["network"]["allowAllUnixSockets"], False)
        self.assertIn("~/.local/state/maple/findings", sandbox["filesystem"]["allowWrite"])
        for path in sandbox["filesystem"]["allowWrite"]:
            self.assertFalse(reaches_xena(path), f"writing Xena state through {path}")
        self.assertNotIn("strictAllowlist", sandbox["network"])
        self.assertNotIn("allowManagedDomainsOnly", sandbox["network"])
        for key in [
            "allowManagedHooksOnly",
            "allowManagedPermissionRulesOnly",
            "allowManagedMcpServersOnly",
            "disableClaudeAiConnectors",
            "disableRemoteControl",
            "skipDangerousModePermissionPrompt",
        ]:
            self.assertIs(settings[key], True, key)
        self.assertIs(settings["syncClaudeAiPlugins"], False)
        self.assertIs(settings["syncClaudeAiSkills"], False)
        self.assertEqual(settings["allowedMcpServers"], [])
        self.assertEqual(settings["statusLine"], {"type": "command", "command": "/etc/claude-code/statusline.sh"})
        self.assertNotIn("disableBypassPermissionsMode", settings["permissions"])
        self.assertEqual(settings["requiredMinimumVersion"], settings["requiredMaximumVersion"])
        self.assertRegex(settings["requiredMinimumVersion"], r"^\d+\.\d+\.\d+$")
        for key in [
            "DISABLE_AUTOUPDATER",
            "DISABLE_UPDATES",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "DISABLE_TELEMETRY",
            "DISABLE_ERROR_REPORTING",
            "DISABLE_FEEDBACK_COMMAND",
            "DO_NOT_TRACK",
        ]:
            self.assertEqual(settings["env"][key], "1", key)
        self.assertEqual(settings["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        for rule in deny:
            self.assertRegex(rule, r"^[A-Za-z]+\(.+\)$")
        for rule in [
            "Bash(rm -rf /*)",
            "Bash(rm -rf ~*)",
            "Bash(git push --force*)",
            "Bash(git push * --force*)",
            "Edit(//home/dev/.xena/**)",
            "Edit(//home/dev/.config/xena/**)",
        ]:
            self.assertIn(rule, deny)
        self.assertNotIn("Read(//home/dev/.config/xena/**)", deny)
        self.assertEqual(set(hooks), {"UserPromptSubmit", "Stop", "Notification"})
        self.assertEqual(hooks["Notification"][0]["matcher"], "permission_prompt")
        for event, notification_type in [
            ("UserPromptSubmit", "null"),
            ("Stop", "null"),
            ("Notification", '"permission_prompt"'),
        ]:
            commands = [h["command"] for h in hooks[event][0]["hooks"]]
            self.assertEqual(commands, [hook_command(event, notification_type)], event)
        self.assertEqual(set(settings["enabledPlugins"]), {p["name"] for p in plugins})
        self.assertTrue(all(v is True for v in settings["enabledPlugins"].values()))
        self.assertEqual(marketplaces, {p["source"].removeprefix("github:") for p in plugins})

    def test_reaches_xena(self):
        # given
        cases = [
            ("~/Documents/code", False),
            ("~/.cache", False),
            ("~/.local/state/maple/findings", False),
            ("/home/dev/.xenaother", False),
            ("~/.xena", True),
            ("~/.xena/", True),
            ("~/.xena/hooks.jsonl", True),
            ("/home/dev/.xena", True),
            ("~", True),
            ("~/", True),
            ("/", True),
            ("/home", True),
            ("//home/dev/.xena", True),
            ("/home//dev/.xena", True),
            ("/home/dev/./.xena", True),
            ("~/Documents/../.xena", True),
            ("~dev/.xena", True),
            ("$HOME/.xena", True),
            ("~/.x*", True),
            ("/home/*", True),
            ("relative/path", True),
        ]

        # when
        results = [(path, reaches_xena(path)) for path, _ in cases]

        # then
        self.assertEqual(results, cases)

    def test_vm_managed_mcp(self):
        # given
        path = VM_MANAGED_MCP
        with open(PLUGINS) as f:
            listed = {s["name"]: s for s in yaml.safe_load(f)["mcp_servers"] if s["scope"] == "vm"}

        # when
        servers = read_json(path)["mcpServers"]
        vault = servers["vault"]

        # then
        self.assertEqual(
            servers,
            {
                "vault": {
                    "type": "stdio",
                    "command": "/usr/bin/socat",
                    "args": ["STDIO", "UNIX-CONNECT:/home/dev/.xena/vault.sock"],
                },
            },
        )
        self.assertEqual(listed["vault"]["command"], [vault["command"], *vault["args"]])

    def test_plugins_feature_rules(self):
        # given
        features = [(p["name"], f) for p in read_plugins() for f in p["disabled_features"]]

        with tempfile.TemporaryDirectory() as home:
            # when
            results = [(name, f["name"], feature_off(f, VM_MANAGED, home)) for name, f in features]

        # then
        self.assertTrue(features)
        for plugin, feature, (off, got) in results:
            self.assertTrue(off, f"{plugin}/{feature}: {got}")

    def test_desktop(self):
        # given
        settings = read_json(DESKTOP)
        features = [(p["name"], f) for p in read_plugins() for f in p["disabled_features"] if f["file"] == "$SETTINGS"]

        # when
        skills = {
            rule
            for p in read_plugins()
            for f in p["disabled_features"]
            for rule in f.get("contains", [])
            if re.match(r"^Skill\(.+\)$", rule)
        }

        with tempfile.TemporaryDirectory() as home:
            results = [(name, f["name"], feature_off(f, DESKTOP, home)) for name, f in features]

        allow_write = [p.replace("~", "/home/bear", 1) for p in settings["sandbox"]["filesystem"]["allowWrite"]]
        network = settings["sandbox"]["network"]

        # then
        self.assertIs(network.get("strictAllowlist"), True, "leaving the allowlist unenforced")
        for host in [
            "github.com",
            "api.github.com",
            "taylorantoniohardin.atlassian.net",
            "api.media.atlassian.com",
            "proxy.golang.org",
            "sum.golang.org",
            "vuln.go.dev",
            "registry.npmjs.org",
            "www.electronjs.org",
            "index.crates.io",
            "static.crates.io",
            "static.rust-lang.org",
            "huggingface.co",
        ]:
            self.assertIn(host, network["allowedDomains"], f"missing host {host}")
        self.assertFalse(
            any(fnmatch.fnmatch("storage.googleapis.com", domain) for domain in network["allowedDomains"]),
            "allowing every Google Cloud Storage bucket",
        )
        for name in ["GOPATH", "GOCACHE", "GOLANGCI_LINT_CACHE", "GOTMPDIR"]:
            value = settings["env"][name]
            self.assertTrue(value.startswith("/home/bear/.cache/claude-go/"), f"writing {name} outside claude-go")
            self.assertTrue(
                any(value == p or value.startswith(p + "/") for p in allow_write),
                f"writing {name} outside allowWrite",
            )
        git_dirs = [p for p in settings["sandbox"]["filesystem"]["allowWrite"] if p.endswith("/.git")]
        self.assertTrue(git_dirs)
        for git_dir in git_dirs:
            for name in ["hooks", "config"]:
                self.assertIn(
                    f"{git_dir}/{name}",
                    settings["sandbox"]["filesystem"].get("denyWrite", []),
                    f"letting sandboxed commands write {git_dir}/{name}",
                )
        self.assertIn("~/.cache/claude-go", settings["sandbox"]["filesystem"]["allowWrite"])
        for path in ["~/.cache/go-build", "~/go/pkg", "~/go", "~/.cache/golangci-lint"]:
            shared = path.replace("~", "/home/bear", 1)
            self.assertFalse(
                any(shared == p.rstrip("/") or shared.startswith(p.rstrip("/") + "/") for p in allow_write),
                f"sharing Go cache {path} with unsandboxed commands",
            )
        for plugin, feature, (off, got) in results:
            self.assertTrue(off, f"{plugin}/{feature}: {got}")
        self.assertEqual(settings["env"]["DO_NOT_TRACK"], "1")
        self.assertLessEqual(
            {m["source"]["repo"] for m in settings["extraKnownMarketplaces"].values()},
            {p["source"].removeprefix("github:") for p in read_plugins()},
        )
        self.assertTrue(skills)
        self.assertLessEqual(skills, set(settings["permissions"]["deny"]))


if __name__ == "__main__":
    unittest.main()
