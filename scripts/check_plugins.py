import argparse
import json
import os
import sys
from urllib.parse import urlsplit

MANAGED_SETTINGS = "/etc/claude-code/managed-settings.json"
MANAGED_MCP = "/etc/claude-code/managed-mcp.json"


def read_json(path: str):
    with open(path) as f:
        return json.load(f)


def load_allowlist(path: str) -> dict:
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)

    if data.get("version") != 1:
        raise ValueError(f"unknown format version {data.get('version')}")

    return data


def load_installed(path: str) -> dict[str, list[dict]]:
    data = read_json(path)

    if data.get("version") != 2:
        raise ValueError(f"unknown format version {data.get('version')}")

    return data["plugins"]


def load_marketplaces(path: str) -> dict[str, str]:
    marketplaces = {}

    for name, entry in read_json(path).items():
        source = entry["source"]
        where = source.get("repo") or source.get("url") or source.get("path") or ""
        marketplaces[name] = f"{source['source']}:{where}"

    return marketplaces


def server_entry(scope: str, config: dict) -> dict:
    command = None
    if "command" in config:
        command = [config["command"], *config.get("args", [])]

    return {"scope": scope, "command": command, "url": config.get("url")}


def load_mcp_servers(claude_json: str, managed_mcp: str | None) -> dict[str, dict]:
    servers = {}

    if os.path.exists(claude_json):
        data = read_json(claude_json)
        configs = [data.get("mcpServers", {})]
        configs += [project.get("mcpServers", {}) for project in data.get("projects", {}).values()]
        for config in configs:
            for name, server in config.items():
                servers[name] = server_entry("desktop", server)

    if managed_mcp and os.path.exists(managed_mcp):
        for name, server in read_json(managed_mcp).get("mcpServers", {}).items():
            servers[name] = server_entry("vm", server)

    return servers


def lookup(feature: dict, settings_path: str, home: str):
    path = feature["file"]
    if path == "$SETTINGS":
        path = settings_path
    elif path.startswith("~/"):
        path = os.path.join(home, path[2:])
    else:
        raise ValueError(f"unknown feature file {path}")

    if not os.path.exists(path):
        return None

    value = read_json(path)
    for part in feature["key"].split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]

    return value


def feature_off(feature: dict, settings_path: str, home: str) -> tuple[bool, str]:
    value = lookup(feature, settings_path, home)

    if "contains" in feature:
        held = value if isinstance(value, list) else []
        missing = [item for item in feature["contains"] if item not in held]
        if missing:
            return False, f"missing {', '.join(missing)}"

        return True, ""

    got = "unset" if value in (None, "") else "set"
    want = str(feature["want"])
    if value is None:
        return want == "", got

    return str(value) == want, got


def drift(kind: str, name: str, want: str, got: str) -> dict:
    return {"kind": kind, "name": name, "want": want, "got": got}


def target(server: dict) -> tuple:
    return tuple(server.get("command") or []), server.get("url") or ""


def describe(server: dict) -> str:
    if server.get("command"):
        return server["command"][0]

    return urlsplit(server.get("url") or "").hostname or ""


def check_plugin(plugin: dict, entries: list[dict], marketplaces: dict, settings_path: str, home: str) -> list[dict]:
    name = plugin["name"]
    items = []

    for got in sorted({entry["version"] for entry in entries if entry["version"] != plugin["version"]}):
        items.append(drift("version", name, plugin["version"], got))

    commit = plugin.get("commit")
    if commit:
        shas = {e["gitCommitSha"] for e in entries if e["version"] == plugin["version"] and e["gitCommitSha"] != commit}
        for got in sorted(shas):
            items.append(drift("commit", name, commit, got))

    source = marketplaces.get(name.split("@", 1)[1], "")
    if source != plugin["source"]:
        items.append(drift("source", name, plugin["source"], source))

    for feature in plugin.get("disabled_features", []):
        off, got = feature_off(feature, settings_path, home)
        if not off:
            want = str(feature.get("want", "contains"))
            items.append(drift("feature-on", f"{name}/{feature['name']}", want, got))

    return items


def check(
    allowlist: dict,
    installed: dict,
    marketplaces: dict,
    servers: dict,
    settings_path: str,
    home: str,
    scope: str,
) -> list[dict]:
    items = []
    listed = {plugin["name"]: plugin for plugin in allowlist.get("plugins", [])}

    for name, entries in installed.items():
        if name not in listed:
            items.append(drift("unlisted-plugin", name, "", ",".join(sorted({e["version"] for e in entries}))))

    for name, plugin in listed.items():
        if name not in installed:
            items.append(drift("missing-plugin", name, plugin["version"], ""))
            continue
        items += check_plugin(plugin, installed[name], marketplaces, settings_path, home)

    listed_servers = {s["name"]: s for s in allowlist.get("mcp_servers", []) if s["scope"] == scope}
    for name, server in servers.items():
        want = listed_servers.get(name)
        if want is None:
            items.append(drift("unlisted-mcp", name, "", describe(server)))
            continue
        if target(want) != target(server):
            items.append(drift("mcp-command", name, describe(want), describe(server)))

    return sorted(items, key=lambda item: (item["kind"], item["name"]))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="check_plugins")
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--scope", required=True, choices=["vm", "desktop"])
    parser.add_argument("--installed")
    parser.add_argument("--marketplaces")
    parser.add_argument("--settings")
    parser.add_argument("--claude-json")
    parser.add_argument("--managed-mcp", default=MANAGED_MCP)
    parser.add_argument("--home", default=os.environ.get("HOME", ""))
    args = parser.parse_args(argv)

    plugins_dir = os.path.join(args.home, ".claude", "plugins")
    args.installed = args.installed or os.path.join(plugins_dir, "installed_plugins.json")
    args.marketplaces = args.marketplaces or os.path.join(plugins_dir, "known_marketplaces.json")
    args.claude_json = args.claude_json or os.path.join(args.home, ".claude.json")
    if not args.settings:
        args.settings = MANAGED_SETTINGS if args.scope == "vm" else os.path.join(args.home, ".claude", "settings.json")

    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    steps = [
        ("reading allowlist", lambda: load_allowlist(args.allowlist)),
        ("reading installed plugins", lambda: load_installed(args.installed)),
        ("reading marketplaces", lambda: load_marketplaces(args.marketplaces)),
        ("reading mcp servers", lambda: load_mcp_servers(args.claude_json, args.managed_mcp)),
    ]
    loaded = []
    for message, load in steps:
        try:
            loaded.append(load())
        except Exception as e:
            print(f"check_plugins: {message}: {e}", file=sys.stderr)
            return 2

    try:
        items = check(*loaded, args.settings, args.home, args.scope)
    except Exception as e:
        print(f"check_plugins: reading settings: {e}", file=sys.stderr)
        return 2

    print(json.dumps({"version": 1, "scope": args.scope, "drift": items}))
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
