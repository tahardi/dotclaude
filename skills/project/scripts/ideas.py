import re
import sys

USAGE = """usage:
  python3 ideas.py list < IDEAS            number each top-level idea in the Ideas note text
  python3 ideas.py remove N < IDEAS        print the note text without idea N and its sub-bullets
"""

TOOL_HEADER = re.compile(r"^# .+  \(.+\.md\)$")


def strip_tool_header(text):
    lines = text.split("\n")
    if lines and TOOL_HEADER.match(lines[0]):
        lines = lines[1:]
    return "\n".join(lines)


def split_ideas(text):
    head, ideas = [], []
    for line in text.split("\n"):
        if re.match(r"[-*] ", line):
            ideas.append([line])
        elif ideas and (line.startswith((" ", "\t")) or not line.strip()):
            ideas[-1].append(line)
        elif ideas:
            ideas.append([line])
        else:
            head.append(line)
    return head, ideas


def list_ideas(text):
    _, ideas = split_ideas(strip_tool_header(text))
    numbered = [idea for idea in ideas if re.match(r"[-*] ", idea[0])]
    return [f"{n}. {idea[0][2:].strip()}" for n, idea in enumerate(numbered, 1)]


def remove_idea(text, n):
    head, ideas = split_ideas(strip_tool_header(text))
    bullets = [i for i, idea in enumerate(ideas) if re.match(r"[-*] ", idea[0])]
    if not 1 <= n <= len(bullets):
        sys.exit(f"removing idea {n}: the note has {len(bullets)} ideas")
    ideas.pop(bullets[n - 1])
    return "\n".join(head + [line for idea in ideas for line in idea])


def main():
    args = sys.argv[1:]
    text = sys.stdin.read()
    if args == ["list"]:
        print("\n".join(list_ideas(text)))
    elif len(args) == 2 and args[0] == "remove" and args[1].isdigit():
        sys.stdout.write(remove_idea(text, int(args[1])))
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
