import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
KEY = re.compile(r"\A[A-Z][A-Z0-9]*-\d+\Z")
CLASS = re.compile(r"\A[a-z0-9-]{1,60}\Z")
SOURCE = re.compile(r"\A(security-pass|agent-review|tool:[a-z0-9-]{1,40})\Z")
NUMBERED = re.compile(r"\AF(\d+)\Z")
CHIPS = {
    "costs-money",
    "leaks-credentials",
    "leaks-data",
    "runs-code",
    "changes-data",
    "bypasses-access",
    "breaks-service",
    "supply-chain",
}
PROSE = ("what", "how", "impact", "defense")
REQUIRED = ("severity", "identity", "line", "sources", "title", *PROSE, "chips")
USAGE = "usage: findings.py write KEY --head SHA"


def findings_path(key: str) -> Path:
    folder = os.environ.get("MAPLE_FINDINGS_DIR") or os.path.expanduser("~/.config/maple/findings")
    return Path(folder) / f"{key}.json"


def code_hash(code: str) -> str:
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is not a non-empty string")
    if len(value) > limit:
        raise ValueError(f"{name} is over {limit} characters")
    return value


def identity_of(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("identity is not an object")
    if value.get("kind") == "code":
        found_class = value.get("class")
        if not isinstance(found_class, str) or not CLASS.match(found_class):
            raise ValueError("identity class is not a kebab-case slug")
        return {
            "kind": "code",
            "class": found_class,
            "file": text(value.get("file"), "identity file", 4096),
            "hash": code_hash(text(value.get("code"), "identity code", 20000)),
        }
    if value.get("kind") == "dependency":
        return {
            "kind": "dependency",
            "advisory": text(value.get("advisory"), "identity advisory", 200),
            "package": text(value.get("package"), "identity package", 400),
        }
    raise ValueError("identity kind is not code or dependency")


def finding_of(value: object) -> dict | None:
    if not isinstance(value, dict):
        raise ValueError("not an object")
    for name in REQUIRED:
        if name not in value:
            raise ValueError(f"missing {name}")
    severity = value["severity"]
    if severity == "low":
        return None
    line = value["line"]
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
        raise ValueError("line is not a positive number or null")
    sources = value["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources is not a non-empty list")
    for source in sources:
        if not isinstance(source, str) or not SOURCE.match(source):
            raise ValueError(f"unknown source {source}")
    chips = value["chips"]
    if not isinstance(chips, list) or len(chips) > 3:
        raise ValueError("chips is not a list of up to 3")
    for chip in chips:
        if chip not in CHIPS:
            raise ValueError(f"unknown chip {chip}")
    return {
        "identity": identity_of(value["identity"]),
        "line": line,
        "severity": severity if severity in ("high", "medium") else "high",
        "sources": list(dict.fromkeys(sources)),
        "title": text(value["title"], "title", 120),
        **{name: text(value[name], name, 600) for name in PROSE},
        "chips": list(dict.fromkeys(chips)),
    }


def parse(items: object) -> tuple[list, int]:
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    parsed = []
    dropped = 0
    for number, value in enumerate(items, start=1):
        try:
            finding = finding_of(value)
        except ValueError as error:
            raise ValueError(f"item {number}: {error}") from error
        if finding is None:
            dropped += 1
        else:
            parsed.append(finding)
    return parsed, dropped


def identity_key(identity: dict) -> str:
    return json.dumps(identity, sort_keys=True)


def number_of(finding_id: str) -> int:
    numbered = NUMBERED.match(finding_id)
    return int(numbered[1]) if numbered else 0


def merge(existing: dict | None, incoming: list, head: str, now: str) -> dict:
    previous = existing or {"version": VERSION, "round": 0, "resume": None, "findings": []}
    old = previous["findings"]
    highest = max((number_of(finding["id"]) for finding in old), default=0)

    combined: dict[str, dict] = {}
    for finding in incoming:
        key = identity_key(finding["identity"])
        if key in combined:
            sources = combined[key]["sources"] + finding["sources"]
            combined[key]["sources"] = list(dict.fromkeys(sources))
        else:
            combined[key] = dict(finding)

    updated = {}
    added = []
    for key, finding in combined.items():
        matches = [other for other in old if identity_key(other["identity"]) == key]
        undecided = [other for other in matches if other["decision"] is None]
        held = [other for other in matches if other["decision"] is not None and not refixed(other)]
        if undecided:
            updated[undecided[0]["id"]] = {**undecided[0], **finding}
        elif not held:
            highest += 1
            new = {"id": f"F{highest}", **finding, "applied": None, "decision": None, "severityOverride": None}
            added.append(new)

    kept = [updated.get(finding["id"], finding) for finding in old]
    kept = [finding for finding in kept if finding["decision"] is not None or finding["id"] in updated]
    return {
        **previous,
        "version": VERSION,
        "round": previous["round"] + 1,
        "headSha": head,
        "updatedAt": now,
        "findings": kept + added,
    }


def refixed(finding: dict) -> bool:
    return finding["decision"]["kind"] == "fix-now" and finding["applied"] is not None


def read_existing(path: Path) -> dict | None:
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"reading findings: {path.name}: {error.strerror}") from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"reading findings: {path.name}: not valid JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ValueError(f"reading findings: {path.name}: not a findings file")
    version = data.get("version")
    if isinstance(version, int) and version > VERSION:
        raise ValueError(f"reading findings: {path.name} is from a newer version")
    return data


def write(key: str, head: str, items: object, now: str) -> dict:
    if not KEY.match(key):
        raise ValueError(f"reading findings input: bad card key {key}")
    try:
        incoming, dropped = parse(items)
    except ValueError as error:
        raise ValueError(f"reading findings input: {error}") from error
    path = findings_path(key)
    merged = {**merge(read_existing(path), incoming, head, now), "card": key}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(merged, indent=2) + "\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    ids = [finding["id"] for finding in merged["findings"] if finding["decision"] is None]
    return {"round": merged["round"], "ids": ids, "dropped": dropped}


def main() -> None:
    args = sys.argv[1:]
    if len(args) != 4 or args[0] != "write" or args[2] != "--head" or not args[3]:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    try:
        items = json.load(sys.stdin)
    except ValueError:
        print("reading findings input: not valid JSON", file=sys.stderr)
        sys.exit(1)
    try:
        result = write(args[1], args[3], items, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
