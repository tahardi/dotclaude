import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USAGE = """usage:
  python3 jira.py get KEY                 print card as markdown with status, parent, links
  python3 jira.py transition KEY STATUS   move card (e.g. "In Progress", "In Review")
  python3 jira.py comment KEY TEXT        add a plain-text comment (URLs become links)
  python3 jira.py assign KEY              assign to the token's user unless already assigned to them
  python3 jira.py strike-blockers KEY     strike through Done blockers in the description's "Blocked by" line
  python3 jira.py open-siblings KEY       list cards in KEY's epic that are not Done
  python3 jira.py create PROJECT SUMMARY [--epic KEY] [--labels a,b] [--points N] [--blocked-by K1,K2] [--blocks K3]
                                          [--type Epic] [--color C]
                                          create a Task, or the --type given; the description is read from stdin;
                                          an Epic gets --color or the first color no other open epic uses;
                                          prints the new key
  python3 jira.py test-card PROJECT SUMMARY
                                          create a "[TEST]" Task labeled test-card, assigned to the token's user,
                                          in the project's active sprint; the description is Markdown read from
                                          stdin (# headings, - and 1. lists); prints the new key last
  python3 jira.py list PROJECT [--label X]
                                          list open cards in PROJECT, optionally only those labeled X
  python3 jira.py update KEY [--description -] [--add-labels a,b] [--remove-labels c,d] [--points N] [--epic KEY]
                                          update a card; --description - reads the description from stdin
  python3 jira.py link BLOCKER BLOCKED    mark BLOCKER as blocking BLOCKED
  python3 jira.py attach KEY FILE         attach FILE to KEY
  python3 jira.py create-project KEY NAME create a team-managed Scrum project led by the token's user; prints the
                                          board id and fails if the board lacks an In Review column
  python3 jira.py sprint-create PROJECT [--start YYYY-MM-DD] [--goal TEXT]
                                          create the next two-week sprint on the shared cadence (Mondays from
                                          2026-09-28, 13:00 to 21:00 UTC), reusing an undated future sprint such
                                          as the one a new board starts with; starts it when no sprint is active
                                          and its start has passed; prints the sprint id
  python3 jira.py sprint-add PROJECT KEY [KEY ...]
                                          add cards to the active sprint (else the newest future sprint), assign
                                          each to the token's user, and rank them top to bottom in the order given
"""

IMPACT_PREFIX = "Card impact from"
COLORS = [
    "purple", "blue", "green", "teal", "yellow", "orange", "grey",
    "dark_purple", "dark_blue", "dark_green", "dark_teal", "dark_yellow", "dark_orange", "dark_grey",
]
CADENCE_ANCHOR = "2026-09-28"
CADENCE_DAYS = 14


def load_env():
    env = {}
    with open(os.path.expanduser("~/.config/jira/env")) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


ENV = load_env()
AUTH = base64.b64encode(f"{ENV['JIRA_EMAIL']}:{ENV['JIRA_TOKEN']}".encode()).decode()


def api(method, path, body=None):
    req = urllib.request.Request(
        ENV["JIRA_SITE"] + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {AUTH}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        sys.exit(f"jira {method} {path} failed: {e.code} {e.read().decode()[:500]}")


def text_of(node):
    if node.get("type") == "text":
        t = node.get("text", "")
        marks = {m["type"] for m in node.get("marks", [])}
        if "code" in marks:
            return f"`{t}`"
        if "strong" in marks:
            return f"**{t}**"
        if "strike" in marks:
            return f"~~{t}~~"
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
        lang = (node.get("attrs") or {}).get("language") or ""
        return f"{indent}```{lang}\n{text_of(node)}\n{indent}```"
    if kind in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(content, 1):
            bullet = f"{i}. " if kind == "orderedList" else "- "
            parts = [render(c, indent + "   ") for c in item.get("content", [])]
            first = parts[0].lstrip() if parts else ""
            lines.append(indent + bullet + first + "".join("\n" + p for p in parts[1:]))
        return "\n".join(lines)
    return indent + text_of(node)


def get(key):
    fields = "summary,status,description,parent,labels,issuelinks,customfield_10016,assignee,created,attachment"
    issue = api("GET", f"/rest/api/3/issue/{key}?fields={fields}")
    f = issue["fields"]
    print(f"# {key}: {f['summary']}")
    print(f"Status: {f['status']['name']}")
    print(f"Created: {f['created'][:10]}")
    if f.get("parent"):
        print(f"Epic: {f['parent']['key']} {f['parent']['fields']['summary']}")
    print(f"Assignee: {(f.get('assignee') or {}).get('displayName', 'unassigned')}")
    print(f"Labels: {', '.join(f.get('labels') or []) or 'none'}")
    print(f"Points: {f.get('customfield_10016')}")
    blocked_by, blocks = [], []
    for link in f.get("issuelinks") or []:
        if link["type"]["name"] != "Blocks":
            continue
        if "inwardIssue" in link:
            other = link["inwardIssue"]
            blocked_by.append(f"{other['key']} ({other['fields']['status']['name']})")
        if "outwardIssue" in link:
            other = link["outwardIssue"]
            blocks.append(f"{other['key']} ({other['fields']['status']['name']})")
    print(f"Blocked by: {', '.join(blocked_by) or 'none'}")
    print(f"Blocks: {', '.join(blocks) or 'none'}")
    print(f"URL: {ENV['JIRA_SITE']}/browse/{key}")
    print()
    print(render(f["description"]) if f.get("description") else "(no description)")
    for a in f.get("attachment") or []:
        if a["filename"].endswith("-full-card.md"):
            req = urllib.request.Request(a["content"], headers={"Authorization": f"Basic {AUTH}"})
            with urllib.request.urlopen(req) as resp:
                print()
                print(f"## Full card ({a['filename']})")
                print("This is the whole card. Follow it where it repeats the description.")
                print()
                print(resp.read().decode())
    comments =api("GET", f"/rest/api/3/issue/{key}/comment?maxResults=100")["comments"]
    amendments = [render(c["body"]) for c in comments if render(c["body"]).startswith(IMPACT_PREFIX)]
    if amendments:
        print()
        print("## Amendments")
        print("These override the description where they conflict.")
        for a in amendments:
            print()
            print(a)


def transition(key, status):
    options = api("GET", f"/rest/api/3/issue/{key}/transitions")["transitions"]
    match = [t for t in options if t["to"]["name"].lower() == status.lower()]
    if not match:
        sys.exit(f"no transition to {status!r}; available: {', '.join(t['to']['name'] for t in options)}")
    api("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": match[0]["id"]}})
    print(f"{key} -> {match[0]['to']['name']}")


def text_doc(text):
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        nodes = []
        for j, line in enumerate(block.split("\n")):
            if j:
                nodes.append({"type": "hardBreak"})
            for part in re.split(r"(https?://\S+)", line):
                if not part:
                    continue
                if part.startswith("http"):
                    nodes.append({"type": "text", "text": part, "marks": [{"type": "link", "attrs": {"href": part}}]})
                else:
                    nodes.append({"type": "text", "text": part})
        if nodes:
            paragraphs.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "version": 1, "content": paragraphs}


def comment(key, text):
    api("POST", f"/rest/api/3/issue/{key}/comment", {"body": text_doc(text)})
    print(f"commented on {key}")


def open_siblings(key):
    parent = api("GET", f"/rest/api/3/issue/{key}?fields=parent")["fields"].get("parent")
    if not parent:
        print(f"{key} has no epic")
        return
    jql = f'parent = {parent["key"]} AND statusCategory != Done AND key != {key} ORDER BY key'
    query = urllib.parse.urlencode({"jql": jql, "fields": "summary,status", "maxResults": 100})
    for issue in api("GET", f"/rest/api/3/search/jql?{query}")["issues"]:
        print(f"{issue['key']} ({issue['fields']['status']['name']}) {issue['fields']['summary']}")


def list_cards(project, label):
    jql = f"project = {project} AND statusCategory != Done"
    if label:
        jql += f' AND labels = "{label}"'
    jql += " ORDER BY key"
    query = urllib.parse.urlencode({"jql": jql, "fields": "summary,status,issuetype,parent", "maxResults": 100})
    for issue in api("GET", f"/rest/api/3/search/jql?{query}")["issues"]:
        f = issue["fields"]
        epic = (f.get("parent") or {}).get("key", "none")
        print(f"{issue['key']} {f['issuetype']['name']} ({f['status']['name']}) epic={epic} {f['summary']}")


def update(key, opts):
    fields, edits = {}, {}
    if opts.get("--description") == "-":
        fields["description"] = text_doc(sys.stdin.read())
    if "--epic" in opts:
        fields["parent"] = {"key": opts["--epic"]}
    if "--points" in opts:
        fields["customfield_10016"] = float(opts["--points"])
    labels = [{"add": x} for x in opts.get("--add-labels", "").split(",") if x]
    labels += [{"remove": x} for x in opts.get("--remove-labels", "").split(",") if x]
    if labels:
        edits["labels"] = labels
    if not fields and not edits:
        sys.exit(f"updating {key}: nothing to update")
    api("PUT", f"/rest/api/3/issue/{key}", {"fields": fields, "update": edits})
    print(f"updated {key}")


def link(blocker, blocked):
    api("POST", "/rest/api/3/issueLink", {
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": blocker},
        "outwardIssue": {"key": blocked},
    })
    print(f"{blocker} blocks {blocked}")


def create(project, summary, opts):
    fields = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": opts.get("--type", "Task")},
        "description": text_doc(sys.stdin.read()),
        "labels": [x for x in opts.get("--labels", "").split(",") if x],
    }
    if "--epic" in opts:
        fields["parent"] = {"key": opts["--epic"]}
    if "--points" in opts:
        fields["customfield_10016"] = float(opts["--points"])
    color = opts.get("--color") or (next_epic_color(project) if fields["issuetype"]["name"] == "Epic" else None)
    new = api("POST", "/rest/api/3/issue", {"fields": fields})["key"]
    if color:
        set_color(new, color)
    links = [(b, new) for b in opts.get("--blocked-by", "").split(",") if b]
    links += [(new, b) for b in opts.get("--blocks", "").split(",") if b]
    for blocker, blocked in links:
        link(blocker, blocked)
    print(new)


def markdown_doc(text):
    content = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        heading = re.match(r"(#{1,6}) (.+)", block)
        if heading and len(lines) == 1:
            content.append({"type": "heading", "attrs": {"level": len(heading[1])}, "content": [{"type": "text", "text": heading[2]}]})
        elif all(re.match(r"[-*] ", line) for line in lines):
            items = [{"type": "listItem", "content": text_doc(line[2:])["content"]} for line in lines]
            content.append({"type": "bulletList", "content": items})
        elif all(re.match(r"\d+\. ", line) for line in lines):
            items = [{"type": "listItem", "content": text_doc(line.split(" ", 1)[1])["content"]} for line in lines]
            content.append({"type": "orderedList", "content": items})
        else:
            content += text_doc(block)["content"]
    return {"type": "doc", "version": 1, "content": content}


def test_card(project, summary):
    fields = {
        "project": {"key": project},
        "summary": summary if summary.startswith("[TEST] ") else f"[TEST] {summary}",
        "issuetype": {"name": "Task"},
        "description": markdown_doc(sys.stdin.read()),
        "labels": ["test-card"],
    }
    new = api("POST", "/rest/api/3/issue", {"fields": fields})["key"]
    assign(new)
    board = api("GET", f"/rest/agile/1.0/board?projectKeyOrId={project}")["values"][0]["id"]
    sprints = api("GET", f"/rest/agile/1.0/board/{board}/sprint?state=active")["values"]
    if sprints:
        api("POST", f"/rest/agile/1.0/sprint/{sprints[0]['id']}/issue", {"issues": [new]})
        print(f"{new} added to {sprints[0]['name']}")
    else:
        print(f"{new} not in a sprint: {project} has no active sprint")
    print(new)


def assign(key):
    me = api("GET", "/rest/api/3/myself")
    current = api("GET", f"/rest/api/3/issue/{key}?fields=assignee")["fields"].get("assignee")
    if current and current["accountId"] == me["accountId"]:
        print(f"{key} already assigned to {me['displayName']}")
        return
    api("PUT", f"/rest/api/3/issue/{key}/assignee", {"accountId": me["accountId"]})
    print(f"{key} assigned to {me['displayName']}")


def strike_text(node, keys):
    out = []
    pattern = re.compile("(" + "|".join(re.escape(k) for k in keys) + ")(?![0-9])")
    for child in node.get("content", []):
        if child.get("type") != "text":
            strike_text(child, keys)
            out.append(child)
            continue
        marks = child.get("marks", [])
        if any(m["type"] == "strike" for m in marks):
            out.append(child)
            continue
        for i, part in enumerate(pattern.split(child["text"])):
            if not part:
                continue
            extra = [{"type": "strike"}] if i % 2 else []
            piece = {"type": "text", "text": part}
            if marks or extra:
                piece["marks"] = marks + extra
            out.append(piece)
    node["content"] = out


def strike_blockers(key):
    issue = api("GET", f"/rest/api/3/issue/{key}?fields=description,issuelinks")
    done = [
        link["inwardIssue"]["key"]
        for link in issue["fields"].get("issuelinks") or []
        if link["type"]["name"] == "Blocks"
        and "inwardIssue" in link
        and link["inwardIssue"]["fields"]["status"]["statusCategory"]["key"] == "done"
    ]
    description = issue["fields"].get("description")
    if not done or not description:
        print("nothing to strike")
        return
    for paragraph in description.get("content", []):
        if paragraph.get("type") == "paragraph" and text_of(paragraph).lstrip("*~").startswith("Blocked by"):
            strike_text(paragraph, done)
    api("PUT", f"/rest/api/3/issue/{key}", {"fields": {"description": description}})
    print(f"struck through {', '.join(done)} in {key}")


def search(jql, fields):
    issues, token = [], None
    while True:
        params = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            params["nextPageToken"] = token
        page = api("GET", f"/rest/api/3/search/jql?{urllib.parse.urlencode(params)}")
        issues += page["issues"]
        token = page.get("nextPageToken")
        if not token:
            return issues


def next_epic_color(project):
    jql = f"project = {project} AND issuetype = Epic AND statusCategory != Done"
    used = {i["fields"].get("customfield_10017") for i in search(jql, "customfield_10017")}
    free = [c for c in COLORS if c not in used]
    if not free:
        sys.exit(f"choosing an epic color: all {len(COLORS)} colors are used by open {project} epics")
    return free[0]


def set_color(key, color):
    if color not in COLORS:
        sys.exit(f"setting {key} color: {color!r} is not one of {', '.join(COLORS)}")
    api("PUT", f"/rest/api/3/issue/{key}", {"fields": {"customfield_10017": color}})
    print(f"{key} color {color}")


def attach(key, path):
    boundary = "----jira" + os.urandom(8).hex()
    name = os.path.basename(path)
    with open(path, "rb") as f:
        payload = f.read()
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        ENV["JIRA_SITE"] + f"/rest/api/3/issue/{key}/attachments",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Basic {AUTH}",
            "X-Atlassian-Token": "no-check",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        urllib.request.urlopen(req).read()
    except urllib.error.HTTPError as e:
        sys.exit(f"attaching {name} to {key} failed: {e.code} {e.read().decode()[:500]}")
    print(f"attached {name} to {key}")


def board_of(project):
    boards = api("GET", f"/rest/agile/1.0/board?projectKeyOrId={project}")["values"]
    if not boards:
        sys.exit(f"finding {project} board: none exists")
    return boards[0]["id"]


def create_project(key, name):
    me = api("GET", "/rest/api/3/myself")["accountId"]
    api("POST", "/rest/api/3/project", {
        "key": key,
        "name": name,
        "projectTypeKey": "software",
        "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "leadAccountId": me,
        "assigneeType": "UNASSIGNED",
    })
    board = board_of(key)
    columns = [c["name"] for c in api("GET", f"/rest/agile/1.0/board/{board}/configuration")["columnConfig"]["columns"]]
    print(f"{key} board {board} columns {', '.join(columns)}")
    print(f"URL: {ENV['JIRA_SITE']}/jira/software/projects/{key}/boards/{board}/backlog")
    if "In Review" not in columns:
        sys.exit(f"creating {key}: board has no In Review column; add it in the Jira UI")


def cadence_start(today, active_end=None):
    import datetime as dt
    anchor = dt.date.fromisoformat(CADENCE_ANCHOR)
    start = anchor + dt.timedelta(days=(today - anchor).days // CADENCE_DAYS * CADENCE_DAYS)
    while active_end and start < active_end:
        start += dt.timedelta(days=CADENCE_DAYS)
    return start


def sprints(board, state=None):
    out, at = [], 0
    while True:
        query = f"startAt={at}&maxResults=50" + (f"&state={state}" if state else "")
        page = api("GET", f"/rest/agile/1.0/board/{board}/sprint?{query}")
        out += page["values"]
        if page.get("isLast", True):
            return out
        at += len(page["values"])


def sprint_create(project, opts):
    import datetime as dt
    board = board_of(project)
    existing = sprints(board)
    active = [s for s in existing if s["state"] == "active"]
    if "--start" in opts:
        start = dt.date.fromisoformat(opts["--start"])
    else:
        end = dt.date.fromisoformat(active[0]["endDate"][:10]) if active else None
        start = cadence_start(dt.datetime.now(dt.timezone.utc).date(), end)
    end = start + dt.timedelta(days=CADENCE_DAYS)
    undated = [s for s in existing if s["state"] == "future" and not s.get("startDate")]
    body = {
        "name": undated[0]["name"] if undated else f"{project} Sprint {len(existing) + 1}",
        "startDate": f"{start}T13:00:00.000Z",
        "endDate": f"{end}T21:00:00.000Z",
    }
    if opts.get("--goal"):
        body["goal"] = opts["--goal"]
    if undated:
        sprint = api("POST", f"/rest/agile/1.0/sprint/{undated[0]['id']}", body)
    else:
        sprint = api("POST", "/rest/agile/1.0/sprint", {**body, "originBoardId": board})
    print(f"{sprint['name']} {start} to {end}")
    if not active and start <= dt.datetime.now(dt.timezone.utc).date():
        api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", {"state": "active"})
        print(f"{sprint['name']} started")
    print(sprint["id"])


def sprint_add(project, keys):
    board = board_of(project)
    target = sprints(board, "active") or sprints(board, "future")[-1:]
    if not target:
        sys.exit(f"adding cards to a {project} sprint: no active or future sprint; run sprint-create first")
    sprint = target[0]
    api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}/issue", {"issues": keys})
    for key in keys:
        assign(key)
    for before, after in zip(keys, keys[1:]):
        api("PUT", "/rest/agile/1.0/issue/rank", {"issues": [after], "rankAfterIssue": before})
    print(f"added {', '.join(keys)} to {sprint['name']} in that order")


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "attach" and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", args[1]):
        attach(args[1], args[2])
        return
    if len(args) == 3 and args[0] == "create-project" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        create_project(args[1], args[2])
        return
    if len(args) >= 2 and args[0] == "sprint-create" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        rest = args[2:]
        if len(rest) % 2 or any(f not in ("--start", "--goal") for f in rest[::2]):
            sys.exit(USAGE)
        sprint_create(args[1], dict(zip(rest[::2], rest[1::2])))
        return
    if len(args) >= 3 and args[0] == "sprint-add" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        if not all(re.fullmatch(rf"{args[1]}-\d+", k) for k in args[2:]):
            sys.exit(USAGE)
        sprint_add(args[1], args[2:])
        return
    if len(args) >= 3 and args[0] == "create" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        rest = args[3:]
        if len(rest) % 2 or any(
            f not in ("--epic", "--labels", "--points", "--blocked-by", "--blocks", "--type", "--color")
            for f in rest[::2]
        ):
            sys.exit(USAGE)
        create(args[1], args[2], dict(zip(rest[::2], rest[1::2])))
        return
    if len(args) == 3 and args[0] == "test-card" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        test_card(args[1], args[2])
        return
    if len(args) in (2, 4) and args[0] == "list" and re.fullmatch(r"[A-Z][A-Z0-9]+", args[1]):
        if len(args) == 4 and args[2] != "--label":
            sys.exit(USAGE)
        list_cards(args[1], args[3] if len(args) == 4 else None)
        return
    if len(args) < 2 or not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", args[1]):
        sys.exit(USAGE)
    cmd, key = args[0], args[1]
    if cmd == "get" and len(args) == 2:
        get(key)
    elif cmd == "transition" and len(args) == 3:
        transition(key, args[2])
    elif cmd == "assign" and len(args) == 2:
        assign(key)
    elif cmd == "strike-blockers" and len(args) == 2:
        strike_blockers(key)
    elif cmd == "comment" and len(args) == 3:
        comment(key, args[2])
    elif cmd == "open-siblings" and len(args) == 2:
        open_siblings(key)
    elif cmd == "update" and len(args) % 2 == 0 and all(
        f in ("--description", "--add-labels", "--remove-labels", "--points", "--epic") for f in args[2::2]
    ):
        update(key, dict(zip(args[2::2], args[3::2])))
    elif cmd == "link" and len(args) == 3 and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", args[2]):
        link(key, args[2])
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
