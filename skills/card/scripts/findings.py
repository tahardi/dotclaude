import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import trust_model

VERSION = 1
KEY = re.compile(r"\A[A-Z][A-Z0-9]*-\d+\Z")
CLASS = re.compile(r"\A[a-z0-9-]{1,60}\Z")
SOURCE = re.compile(r"\A(security-pass|agent-review|tool:[a-z0-9-]{1,40})\Z")
NUMBERED = re.compile(r"\AF(\d+)\Z")
COMMIT = re.compile(r"\A[0-9a-f]{7,64}\Z")
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
USAGE = "usage: findings.py write KEY --head SHA [--base SHA] | read KEY | applied KEY ID [--commit SHA] [--card KEY]"


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


def items_of(value: object, name: str, low: int, high: int, what: str) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError(f"{name} is not a list of {low} to {high} {what}")
    return value


def path_of(value: object) -> list:
    steps = []
    for number, entry in enumerate(items_of(value, "path", 2, 6, "steps"), start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"path step {number} is not an object")
        steps.append(
            {
                "actor": text(entry.get("actor"), f"path step {number} actor", 40),
                "step": text(entry.get("step"), f"path step {number} step", 120),
            }
        )
    return steps


def map_of(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("map is not an object")
    zones = [text(zone, "map zone", 40) for zone in items_of(value.get("zones"), "map zones", 2, 6, "names")]
    for zone in zones:
        if zones.count(zone) > 1:
            raise ValueError(f"map zones repeat {zone}")
    for end in ("from", "to"):
        if value.get(end) not in zones:
            raise ValueError(f"map {end} is not one of the zones")
    if value["from"] == value["to"]:
        raise ValueError("map from and to are the same zone")
    return {"zones": zones, "from": value["from"], "to": value["to"]}


def reach_of(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("reach is not an object")
    now = items_of(value.get("now"), "reach now", 1, 4, "items")
    after = items_of(value.get("afterFix", []), "reach afterFix", 0, 4, "items")
    return {
        "now": [text(entry, "reach now item", 120) for entry in now],
        "afterFix": [text(entry, "reach afterFix item", 120) for entry in after],
    }


def check_visual(visual: dict) -> dict | None:
    if not isinstance(visual, dict):
        raise ValueError("is not an object")
    parts = {"path": path_of, "map": map_of, "reach": reach_of}
    checked = {name: check(visual[name]) for name, check in parts.items() if visual.get(name) is not None}
    return checked or None


def finding_of(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("not an object")
    for name in REQUIRED:
        if name not in value:
            raise ValueError(f"missing {name}")
    severity = value["severity"]
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
        "severity": severity if severity in trust_model.SEVERITIES else "high",
        "sources": list(dict.fromkeys(sources)),
        "title": text(value["title"], "title", 120),
        **{name: text(value[name], name, 600) for name in PROSE},
        "chips": list(dict.fromkeys(chips)),
    }


def parse(items: object) -> list:
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    parsed = []
    for number, value in enumerate(items, start=1):
        try:
            finding = finding_of(value)
        except ValueError as error:
            raise ValueError(f"item {number}: {error}") from error
        try:
            visual = check_visual(value["visual"]) if value.get("visual") is not None else None
        except ValueError as error:
            raise ValueError(f"item {number} visual: {error}") from error
        parsed.append(finding if visual is None else {**finding, "visual": visual})
    return parsed


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
            if finding["severity"] == "high":
                combined[key]["severity"] = "high"
            if "visual" in finding and "visual" not in combined[key]:
                combined[key]["visual"] = finding["visual"]
        else:
            combined[key] = dict(finding)

    updated = {}
    added = []
    for key, finding in combined.items():
        matches = [other for other in old if identity_key(other["identity"]) == key]
        undecided = [other for other in matches if other["decision"] is None]
        held = [other for other in matches if other["decision"] is not None and not refixed(other)]
        if undecided:
            kept_fields = {name: field for name, field in undecided[0].items() if name != "visual"}
            updated[undecided[0]["id"]] = {**kept_fields, **finding}
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
    return finding["decision"].get("kind") == "fix-now" and finding["applied"] is not None


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
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, int) and version > VERSION:
        raise ValueError(f"reading findings: {path.name} is from a newer version")
    if not well_formed(data):
        raise ValueError(f"reading findings: {path.name}: not a findings file")
    return data


def well_formed(data: object) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("round"), int):
        return False
    found = data.get("findings")
    return isinstance(found, list) and all(
        isinstance(finding, dict)
        and isinstance(finding.get("id"), str)
        and isinstance(finding.get("identity"), dict)
        and "applied" in finding
        and "decision" in finding
        and (finding["decision"] is None or isinstance(finding["decision"], dict))
        for finding in found
    )


def known_keys(data: dict, key: str) -> set[str]:
    return {
        identity_key(entry["identity"])
        for entry in trust_model.entries(data, key)
        if isinstance(entry, dict) and isinstance(entry.get("identity"), dict)
    }


def skip_known(findings: list[dict], model: dict, security: dict) -> tuple[list[dict], int]:
    known = known_keys(model, "accepted") | known_keys(security, "tracked")
    overrides = {
        identity_key(entry["identity"]): entry["severity"]
        for entry in trust_model.entries(model, "overrides")
        if isinstance(entry, dict)
        and isinstance(entry.get("identity"), dict)
        and entry.get("severity") in trust_model.SEVERITIES
    }
    kept = []
    for finding in findings:
        key = identity_key(finding["identity"])
        if key not in known and overrides.get(key) != "low":
            kept.append({**finding, "severity": overrides.get(key, finding["severity"])})
    return kept, len(findings) - len(kept)


def write(key: str, head: str, items: object, now: str, known: tuple[dict, dict] | None = None) -> dict:
    if not KEY.match(key):
        raise ValueError(f"reading findings input: bad card key {key}")
    try:
        incoming = parse(items)
    except ValueError as error:
        raise ValueError(f"reading findings input: {error}") from error
    skipped = 0
    if known is not None:
        incoming, skipped = skip_known(incoming, *known)
    kept = [finding for finding in incoming if finding["severity"] != "low"]
    dropped = len(incoming) - len(kept)
    incoming = kept
    path = findings_path(key)
    merged = {**merge(read_existing(path), incoming, head, now), "card": key}
    save(path, merged)
    ids = [finding["id"] for finding in merged["findings"] if finding["decision"] is None]
    result = {"round": merged["round"], "ids": ids, "dropped": dropped}
    return result if known is None else {**result, "skipped": skipped}


def save(path: Path, data: dict) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(temp, path)
    except OSError as error:
        raise ValueError(f"writing findings: {path.name}: {error.strerror or error}") from error
    finally:
        temp.unlink(missing_ok=True)


def read(key: str) -> list:
    existing = read_existing(findings_path(key))
    found = existing["findings"] if existing else []
    return [
        {**finding, "severity": finding.get("severityOverride") or finding.get("severity")}
        for finding in found
        if finding["decision"] is not None and finding["applied"] is None
    ]


def mark_applied(key: str, finding_id: str, commit: str | None, card: str | None, at: str) -> None:
    path = findings_path(key)
    existing = read_existing(path)
    found = existing["findings"] if existing else []
    target = next((finding for finding in found if finding["id"] == finding_id), None)
    if existing is None or target is None:
        raise ValueError(f"marking finding applied: no finding {finding_id}")
    if target["decision"] is None:
        raise ValueError(f"marking finding applied: {finding_id} is not decided")
    target["applied"] = {"at": at, "commit": commit, "cardKey": card}
    save(path, existing)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def usage() -> None:
    print(USAGE, file=sys.stderr)
    sys.exit(2)


def applied_flags(args: list) -> dict:
    if len(args) % 2:
        usage()
    flags = dict(zip(args[::2], args[1::2]))
    if set(flags) - {"--commit", "--card"} or len(flags) * 2 != len(args) or not all(flags.values()):
        usage()
    if "--card" in flags and not KEY.match(flags["--card"]):
        usage()
    if "--commit" in flags and not COMMIT.match(flags["--commit"]):
        usage()
    return flags


def run_write(args: list) -> dict:
    if len(args) == 6 and (args[4] != "--base" or not args[5]):
        usage()
    known, warning = trust_model.model_at(args[5]) if len(args) == 6 else (None, None)
    try:
        items = json.load(sys.stdin)
    except ValueError as error:
        raise ValueError("reading findings input: not valid JSON") from error
    result = write(args[1], args[3], items, now(), known)
    return result if warning is None else {**result, "warning": warning}


def run(args: list) -> object:
    if len(args) in (4, 6) and args[0] == "write" and args[2] == "--head" and args[3]:
        return run_write(args)
    if len(args) == 2 and args[0] == "read" and KEY.match(args[1]):
        return read(args[1])
    if len(args) >= 3 and args[0] == "applied" and KEY.match(args[1]):
        flags = applied_flags(args[3:])
        mark_applied(args[1], args[2], flags.get("--commit"), flags.get("--card"), now())
        return None
    usage()
    return None


def main() -> None:
    try:
        result = run(sys.argv[1:])
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
