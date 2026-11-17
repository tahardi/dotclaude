import re

URL = r"https?://[^\s<>()]*[^\s<>().,;:!?'\"]"
INLINE = re.compile(rf"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|{URL})")
LIST = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")


def inline(text):
    out = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            for n in inline(part[2:-2]):
                marks = n.setdefault("marks", [])
                if not any(m["type"] == "code" for m in marks):
                    marks.append({"type": "strong"})
                out.append(n)
        elif part.startswith("`") and part.endswith("`") and len(part) > 1:
            if part[1:-1]:
                out.append({"type": "text", "text": part[1:-1], "marks": [{"type": "code"}]})
        elif part.startswith("[") and "](" in part:
            label, url = part[1:].split("](", 1)
            out.append({"type": "text", "text": label, "marks": [{"type": "link", "attrs": {"href": url[:-1]}}]})
        elif re.fullmatch(URL, part):
            out.append({"type": "text", "text": part, "marks": [{"type": "link", "attrs": {"href": part}}]})
        else:
            out.append({"type": "text", "text": part})
    return out


def para(text):
    nodes = inline(text)
    return {"type": "paragraph", "content": nodes} if nodes else None


def fence(lines, i):
    line = lines[i]
    lang = line.strip()[3:].strip() or None
    indent = len(line) - len(line.lstrip())
    code = []
    i += 1
    while i < len(lines) and not lines[i].strip().startswith("```"):
        code.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
        i += 1
    node = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code) or " "}]}
    if lang:
        node["attrs"] = {"language": lang}
    return node, i + 1


def convert(md):
    lines = md.split("\n")
    doc = []
    i = 0
    buf = []

    def flush():
        if buf:
            p = para(" ".join(s.strip() for s in buf))
            if p:
                doc.append(p)
            buf.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            node, i = fence(lines, i)
            doc.append(node)
            continue
        if not stripped:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            doc.append({"type": "heading", "attrs": {"level": len(m.group(1))}, "content": inline(m.group(2))})
            i += 1
            continue
        if stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            doc.append({"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(rows)}]})
            continue
        if LIST.match(line):
            flush()
            node, i = parse_list(lines, i)
            doc.append(node)
            continue
        buf.append(line)
        i += 1
    flush()
    return {"type": "doc", "version": 1, "content": doc}


def parse_list(lines, i):
    ordered = LIST.match(lines[i]).group(2)[0].isdigit()
    items = []
    gap = False
    while i < len(lines):
        line = lines[i]
        m = LIST.match(line)
        if not line.strip():
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j == len(lines) or not (lines[j].startswith(" ") or LIST.match(lines[j])):
                break
            i, gap = j, True
            continue
        if m and (m.group(1) or m.group(2)[0].isdigit() == ordered):
            items.append({"depth": 1 if len(m.group(1)) >= 2 else 0, "ordered": m.group(2)[0].isdigit(),
                          "text": m.group(3), "blocks": []})
            i, gap = i + 1, False
        elif m or not line.startswith(" "):
            break
        elif line.strip().startswith("```"):
            node, i = fence(lines, i)
            items[-1]["blocks"].append(node)
        elif gap or (items[-1]["blocks"] and items[-1]["blocks"][-1]["type"] != "paragraph"):
            items[-1]["blocks"].append(para(line.strip()))
            i, gap = i + 1, False
        elif items[-1]["blocks"]:
            items[-1]["blocks"][-1]["content"] += inline(" " + line.strip())
            i += 1
        else:
            items[-1]["text"] += " " + line.strip()
            i += 1
    return build_list(items, ordered), i


def build_list(items, ordered):
    root = {"type": "orderedList" if ordered else "bulletList", "content": []}
    for entry in items:
        p = para(entry["text"]) or {"type": "paragraph", "content": []}
        if entry["depth"] == 0 or not root["content"]:
            root["content"].append({"type": "listItem", "content": [p, *entry["blocks"]]})
        else:
            parent = root["content"][-1]["content"]
            if parent[-1]["type"] not in ("bulletList", "orderedList"):
                parent.append({"type": "orderedList" if entry["ordered"] else "bulletList", "content": []})
            parent[-1]["content"].append({"type": "listItem", "content": [p, *entry["blocks"]]})
    return root
