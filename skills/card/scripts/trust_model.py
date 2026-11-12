import re
import sys
from pathlib import Path

import yaml

MD = "docs/security/trust-model.md"
MODEL = ".maple/trust-model.yaml"
SECURITY = ".maple/security.yaml"
HEADINGS = [
    "# Trust Model",
    "## Assets",
    "## Who Might Attack",
    "## Trust Boundaries",
    "## Users and Access",
    "## Build, Deploy, and Monitor",
    "## Accepted Risks",
    "## Severity Overrides",
]
ENTRY_FIELDS = {
    "assets": ["id", "what", "loss"],
    "components": ["id", "what"],
    "attackers": ["id", "who", "reaches"],
    "boundaries": ["id", "between", "crosses", "checks"],
    "users": ["id", "who", "can", "access"],
}
BUILD_FIELDS = ["built", "deployed", "monitored"]
CLASS = re.compile(r"\A[a-z0-9-]{1,60}\Z")
HASH = re.compile(r"\A[0-9a-f]{16}\Z")
USAGE = "usage: trust_model.py check DIR"


class StrictBoolLoader(yaml.SafeLoader):
    pass


StrictBoolLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
StrictBoolLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"\A(?:true|false)\Z"),
    list("tf"),
)


def load_mapping(text: str) -> dict:
    data = yaml.load(text, Loader=StrictBoolLoader)

    if not isinstance(data, dict):
        raise ValueError("expected a mapping at the top level")

    return data


def read_model(text: str) -> dict:
    return load_mapping(text)


def read_security(text: str) -> dict:
    return load_mapping(text)


def identity_ok(identity: object) -> bool:
    if not isinstance(identity, dict):
        return False

    if identity.get("kind") == "code":
        return (
            set(identity) == {"kind", "class", "file", "hash"}
            and isinstance(identity["class"], str)
            and bool(CLASS.match(identity["class"]))
            and isinstance(identity["file"], str)
            and identity["file"] != ""
            and isinstance(identity["hash"], str)
            and bool(HASH.match(identity["hash"]))
        )

    if identity.get("kind") == "dependency":
        return set(identity) == {"kind", "advisory", "package"} and all(
            isinstance(identity[key], str) and identity[key] != "" for key in ("advisory", "package")
        )

    return False


def entries(data: dict, key: str) -> list:
    value = data.get(key)
    return value if isinstance(value, list) else []


def markdown_problems(text: str) -> list:
    lines = set(text.splitlines())
    return [f'trust-model.md has no "{heading}" heading' for heading in HEADINGS if heading not in lines]


def identity_problems(data: dict, key: str) -> list:
    found = []

    for number, entry in enumerate(entries(data, key), start=1):
        if not isinstance(entry, dict) or not identity_ok(entry.get("identity")):
            found.append(f"{key} entry {number} has a bad identity")

    return found


def model_problems(model: dict) -> list:
    found = []

    if model.get("version") != 1:
        found.append("version must be 1")

    for key, fields in ENTRY_FIELDS.items():
        if not entries(model, key):
            found.append(f"{key} needs at least one entry")
            continue

        for number, entry in enumerate(entries(model, key), start=1):
            if not isinstance(entry, dict):
                found.append(f"{key} entry {number} is not a mapping")
                continue

            found.extend(f"{key} entry {number} has no {field}" for field in fields if entry.get(field) in (None, ""))

    components = {entry.get("id") for entry in entries(model, "components") if isinstance(entry, dict)}

    for attacker in entries(model, "attackers"):
        if not isinstance(attacker, dict):
            continue

        reaches = attacker.get("reaches")

        if reaches is not None and not isinstance(reaches, list):
            found.append(f"attacker {attacker.get('id')} reaches must be a list")
            continue

        for component in reaches or []:
            if component not in components:
                found.append(f"attacker {attacker.get('id')} reaches unknown component {component}")

    build = model.get("build")
    build = build if isinstance(build, dict) else {}
    found.extend(f"build.{field} is missing" for field in BUILD_FIELDS if build.get(field) in (None, ""))

    for key in ("accepted", "overrides"):
        found.extend(identity_problems(model, key))

    return found


def security_problems(security: dict) -> list:
    found = []

    if security.get("version") != 1:
        found.append("version must be 1")

    if not isinstance(security.get("enabled"), bool):
        found.append("enabled must be true or false")

    found.extend(identity_problems(security, "tracked"))
    return found


def problems(repo: Path) -> list[str]:
    missing = [f"checking trust model: {rel} is missing" for rel in (MD, MODEL, SECURITY) if not (repo / rel).is_file()]

    if missing:
        return missing

    found = markdown_problems((repo / MD).read_text())

    for rel, read, check in ((MODEL, read_model, model_problems), (SECURITY, read_security, security_problems)):
        try:
            data = read((repo / rel).read_text())
        except (yaml.YAMLError, ValueError) as error:
            return [f"reading trust model: {rel}: {' '.join(str(error).split())}"]

        found.extend(check(data))

    return [f"checking trust model: {problem}" for problem in found]


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    found = problems(Path(sys.argv[2]))

    for problem in found:
        print(problem)

    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
