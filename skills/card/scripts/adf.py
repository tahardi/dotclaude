import re

SAFE_LANGUAGE = re.compile(r"[\w+#.-]+")


def backticks(code, minimum):
    return "`" * max(minimum, max((len(run) for run in re.findall(r"`+", code)), default=0) + 1)


def inline_code(code):
    fence = backticks(code, 1)
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{fence}{pad}{code}{pad}{fence}"


def label(language):
    words = re.split(r"[ \t]+", language.strip())
    return words[0] if SAFE_LANGUAGE.fullmatch(words[0]) else ""


def text_of(node):
    if node.get("type") == "text":
        t = node.get("text", "")
        marks = {m["type"] for m in node.get("marks", [])}
        if "code" in marks:
            return inline_code(t)
        if "strong" in marks:
            return f"**{t}**"
        if "strike" in marks:
            return f"~~{t}~~"
        href = next((m.get("attrs", {}).get("href") for m in node.get("marks", []) if m["type"] == "link"), None)
        if href and href != t:
            return f"[{t}]({href})"
        return t
    if node.get("type") == "hardBreak":
        return "\n"
    return "".join(text_of(c) for c in node.get("content", []))


def render(node, indent=""):
    kind = node.get("type")
    content = node.get("content", [])
    if kind == "doc":
        return "\n\n".join(render(c) for c in content)
    if kind == "heading":
        return "#" * node["attrs"]["level"] + " " + text_of(node)
    if kind == "paragraph":
        return indent + text_of(node)
    if kind == "codeBlock":
        code = text_of(node)
        fence = backticks(code, 3)
        body = "\n".join(indent + row if row else row for row in code.split("\n"))
        return f"{indent}{fence}{label((node.get('attrs') or {}).get('language') or '')}\n{body}\n{indent}{fence}"
    if kind in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(content, 1):
            bullet = f"{i}. " if kind == "orderedList" else "- "
            parts = [render(c, indent + "   ") for c in item.get("content", [])]
            first = parts[0].lstrip() if parts else ""
            lines.append(indent + bullet + first + "".join("\n" + p for p in parts[1:]))
        return "\n".join(lines)
    return indent + text_of(node)
