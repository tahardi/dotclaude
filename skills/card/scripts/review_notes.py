import json
import re
import sys
from pathlib import Path

HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MARKER = "**Reviewer note:**"
FIX_MARKER = "**Reviewer fix:**"
KINDS = {"fix": FIX_MARKER, "question": MARKER}
USAGE = "usage: review_notes.py review NOTES DIFF COMMIT | comment NOTES DIFF | open < THREADS_JSON"


def new_side_lines(diff: str) -> dict[str, set[int]]:
    lines: dict[str, set[int]] = {}
    path = None
    old_left = new_left = 0
    for row in diff.split("\n"):
        if old_left or new_left:
            if row.startswith("+"):
                new_left -= 1
            elif row.startswith("-"):
                old_left -= 1
            elif not row.startswith("\\"):
                old_left -= 1
                new_left -= 1
        elif row.startswith("+++ "):
            path = row.removeprefix("+++ b/").rstrip("\t") if row.startswith("+++ b/") else None
        elif hunk := HUNK.match(row):
            old_left = int(hunk[1] or 1)
            new_left = int(hunk[3] or 1)
            if path:
                start = int(hunk[2])
                lines.setdefault(path, set()).update(range(start, start + new_left))
    return lines


def is_inline(note: dict, lines: dict[str, set[int]]) -> bool:
    return note.get("line") in lines.get(note.get("path"), set())


def check_notes(notes: list[dict]) -> None:
    for i, note in enumerate(notes, start=1):
        if not (note.get("text") or "").strip():
            raise ValueError(f"reading notes: note {i} has no text")
        kind = note.get("kind", "question")
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError(f"reading notes: note {i} has unknown kind {kind}")


def marker(note: dict) -> str:
    return KINDS[note.get("kind", "question")]


def review_payload(notes: list[dict], diff: str, commit: str) -> dict | None:
    check_notes(notes)
    lines = new_side_lines(diff)
    comments = [
        {"path": note["path"], "line": note["line"], "side": "RIGHT", "body": f"{marker(note)} {note['text']}"}
        for note in notes
        if is_inline(note, lines)
    ]
    if not comments:
        return None
    return {"commit_id": commit, "event": "COMMENT", "comments": comments}


def location(note: dict) -> str:
    if not note.get("path"):
        return ""
    line = note.get("line")
    return f"`{note['path']}:{line}` " if line else f"`{note['path']}` "


def numbered(header: str, notes: list[dict]) -> str:
    items = [f"{i}. {location(note)}{note['text']}" for i, note in enumerate(notes, start=1)]
    return f"{header}\n\n" + "\n".join(items)


def general_comment(notes: list[dict], diff: str) -> str:
    check_notes(notes)
    lines = new_side_lines(diff)
    general = [note for note in notes if not is_inline(note, lines)]
    fixes = [note for note in general if marker(note) == FIX_MARKER]
    questions = [note for note in general if marker(note) == MARKER]
    sections = []
    if fixes:
        sections.append(numbered(f"{FIX_MARKER} Other findings", fixes))
    if questions:
        sections.append(numbered(f"{MARKER} Other notes", questions))
    return "\n\n".join(sections)


def open_fixes(threads: dict) -> list[str]:
    try:
        nodes = threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        found = []
        for node in nodes:
            comments = node["comments"]["nodes"]
            if node["isResolved"] or not comments or not comments[0]["body"].startswith(FIX_MARKER):
                continue
            line = comments[0].get("line")
            path = comments[0]["path"]
            found.append(f"{node['id']} {path}:{line}" if line else f"{node['id']} {path}")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"reading threads: {error!r}") from error
    return found


def run_open() -> None:
    try:
        threads = json.loads(sys.stdin.read())
    except ValueError as error:
        sys.exit(f"reading threads: {error}")
    try:
        found = open_fixes(threads)
    except ValueError as error:
        sys.exit(str(error))
    for row in found:
        print(row)
    sys.exit(1 if found else 0)


def review_output(notes: list[dict], diff: str, commit: str) -> str:
    payload = review_payload(notes, diff, commit)
    return json.dumps(payload) if payload else ""


def read_inputs(notes_path: str, diff_path: str) -> tuple[list[dict], str]:
    try:
        notes = json.loads(Path(notes_path).read_text())
        diff = Path(diff_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as error:
        raise ValueError(f"reading notes: {error}") from error
    if not isinstance(notes, list) or not all(isinstance(note, dict) for note in notes):
        raise ValueError("reading notes: expected a list of notes")
    return notes, diff


def main() -> None:
    args = sys.argv[1:]
    if args == ["open"]:
        run_open()
    if not ((len(args) == 4 and args[0] == "review") or (len(args) == 3 and args[0] == "comment")):
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    try:
        notes, diff = read_inputs(args[1], args[2])
        output = review_output(notes, diff, args[3]) if args[0] == "review" else general_comment(notes, diff)
    except ValueError as error:
        sys.exit(str(error))
    if output:
        print(output)


if __name__ == "__main__":
    main()
