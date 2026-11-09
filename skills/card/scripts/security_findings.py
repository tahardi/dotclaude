import json
import re
import sys

MARKER = re.compile(r"\A<!-- xena-security-finding severity=(high|medium|low) id=([A-Za-z0-9-]{1,40}) -->")
ACCEPT = re.compile(r"(?m)^xena-accept ([A-Za-z0-9-]{1,40})$")
NUMBERED = re.compile(r"\AF(\d+)\Z")
TOOL_PREFIXES = ("**Claude:**", "**Reviewer note:**")


def accepted_ids(comments: list, login: str) -> set:
    ids = set()

    for comment in comments:
        author = comment.get("author") or {}
        body = comment["body"].replace("\r\n", "\n")

        if author.get("login") != login or comment.get("includesCreatedEdit"):
            continue

        if MARKER.match(body) or body.startswith(TOOL_PREFIXES):
            continue

        ids.update(ACCEPT.findall(body))

    return ids


def findings(comments: list, login: str) -> dict:
    ordered = sorted(comments, key=lambda comment: comment["createdAt"])
    still_open = []
    highest = 0

    for comment in ordered:
        marker = MARKER.match(comment["body"])

        if not marker:
            continue

        severity, finding_id = marker.groups()
        numbered = NUMBERED.match(finding_id)

        if numbered:
            highest = max(highest, int(numbered[1]))

        later = [other for other in ordered if other["createdAt"] > comment["createdAt"]]

        if finding_id not in accepted_ids(later, login):
            edited = comment.get("includesCreatedEdit")
            still_open.append({"id": finding_id, "severity": "high" if edited else severity})

    return {
        "next": highest + 1,
        "open": still_open,
        "blocking": any(finding["severity"] == "high" for finding in still_open),
    }


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("usage: security_findings.py LOGIN", file=sys.stderr)
        sys.exit(2)

    try:
        result = findings(json.load(sys.stdin)["comments"], sys.argv[1])
    except (ValueError, KeyError, TypeError, AttributeError):
        print("reading comments: expected gh pr view --json comments output", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
