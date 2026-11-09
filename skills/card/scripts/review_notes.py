import json
import re
import sys
from pathlib import Path

HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MARKER = "**Reviewer note:**"
USAGE = "usage: review_notes.py review NOTES DIFF COMMIT | comment NOTES DIFF"


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


def check_text(notes: list[dict]) -> None:
    for i, note in enumerate(notes, start=1):
        if not (note.get("text") or "").strip():
            raise ValueError(f"reading notes: note {i} has no text")


def review_payload(notes: list[dict], diff: str, commit: str) -> dict | None:
    check_text(notes)
    lines = new_side_lines(diff)
    comments = [
        {"path": note["path"], "line": note["line"], "side": "RIGHT", "body": f"{MARKER} {note['text']}"}
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


def general_comment(notes: list[dict], diff: str) -> str:
    check_text(notes)
    lines = new_side_lines(diff)
    general = [note for note in notes if not is_inline(note, lines)]
    if not general:
        return ""
    items = [f"{i}. {location(note)}{note['text']}" for i, note in enumerate(general, start=1)]
    return f"{MARKER} notes on the whole PR\n\n" + "\n".join(items)


def read_inputs(notes_path: str, diff_path: str) -> tuple[list[dict], str]:
    return json.loads(Path(notes_path).read_text()), Path(diff_path).read_text(encoding="utf-8", errors="replace")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 4 and args[0] == "review":
        payload = review_payload(*read_inputs(args[1], args[2]), args[3])
        if payload:
            print(json.dumps(payload))
    elif len(args) == 3 and args[0] == "comment":
        comment = general_comment(*read_inputs(args[1], args[2]))
        if comment:
            print(comment)
    else:
        print(USAGE, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
