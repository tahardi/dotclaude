import json
import re
import sys

USAGE = "usage: python3 lesson_check.py NOTE"
PREFIX = "checking lesson: "


def blocks(text, kind):
    return re.findall(rf"^```{kind}[ \t]*\n(.*?)\n```[ \t]*$", text, re.M | re.S)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def text_field(where, name, value, most):
    if not isinstance(value, str) or not value.strip():
        return [f"{where}: {name} is missing"]
    if len(value) > most:
        return [f"{where}: {name} is {len(value)} characters, want at most {most}"]
    return []


def count(where, items, noun, least, most):
    if not isinstance(items, list):
        return [f"{where}: {noun}s is not a list"]
    if not least <= len(items) <= most:
        return [f"{where} has {len(items)} {noun}s, want {least} to {most}"]
    return []


def check_trace(data):
    if not isinstance(data, dict):
        return ["trace is not an object"]
    found = text_field("trace", "lang", data.get("lang"), 40)
    code = data.get("code")
    found += text_field("trace", "code", code, 4000)
    if found:
        return found
    total = len(code.split("\n"))
    if total > 60:
        found.append(f"trace code is {total} lines, want at most 60")
    steps = data.get("steps")
    found += count("trace", steps, "step", 2, 12)
    if not isinstance(steps, list):
        return found
    for n, step in enumerate(steps, 1):
        where = f"trace step {n}"
        if not isinstance(step, dict):
            found.append(f"{where}: is not an object")
            continue
        found += text_field(where, "text", step.get("text"), 600)
        lines = step.get("lines")
        if not (isinstance(lines, list) and len(lines) == 2 and all(is_int(x) for x in lines)):
            found.append(f"{where}: lines is not [first, last]")
        elif not 1 <= lines[0] <= lines[1]:
            found.append(f"{where}: lines {lines[0]}-{lines[1]} are not a 1-based range")
        elif lines[1] > total:
            found.append(f"{where}: lines {lines[0]}-{lines[1]} are past the end of the code ({total} lines)")
    return found


def check_quiz(data):
    if not isinstance(data, dict):
        return ["quiz is not an object"]
    questions = data.get("questions")
    found = count("quiz", questions, "question", 3, 5)
    if not isinstance(questions, list):
        return found
    for n, item in enumerate(questions, 1):
        where = f"quiz question {n}"
        if not isinstance(item, dict):
            found.append(f"{where}: is not an object")
            continue
        found += text_field(where, "question", item.get("question"), 300)
        found += text_field(where, "why", item.get("why"), 600)
        choices = item.get("choices")
        more = count(where, choices, "choice", 2, 5)
        found += more
        if more:
            continue
        for c, choice in enumerate(choices, 1):
            found += text_field(where, f"choice {c}", choice, 200)
        answer = item.get("answer")
        if not is_int(answer) or not 0 <= answer < len(choices):
            found.append(f"{where}: answer {answer} is not a choice index ({len(choices)} choices)")
    return found


def check(text):
    if not re.search(r"^## Lesson[ \t]*$", text, re.M):
        return []
    found = []
    for kind, checker in (("maple-trace", check_trace), ("maple-quiz", check_quiz)):
        found_blocks = blocks(text, kind)
        if len(found_blocks) != 1:
            found.append(f"found {len(found_blocks)} {kind} blocks, want 1")
            continue
        try:
            data = json.loads(found_blocks[0])
        except json.JSONDecodeError:
            found.append(f"{kind} block is not valid JSON")
            continue
        found += checker(data)
    return [PREFIX + p for p in found]


def main(argv):
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        with open(argv[1]) as f:
            text = f.read()
    except OSError as e:
        print(f"{PREFIX}reading {argv[1]}: {e.strerror}", file=sys.stderr)
        return 1
    found = check(text)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
