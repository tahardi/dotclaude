import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

import findings

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
USAGE = "usage: trust_model.py check DIR | base SHA | apply KEY | diff KEY --base SHA"
MODEL_CLASSES = ("trust-model-change", "trust-model-update")
ACCEPTED_HEADING = "## Accepted Risks"
OVERRIDES_HEADING = "## Severity Overrides"


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


def entry_line(entry: dict) -> str:
    return f"  - {json.dumps(entry)}"


def one_line(value: object) -> str:
    return " ".join(str(value).split()) if value else "none"


def entry_lines(file: dict) -> dict[str, list[str]]:
    lines: dict[str, list[str]] = {}
    card = file.get("card")

    for finding in file.get("findings", []):
        decision = finding.get("decision")
        identity = finding.get("identity")

        if not isinstance(decision, dict) or not isinstance(identity, dict) or identity.get("class") in MODEL_CLASSES:
            continue

        title = finding.get("title")
        tag = f"{card} {finding.get('id')}"
        at = str(decision.get("decidedAt", ""))[:10]
        applied = finding.get("applied") if isinstance(finding.get("applied"), dict) else {}

        if decision.get("kind") == "accept-risk":
            reason = decision.get("reason")
            entry = {"identity": identity, "title": title, "reason": reason, "card": card, "finding": finding["id"]}
            lines.setdefault(f"{MODEL}:accepted", []).append(entry_line({**entry, "at": at}))
            lines.setdefault(f"{MD}:{ACCEPTED_HEADING}", []).append(f"- {one_line(title)} ({tag}): {one_line(reason)}")

        if finding.get("severityOverride") in SEVERITIES:
            severity = finding["severityOverride"]
            entry = {"identity": identity, "severity": severity, "title": title, "card": card}
            lines.setdefault(f"{MODEL}:overrides", []).append(
                entry_line({**entry, "finding": finding["id"], "at": at})
            )
            lines.setdefault(f"{MD}:{OVERRIDES_HEADING}", []).append(f"- {one_line(title)} ({tag}): {severity}")

        if decision.get("kind") == "fix-later" and applied.get("cardKey"):
            entry = {"identity": identity, "title": title, "card": applied["cardKey"]}
            lines.setdefault(f"{SECURITY}:tracked", []).append(entry_line(entry))

    return lines


def section_end(lines: list[str], start: int, markdown: bool) -> int:
    end = start + 1

    while end < len(lines) and (
        not lines[end].startswith("#") if markdown else lines[end].startswith((" ", "-"))
    ):
        end += 1

    while markdown and end > start + 1 and not lines[end - 1].strip():
        end -= 1

    return end


def insert(rel: str, text: str, section: str, new: list[str], markdown: bool) -> str:
    lines = text.splitlines()
    header = section if markdown else f"{section}:"
    starts = [
        index
        for index, line in enumerate(lines)
        if (line.rstrip() == header if markdown else line.startswith(header))
    ]

    if not starts:
        lines.append(header)
        starts = [len(lines) - 1]

    if not markdown:
        if lines[starts[0]][len(header) :].strip() not in ("", "[]"):
            raise ValueError(f"writing trust model: {rel}: {section} is an inline list")

        lines[starts[0]] = header

    end = section_end(lines, starts[0], markdown)
    return "\n".join(lines[:end] + new + lines[end:]) + "\n"


def apply(repo: Path, file: dict) -> int:
    if not (repo / MODEL).is_file():
        return 0

    added = 0

    for key, new in entry_lines(file).items():
        rel, section = key.split(":", 1)
        path = repo / rel

        if not path.is_file():
            continue

        text = path.read_text()
        present = set(text.splitlines())
        missing = [line for line in dict.fromkeys(new) if line not in present]

        if missing:
            path.write_text(insert(rel, text, section, missing, rel == MD))
            added += len(missing)

    return added


def unexplained(diff_text: str, expected: set[str]) -> list[dict]:
    found: dict[str, list[str]] = {}
    current = None
    in_header = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current, in_header = None, True
        elif in_header and line.startswith("@@"):
            in_header = False
        elif in_header and line.startswith(("--- a/", "+++ b/")):
            current = line[6:]
        elif not in_header and current in (MD, MODEL, SECURITY) and line.startswith(("+", "-")):
            if not (line.startswith("+") and line[1:] in expected):
                found.setdefault(current, []).append(line)

    return [{"file": rel, "lines": lines} for rel, lines in found.items()]


def findings_file(key: str) -> dict:
    return findings.read_existing(findings.findings_path(key)) or {"card": key, "findings": []}


def model_diff(key: str, base: str) -> list[dict]:
    if git(["cat-file", "-e", f"{base}^{{commit}}"], f"base commit {base}").returncode != 0:
        raise ValueError(f"base commit {base} is not in this repo")

    if show(base, MODEL) is None:
        return []

    expected = {line for lines in entry_lines(findings_file(key)).values() for line in lines}
    flags = ["--unified=0", "--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/"]
    result = git(["diff", *flags, base, "--", MD, MODEL, SECURITY], "diffing trust model")

    if result.returncode != 0:
        raise ValueError(f"diffing trust model: {' '.join(result.stderr.split())}")

    return unexplained(result.stdout, expected)


def usage() -> None:
    print(USAGE, file=sys.stderr)
    sys.exit(2)


def run_findings_command(args: list[str]) -> object:
    if len(args) == 2 and args[0] == "apply" and findings.KEY.match(args[1]):
        return {"added": apply(Path.cwd(), findings_file(args[1]))}

    if len(args) == 4 and args[0] == "diff" and findings.KEY.match(args[1]) and args[2] == "--base" and args[3]:
        return model_diff(args[1], args[3])

    usage()
    return None


def main() -> None:
    args = sys.argv[1:]

    if args[:1] in (["apply"], ["diff"]):
        try:
            print(json.dumps(run_findings_command(args)))
        except ValueError as error:
            print(error, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if len(args) != 2 or args[0] not in ("check", "base"):
        usage()

    if args[0] == "base":
        known, warning = model_at(args[1])
        status = {"optedIn": known is not None}
        print(json.dumps(status if warning is None else {**status, "warning": warning}))
        sys.exit(0)

    found = problems(Path(args[1]))

    for problem in found:
        print(problem)

    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
