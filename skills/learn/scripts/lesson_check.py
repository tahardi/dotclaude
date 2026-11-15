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


def lines_field(where, name, value):
    found = text_field(where, name, value, 300)
    if found:
        return found
    total = len(value.split("\n"))
    return [f"{where}: {name} is {total} lines, want at most 3"] if total > 3 else []


def check_example(data):
    if not isinstance(data, dict):
        return ["example is not an object"]
    found = text_field("example", "lang", data.get("lang"), 40)
    found += lines_field("example", "normal", data.get("normal"))
    attack = data.get("attack")
    more = lines_field("example", "attack", attack)
    mark = data.get("mark")
    if not isinstance(mark, str) or not mark:
        more.append("example: mark is missing")
    elif not more and mark not in attack:
        more.append("example: mark is not part of attack")
    return found + more


def check_path(data):
    if not isinstance(data, dict):
        return ["path is not an object"]
    steps = data.get("steps")
    found = count("path", steps, "step", 2, 6)
    if not isinstance(steps, list):
        return found
    zones = []
    for n, step in enumerate(steps, 1):
        where = f"path step {n}"
        if not isinstance(step, dict):
            found.append(f"{where}: is not an object")
            continue
        found += text_field(where, "actor", step.get("actor"), 40)
        found += text_field(where, "step", step.get("step"), 120)
        if "crosses" in step:
            found += text_field(where, "crosses", step.get("crosses"), 60)
        zone = step.get("zone")
        more = text_field(where, "zone", zone, 40)
        found += more
        if more or (zones and zones[-1] == zone):
            continue
        if zone in zones:
            found.append(f"{where}: zone {zone} was left earlier")
        zones.append(zone)
    if len(set(zones)) > 3:
        found.append(f"path has {len(set(zones))} zones, want 1 to 3")
    return found


def check_reach(where, data):
    if not isinstance(data, dict):
        return [f"{where} is not an object"]
    found = []
    for name, least in (("now", 1), ("afterFix", 0)):
        items = data.get(name)
        more = count(where, items, f"{name} item", least, 4)
        found += more
        if not more:
            for n, item in enumerate(items, 1):
                found += text_field(where, f"{name} item {n}", item, 120)
    return found


def check_source(text):
    sections = re.findall(r"^### Source[ \t]*\n(.*?)(?=^##|\Z)", text, re.M | re.S)
    if len(sections) != 1:
        return [f"found {len(sections)} Source sections, want 1"]
    links = re.findall(r"\[([^\]]*)\]\(([^)]*)\)", sections[0])
    if len(links) != 1:
        return [f"Source has {len(links)} links, want 1"]
    title, url = links[0]
    found = text_field("Source", "title", title, 120)
    if not re.fullmatch(r"https://\S+", url):
        found.append("Source link is not an https URL")
    return found


def check_findings(text):
    parts = re.split(r"^## Findings[ \t]*$", text, maxsplit=1, flags=re.M)
    entries = re.split(r"^### ", parts[1], flags=re.M)[1:] if len(parts) == 2 else []
    found = []
    for n, entry in enumerate(entries, 1):
        where = f"finding {n} reach"
        reaches = blocks(entry, "maple-reach")
        if len(reaches) > 1:
            found.append(f"finding {n} has {len(reaches)} maple-reach blocks, want at most 1")
            continue
        for raw in reaches:
            try:
                found += check_reach(where, json.loads(raw))
            except json.JSONDecodeError:
                found.append(f"{where} block is not valid JSON")
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
        words = [len(c.split()) for c in choices if isinstance(c, str)]
        if words and max(words) - min(words) > 3:
            found.append(
                f"{where}: choices are {min(words)} to {max(words)} words, want them within 3 of each other"
            )
        answer = item.get("answer")
        if not is_int(answer) or not 0 <= answer < len(choices):
            found.append(f"{where}: answer {answer} is not a choice index ({len(choices)} choices)")
    answers = [q.get("answer") for q in questions if isinstance(q, dict) and is_int(q.get("answer"))]
    if len(questions) >= 3 and len(answers) == len(questions) and len(set(answers)) == 1:
        found.append(f"quiz: every answer is {answers[0]}, want the right choice in different places")
    return found


def check(text):
    if not re.search(r"^## Lesson[ \t]*$", text, re.M):
        return [PREFIX + p for p in check_findings(text)]
    found = []
    kinds = (
        ("maple-example", check_example),
        ("maple-path", check_path),
        ("maple-trace", check_trace),
        ("maple-quiz", check_quiz),
    )
    for kind, checker in kinds:
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
    found += check_source(text)
    found += check_findings(text)
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
