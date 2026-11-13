import json
import re
import subprocess
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
SEVERITIES = ("high", "medium", "low")
CLASS = re.compile(r"\A[a-z0-9-]{1,60}\Z")
HASH = re.compile(r"\A[0-9a-f]{16}\Z")
USAGE = "usage: trust_model.py check DIR | base SHA"


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


def git(args: list[str], what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"{what}: git {args[0]} timed out") from error
    except OSError as error:
        raise ValueError(f"{what}: running git: {error.strerror or error}") from error


def show(base: str, rel: str) -> str | None:
    result = git(["show", f"{base}:{rel}"], rel)
    return result.stdout if result.returncode == 0 else None


def at_base(base: str) -> tuple[dict | None, dict | None]:
    if git(["cat-file", "-e", f"{base}^{{commit}}"], f"base commit {base}").returncode != 0:
        raise ValueError(f"base commit {base} is not in this repo")

    found = []

    for rel, read in ((MODEL, read_model), (SECURITY, read_security)):
        text = show(base, rel)

        try:
            found.append(None if text is None else read(text))
        except (yaml.YAMLError, ValueError) as error:
            raise ValueError(f"{rel}: {' '.join(str(error).split())}") from error

    return found[0], found[1]


def opted_in(model: dict | None, security: dict | None) -> bool:
    return model is not None and security is not None and security.get("enabled") is True


def model_at(base: str) -> tuple[tuple[dict, dict] | None, str | None]:
    try:
        model, security = at_base(base)
    except ValueError as error:
        return None, f"reading trust model: {error}; findings unfiltered"

    if model is None or security is None or not opted_in(model, security):
        return None, None

    for rel, found in ((MODEL, model_problems(model)), (SECURITY, security_problems(security))):
        if found:
            return None, f"reading trust model: {rel}: {found[0]}; findings unfiltered"

    return (model, security), None


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
    lines = text.splitlines()
    found = []
    last = -1

    for heading in HEADINGS:
        if heading not in lines:
            found.append(f'trust-model.md has no "{heading}" heading')
            continue

        index = lines.index(heading)

        if lines.count(heading) > 1:
            found.append(f'trust-model.md has "{heading}" more than once')

        if index < last:
            found.append(f'trust-model.md has "{heading}" out of order')

        last = max(last, index)

    return found


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

        ids = [entry.get("id") for entry in entries(model, key) if isinstance(entry, dict) and entry.get("id")]
        repeated = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
        found.extend(f"{key} has id {entry_id} more than once" for entry_id in repeated)

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

    attackers = [attacker for attacker in entries(model, "attackers") if isinstance(attacker, dict)]

    reaching = [attacker for attacker in attackers if isinstance(attacker.get("reaches"), list) and attacker["reaches"]]

    if attackers and not reaching:
        found.append("at least one attacker must reach a component")

    for boundary in entries(model, "boundaries"):
        if not isinstance(boundary, dict):
            continue

        between = boundary.get("between")

        for component in between if isinstance(between, list) else []:
            if component not in components:
                found.append(f"boundary {boundary.get('id')} is between unknown component {component}")

    build = model.get("build")
    build = build if isinstance(build, dict) else {}
    found.extend(f"build.{field} is missing" for field in BUILD_FIELDS if build.get(field) in (None, ""))

    for key in ("accepted", "overrides"):
        found.extend(identity_problems(model, key))

    for number, entry in enumerate(entries(model, "overrides"), start=1):
        if not isinstance(entry, dict) or entry.get("severity") not in SEVERITIES:
            found.append(f"overrides entry {number} needs severity high, medium, or low")

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
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "base"):
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    if sys.argv[1] == "base":
        known, warning = model_at(sys.argv[2])
        status = {"optedIn": known is not None}
        print(json.dumps(status if warning is None else {**status, "warning": warning}))
        sys.exit(0)

    found = problems(Path(sys.argv[2]))

    for problem in found:
        print(problem)

    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
