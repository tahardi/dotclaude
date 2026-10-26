import re
import sys

USAGE = "usage: python3 check_spec.py SPEC [--approved]"

SECTIONS = {
    "Purpose": [],
    "Users and Data": [],
    "Requirements": [],
    "Architecture": [],
    "Security and Privacy": ["Threat Model", "Data Handling", "Secrets", "Network Exposure", "Supply Chain", "Host"],
    "Operations": ["Deployment", "Observability", "Upgrades and Migrations", "Backup and Recovery"],
    "Testing": [],
    "Out of Scope": [],
    "Open Questions": [],
}
KINDS = ["F", "SEC", "PRIV", "OPS"]
DEFINED = re.compile(r"^\s*- \*\*(R-[A-Z]+-\d+):\*\*", re.M)


def sections(text, level):
    marker = "#" * level + " "
    out, name = {}, None
    for line in text.split("\n"):
        if line.startswith(marker):
            name = line[len(marker):].strip()
            out[name] = []
        elif line.startswith("#" * (level - 1) + " ") and level > 2:
            name = None
        elif name is not None:
            out[name].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def requirement_ids(text):
    return DEFINED.findall(text)


def problems(text, approved):
    found = []
    top = sections(text, 2)
    for name, subs in SECTIONS.items():
        if name not in top:
            found.append(f"missing section: ## {name}")
            continue
        if not top[name]:
            found.append(f"empty section: ## {name}")
        inner = sections(top[name], 3)
        for sub in subs:
            if sub not in inner:
                found.append(f"missing section: ### {sub} under ## {name}")
            elif not inner[sub]:
                found.append(f"empty section: ### {sub} under ## {name}")
    ids = requirement_ids(text)
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        found.append(f"requirement defined twice: {dup}")
    for kind in KINDS:
        if not any(i.startswith(f"R-{kind}-") for i in ids):
            found.append(f"no R-{kind}-n requirement defined")
    for bad in sorted({i for i in ids if i.split("-")[1] not in KINDS}):
        found.append(f"unknown requirement kind: {bad} (use {', '.join('R-' + k for k in KINDS)})")
    for n, line in enumerate(text.split("\n"), 1):
        if re.search(r"\b(TBD|TODO|XXX)\b", line) or line.startswith("> Guide:"):
            found.append(f"line {n} is unfinished: {line.strip()[:80]}")
    if approved:
        if not re.search(r"^Status: Approved \d{4}-\d{2}-\d{2}$", text, re.M):
            found.append("missing line: Status: Approved YYYY-MM-DD")
        if top.get("Open Questions", "").rstrip(".") != "None":
            found.append("## Open Questions must say None before approval")
    return found


def main():
    args = sys.argv[1:]
    if not args or len(args) > 2 or (len(args) == 2 and args[1] != "--approved"):
        sys.exit(USAGE)
    with open(args[0]) as f:
        text = f.read()
    found = problems(text, len(args) == 2)
    for p in found:
        print(p)
    if found:
        sys.exit(1)
    print(f"spec ok: {len(requirement_ids(text))} requirements")


if __name__ == "__main__":
    main()
