import re

INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
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
        else:
            out.append({"type": "text", "text": part})
    return out


def para(text):
    nodes = inline(text)
    return {"type": "paragraph", "content": nodes} if nodes else None


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
            lang = stripped[3:].strip() or None
            indent = len(line) - len(line.lstrip())
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
                i += 1
            i += 1
            node = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code) or " "}]}
            if lang:
                node["attrs"] = {"language": lang}
            doc.append(node)
            continue
        if not stripped:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            level = min(len(m.group(1)) + 1, 6)
            doc.append({"type": "heading", "attrs": {"level": level}, "content": inline(m.group(2))})
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
        m = LIST.match(line)
        if m:
            flush()
            items = []
            while i < len(lines):
                m = LIST.match(lines[i])
                if m:
                    depth = 1 if len(m.group(1)) >= 2 else 0
                    items.append([depth, m.group(2)[0].isdigit(), m.group(3)])
                    i += 1
                elif lines[i].strip() and not lines[i].strip().startswith("```") and lines[i].startswith(" ") and items:
                    items[-1][2] += " " + lines[i].strip()
                    i += 1
                else:
                    break
            doc.append(build_list(items))
            continue
        buf.append(line)
        i += 1
    flush()
    return {"type": "doc", "version": 1, "content": doc}


def build_list(items):
    root = {"type": "orderedList" if items[0][1] else "bulletList", "content": []}
    for depth, ordered, text in items:
        p = para(text) or {"type": "paragraph", "content": []}
        if depth == 0 or not root["content"]:
            root["content"].append({"type": "listItem", "content": [p]})
        else:
            parent = root["content"][-1]["content"]
            if parent[-1]["type"] not in ("bulletList", "orderedList"):
                parent.append({"type": "orderedList" if ordered else "bulletList", "content": []})
            parent[-1]["content"].append({"type": "listItem", "content": [p]})
    return root
