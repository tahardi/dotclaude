import json
import os
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
        for rule in ["Bash(rm -rf /*)", "Bash(rm -rf ~*)", "Bash(git push --force*)", "Bash(git push * --force*)"]:
            self.assertIn(rule, deny)
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

        # then
        for plugin, feature, (off, got) in results:
            self.assertTrue(off, f"{plugin}/{feature}: {got}")
        self.assertEqual(settings["env"]["DO_NOT_TRACK"], "1")
        self.assertTrue(skills)
        self.assertLessEqual(skills, set(settings["permissions"]["deny"]))


if __name__ == "__main__":
    unittest.main()
