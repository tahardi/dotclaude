import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md2adf import convert  # noqa: E402

USAGE = """usage:
  python3 cards.py check MANIFEST         validate the manifest, plan, and spec; print the card map; change nothing
  python3 cards.py apply MANIFEST         check, then create epics, cards, links, and the first sprint in Jira;
                                          safe to re-run, it resumes from MANIFEST.state.json
"""

POINTS = {1, 2, 3, 5, 8}
SCRIPT_LABELS = {"parallelizable", "needs-refinement"}
ADF_LIMIT = 30000
CARD_HEADING = re.compile(r"^### (T-[A-Z]+\d+): (.+)$", re.M)
REQ = re.compile(r"\bR-[A-Z]+-\d+\b")
TASK_REF = re.compile(r"\bT-[A-Z]+\d+\b")


def load(path):
    with open(os.path.expanduser(path)) as f:
        return f.read()


def plan_cards(plan):
    out = {}
    matches = list(CARD_HEADING.finditer(plan))
    for m in matches:
        rest = plan[m.end():]
        stop = re.search(r"^(### |## |---$)", rest, re.M)
        out[m.group(1)] = (m.group(2).strip(), (rest[: stop.start()] if stop else rest).strip())
    return out


def global_constraints(plan):
    m = re.search(r"^## Global Constraints\n(.*?)(?=^## |\Z)", plan, re.S | re.M)
    return m.group(1).strip() if m else ""


def files_of(body):
    m = re.search(r"\*\*Files:\*\*\n(.*?)(?=\n\s*\n|\n- \[ \])", body, re.S)
    if not m:
        return None
    paths = set()
    for line in m.group(1).split("\n"):
        line = line.strip()
        if re.match(r"- (Create|Modify|Delete):", line):
            paths |= set(re.findall(r"`([^`]+)`", line))
    return paths


def ancestors(cards):
    blocked_by = {c["id"]: c.get("blocked_by", []) for c in cards}
    memo = {}

    def walk(cid, seen):
        if cid in memo:
            return memo[cid]
        if cid in seen:
            raise ValueError(f"blocker cycle through {cid}")
        out = set()
        for b in blocked_by.get(cid, []):
            out |= {b} | walk(b, seen | {cid})
        memo[cid] = out
        return out

    return {cid: walk(cid, set()) for cid in blocked_by}


def depth(cid, cards_by_id, memo=None):
    memo = {} if memo is None else memo
    if cid not in memo:
        blockers = cards_by_id[cid].get("blocked_by", [])
        memo[cid] = 1 + max((depth(b, cards_by_id, memo) for b in blockers), default=-1)
    return memo[cid]


def parallelizable(cards, files):
    anc = ancestors(cards)
    out = set()
    for c in cards:
        mine = files.get(c["id"])
        if not mine:
            continue
        concurrent = [
            o["id"] for o in cards
            if o["id"] != c["id"] and o["id"] not in anc[c["id"]] and c["id"] not in anc[o["id"]]
        ]
        if all(not (mine & (files.get(o) or set())) for o in concurrent):
            out.add(c["id"])
    return out


def validate(manifest, plan, spec):
    errors = []
    for field in ("project", "plan", "plan_ref", "spec", "repo", "pre_pr", "epics", "cards", "sprint"):
        if field not in manifest:
            errors.append(f"manifest is missing {field!r}")
    if errors:
        return errors
    if not re.fullmatch(r"[A-Z][A-Z0-9]+", manifest["project"]):
        errors.append(f"project key {manifest['project']!r} is not a Jira key")
    epic_ids = [e["id"] for e in manifest["epics"]]
    card_ids = [c["id"] for c in manifest["cards"]]
    for dup in sorted({i for i in epic_ids + card_ids if (epic_ids + card_ids).count(i) > 1}):
        errors.append(f"id used twice: {dup}")
    sections = plan_cards(plan)
    if not global_constraints(plan):
        errors.append("plan has no ## Global Constraints section")
    for orphan in sorted(set(sections) - set(card_ids)):
        errors.append(f"plan task {orphan} is not in the manifest")
    for c in manifest["cards"]:
        cid = c["id"]
        if c.get("epic") not in epic_ids:
            errors.append(f"{cid}: epic {c.get('epic')!r} is not a manifest epic")
        if c.get("points") not in POINTS:
            errors.append(f"{cid}: points {c.get('points')!r} not in 1, 2, 3, 5, 8")
        for b in c.get("blocked_by", []):
            if b not in card_ids:
                errors.append(f"{cid}: blocker {b} is not a manifest card")
        for label in set(c.get("labels", [])) & SCRIPT_LABELS:
            errors.append(f"{cid}: label {label} is set by the script, remove it")
        if cid not in sections:
            errors.append(f"{cid}: plan has no heading '### {cid}: <Title>'")
            continue
        body = sections[cid][1]
        for part in ("**Goal:**", "**Acceptance criteria:**"):
            if part not in body:
                errors.append(f"{cid}: plan section has no {part}")
        if c.get("workflow", True):
            if not files_of(body):
                errors.append(f"{cid}: plan section has no **Files:** list with Create/Modify/Delete lines")
            if "**Step 1" not in body:
                errors.append(f"{cid}: plan section has no **Step 1** (test step first)")
        for ref in set(TASK_REF.findall(body)) - set(card_ids):
            errors.append(f"{cid}: mentions {ref}, which is not a manifest card")
    for f in manifest.get("future", []):
        if f.get("epic") not in epic_ids:
            errors.append(f"future card {f.get('title')!r}: epic {f.get('epic')!r} is not a manifest epic")
    try:
        ancestors(manifest["cards"])
    except ValueError as e:
        errors.append(str(e))
    sprint = manifest["sprint"].get("cards", [])
    for cid in sprint:
        if cid not in card_ids:
            errors.append(f"sprint card {cid} is not a manifest card")
            continue
        for b in next(c for c in manifest["cards"] if c["id"] == cid).get("blocked_by", []):
            if b not in sprint:
                errors.append(f"sprint card {cid} is blocked by {b}, which is not in the sprint")
    defined = set(re.findall(r"^\s*- \*\*(R-[A-Z]+-\d+):\*\*", spec, re.M))
    cited = {r for _, body in sections.values() for r in REQ.findall(body)}
    cited |= {r for f in manifest.get("future", []) for r in f.get("requirements", [])}
    for r in sorted(defined - cited):
        errors.append(f"requirement {r} is in no card and no future card")
    for r in sorted(cited - defined):
        errors.append(f"requirement {r} is cited but not defined in the spec")
    return errors


def card_map(manifest, plan):
    sections = plan_cards(plan)
    cards = manifest["cards"]
    by_id = {c["id"]: c for c in cards}
    files = {c["id"]: files_of(sections[c["id"]][1]) for c in cards}
    par = parallelizable(cards, files)
    rows = []
    for c in cards:
        labels = list(c.get("labels", [])) + (["parallelizable"] if c["id"] in par else [])
        rows.append({**c, "title": sections[c["id"]][0], "labels": labels, "depth": depth(c["id"], by_id)})
    return rows


def slug(title):
    return "-".join(re.sub(r"[^a-z0-9 ]+", "", title.lower()).split()[:3])


def describe(manifest, plan, row, keys):
    key = keys[row["id"]]
    lower = key.lower()
    repo = row.get("repo", manifest["repo"])
    path = f"~/Documents/code/{repo}"
    branch = f"{lower}-{slug(row['title'])}"
    blockers = ", ".join(keys[b] for b in row.get("blocked_by", [])) or "none"
    out = [f"**Plan:** {manifest['plan_ref']}, task {row['id']}.", "", f"**Blocked by:** {blockers}.", ""]
    if row.get("workflow", True):
        setup = row.get("setup", manifest.get("setup"))
        setup = f" {setup}" if setup else ""
        out += [
            "**Workflow:**",
            "",
            f"1. `git -C {path} fetch origin && git -C {path} worktree add ~/Documents/code/wts/{repo}-{branch} "
            f"-b {branch} --no-track origin/main`",
            f"2. Work only inside that worktree. Never commit to `main`.{setup}",
            "3. Follow the steps in order: write the test, see it fail, then implement.",
            f"4. `{row.get('pre_pr', manifest['pre_pr'])}` from the worktree root must exit 0.",
            f"5. Open the PR titled `[{key}] {row['title']}`, fill in the PR template, and link this card.",
            "",
        ]
    body = plan_cards(plan)[row["id"]][1]
    out += [TASK_REF.sub(lambda m: keys.get(m.group(0), m.group(0)), body), "", "### Global Constraints", ""]
    out.append(global_constraints(plan))
    return "\n".join(out)


def check(manifest_path):
    manifest = json.loads(load(manifest_path))
    plan = load(manifest.get("plan", "")) if manifest.get("plan") else ""
    spec = load(manifest.get("spec", "")) if manifest.get("spec") else ""
    errors = validate(manifest, plan, spec)
    if errors:
        print("\n".join(errors))
        sys.exit(f"{len(errors)} problems; fix them and run check again")
    rows = card_map(manifest, plan)
    sprint = set(manifest["sprint"]["cards"])
    for r in sorted(rows, key=lambda r: (r["depth"], card_index(manifest, r["id"]))):
        mark = "S" if r["id"] in sprint else " "
        blockers = ",".join(r.get("blocked_by", [])) or "-"
        labels = ",".join(r["labels"]) or "-"
        print(f"{mark} {r['id']:7} {r['points']}pt epic={r['epic']} blocked_by={blockers} labels={labels} {r['title']}")
    points = sum(r["points"] for r in rows if r["id"] in sprint)
    future = len(manifest.get("future", []))
    print(f"{len(rows)} cards, {future} future cards, sprint {len(sprint)} cards {points} points")
    return manifest, plan, rows


def card_index(manifest, cid):
    return [c["id"] for c in manifest["cards"]].index(cid)


def apply(manifest_path):
    import jira

    manifest, plan, rows = check(manifest_path)
    project = manifest["project"]
    state_path = os.path.expanduser(manifest_path) + ".state.json"
    state = json.loads(load(state_path)) if os.path.exists(state_path) else {}

    def save():
        with open(state_path, "w") as f:
            json.dump(state, f, indent=1)

    def create(summary, itype, md, labels, parent=None, points=None):
        fields = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": itype},
            "description": convert(md),
            "labels": labels,
        }
        if parent:
            fields["parent"] = {"key": parent}
        if points is not None:
            fields["customfield_10016"] = float(points)
        return jira.api("POST", "/rest/api/3/issue", {"fields": fields})["key"]

    for e in manifest["epics"]:
        if e["id"] not in state:
            color = jira.next_epic_color(project)
            state[e["id"]] = create(e["name"], "Epic", e["description"], [])
            save()
            jira.set_color(state[e["id"]], color)
            print("epic", state[e["id"]], e["name"])

    for r in rows:
        if r["id"] in state:
            continue
        key = create(r["title"], "Task", f"**Plan:** {manifest['plan_ref']}, task {r['id']}.", r["labels"],
                     state[r["epic"]], r["points"])
        state[r["id"]] = key
        save()
        print("card", key, r["title"])

    keys = {cid: k for cid, k in state.items() if not cid.startswith("_")}
    for r in rows:
        if r["id"] in state.get("_described", []):
            continue
        key = keys[r["id"]]
        md = describe(manifest, plan, r, keys)
        if len(json.dumps(convert(md))) > ADF_LIMIT:
            full = os.path.join(os.path.dirname(state_path), f"{key}-full-card.md")
            with open(full, "w") as f:
                f.write(md)
            attached = jira.api("GET", f"/rest/api/3/issue/{key}?fields=attachment")["fields"]["attachment"]
            if not any(a["filename"] == os.path.basename(full) for a in attached):
                jira.attach(key, full)
            md = md.split("- [ ] **Step 1", 1)[0] + f"\n\n**Full card:** every step is in the attached `{key}-full-card.md`."
        jira.api("PUT", f"/rest/api/3/issue/{key}", {"fields": {"description": convert(md)}})
        state.setdefault("_described", []).append(r["id"])
        save()

    for f in manifest.get("future", []):
        if f["title"] not in state:
            text = f["description"] + " Refine this card with /refine before implementing it."
            state[f["title"]] = create(f["title"], "Task", text, ["needs-refinement"], state[f["epic"]])
            save()
            print("future", state[f["title"]], f["title"])

    done = {tuple(p) for p in state.get("_links", [])}
    for r in rows:
        for b in r.get("blocked_by", []):
            pair = (keys[b], keys[r["id"]])
            if pair not in done:
                jira.link(*pair)
                done.add(pair)
                state["_links"] = sorted(done)
                save()
    for r in rows:
        want = {keys[b] for b in r.get("blocked_by", [])}
        links = jira.api("GET", f"/rest/api/3/issue/{keys[r['id']]}?fields=issuelinks")["fields"]["issuelinks"]
        got = {l["inwardIssue"]["key"] for l in links if l["type"]["name"] == "Blocks" and "inwardIssue" in l}
        if got != want:
            sys.exit(f"checking links on {keys[r['id']]}: blocked by {sorted(got)}, want {sorted(want)}")
    print(f"links verified: {len(done)}")

    if "_sprint" not in state:
        board = jira.board_of(project)
        if not jira.sprints(board, "active"):
            opts = {"--goal": manifest["sprint"].get("goal", "")}
            if manifest["sprint"].get("start"):
                opts["--start"] = manifest["sprint"]["start"]
            jira.sprint_create(project, opts)
        order = sorted(manifest["sprint"]["cards"],
                       key=lambda cid: (next(r["depth"] for r in rows if r["id"] == cid), card_index(manifest, cid)))
        jira.sprint_add(project, [keys[cid] for cid in order])
        state["_sprint"] = [keys[cid] for cid in order]
        save()

    keyed = CARD_HEADING.sub(lambda m: f"### {m.group(1)}: {m.group(2)} ({keys[m.group(1)]})", plan)
    keyed_path = os.path.expanduser(manifest["plan"])[:-3] + ".keyed.md"
    with open(keyed_path, "w") as f:
        f.write(keyed)
    print(f"plan with card keys: {keyed_path}")
    ready = [keys[r["id"]] for r in rows if r["id"] in manifest["sprint"]["cards"] and not r.get("blocked_by")]
    print(f"start now: {', '.join(ready)}")


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "check":
        check(args[1])
    elif len(args) == 2 and args[0] == "apply":
        sys.path.insert(0, os.path.expanduser("~/.claude/skills/card/scripts"))
        apply(args[1])
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
