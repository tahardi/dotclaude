---
name: project
description: Use when the user runs /project to start a new personal project, from an idea in their Ideas note or a new one, through spec, plan, Jira cards, and the first sprint
argument-hint: "[idea]"
disable-model-invocation: true
---

# Start a Project

Turn an idea into an approved spec, an approved plan, a Jira project full of cards, and a running first sprint, so
the user can start `/card` sessions. Build every project as if real clients depended on it: security, privacy,
deployment, observability, upgrades, and backups are requirements from the first draft, not later cards.

`/project` creates the vault folder, the notes, the Jira project, the cards, and the sprint. It never creates a
repo, writes code, or sets up a dev environment. Those are cards, because each project's setup differs.

**Scripts** (in `~/.claude/skills/project/scripts/`, run with `python3`; each prints usage with no arguments):

- `ideas.py list|remove N` reads Ideas note text on stdin.
- `check_spec.py SPEC [--approved]` fails until the spec has every required section and requirement kind.
- `cards.py check|apply MANIFEST` validates the plan and manifest, then creates everything in Jira.
- `~/.claude/skills/card/scripts/jira.py` for `create-project`, `sprint-create`, `sprint-add`, and the rest.

Use the scripts for every step they cover. Never do by hand what a script does. If a script is wrong, fix the
script and say so. Never print `~/.config/jira/env`. Vault reads and writes go through the anchorhold MCP tools
(`anchorhold_get_note`, `anchorhold_write_note`). Put working files in this session's scratchpad. In Markdown
prose (spec, plan, cards), write each paragraph and list item on one line; never hard-wrap it. A note too large to
send through `anchorhold_write_note` (a full plan) goes in with a command for the user to run:
`! anchorhold write --overwrite "<vault path>" < <scratchpad file>`.

## Steps

1. **Pick the idea.** Read `Ideas.md` with `anchorhold_get_note`, save the text to the scratchpad, and run
   `ideas.py list` on it. If `$ARGUMENTS` names one, use it. Otherwise ask with AskUserQuestion: up to four ideas
   as options (the user can type another number or a new idea under Other). Read the memory files of the user's
   past projects for the default stack and process.
2. **Brainstorm.** REQUIRED SUB-SKILL: superpowers:brainstorming, with these overrides: the spec follows
   `spec-template.md` in this skill and is saved in the vault, not committed anywhere. Ask one question at a time,
   with options and a recommendation. Show mockups for any UI. Agree on the long-term goal, then cut V1 down to
   size. Work through every Security and Privacy and Operations section with the user. The questions there are as
   important as the feature questions.
3. **Name it.** Last, ask with AskUserQuestion for the name, offering 3 or 4 suggestions. The name sets the vault
   folder `Projects/<Name>/`, the repo `tahardi/<repo>`, and a Jira key of 2 to 4 letters. Confirm the key.
4. **Write the spec** to the scratchpad from `spec-template.md`. Start from the Baseline Requirements below and
   add the project's own. Run `check_spec.py SPEC` until it passes.
5. **Review the spec.** Start two `general-purpose` subagents at once with the prompts under Reviewer Prompts.
   Settle what they raise with the user (AskUserQuestion, few calls, recommended option first). Then ask for
   approval. On approval, run `jira.py create-project KEY "<Name>"` and put the board URL it prints in the spec's
   Jira line. Set `Status: Approved <today>`, write `Open Questions` as `None.`, and run
   `check_spec.py SPEC --approved` until it passes. Write the spec to `Projects/<Name>/Design Spec.md`.
6. **Remove the idea.** Run `ideas.py remove N` on the saved Ideas text, and write the result back to `Ideas.md`
   with `anchorhold_write_note` in `overwrite` mode. The spec's Origin line keeps the idea's text. Skip this when
   the idea was new.
7. **Write the plan.** REQUIRED SUB-SKILL: superpowers:writing-plans for step format, with the Plan Format below.
   Write the plan head yourself, then start one `general-purpose` subagent per epic, in parallel, to write that
   epic's card sections into its own scratchpad file. Tell each to read the plan head first, treat it as binding,
   copy real code from the user's past repos on `origin/main` where it fits, and report contract gaps instead of
   editing the head. Fix the head for each gap, join the files into one plan, and write `cards.json`.
8. **Check it:** `cards.py check cards.json`, until it passes. Show the user the card map it prints, with the
   sprint points, and ask for approval. Write the plan to `Projects/<Name>/Implementation Plan.md`.
9. **Create the cards:** `cards.py apply cards.json`. It creates colored epics, cards, future cards, links (and
   verifies them), the sprint on the shared cadence, and adds, assigns, and ranks the sprint cards. If it stops,
   fix the cause and run it again: it resumes. Then overwrite the vault plan with the `.keyed.md` file it wrote.
10. **Remember it.** Write a `project` memory for the new project (what it is, spec and plan paths, repo, Jira key
    and board, epics, sprint, decisions that are not in the spec) and add its line to `MEMORY.md`.
11. **Report:** the board URL, the sprint cards and points, the cards to start now (`cards.py` prints them), and
    the needs-taylor cards.

## Baseline Requirements

Every spec starts with these. Reword them to fit, and drop one only with a reason the user agrees to, written in
Out of Scope.

- R-SEC: Secrets live outside the repo, in files only the service user can read. CI runs secret scanning.
- R-SEC: CI runs a dependency audit. Dependabot alerts and security updates are on. Versions are pinned.
- R-SEC: Every endpoint requires authentication. Nothing listens beyond what the threat model allows.
- R-SEC: Services run as an unprivileged user with service sandboxing.
- R-SEC: A security review card ends V1, and its findings become cards.
- R-PRIV: The spec lists all data that leaves the machine. Sensitive data is never logged. Public repo test data
  is made up.
- R-OPS: CI runs format, lint, and tests. `main` takes only squash-merged PRs. Each CI job becomes a required
  check once it has run.
- R-OPS: Logs are structured, there is a health check, and Taylor learns when the service is down.
- R-OPS: Deploy, start on boot, and roll back are documented and scripted. Schema changes are versioned
  migrations.
- R-OPS: Stored data is backed up, and a restore is tested.

## Plan Format

The plan head comes first and binds every card:

- `## Shared Contracts`: interfaces, types, API and schema shared by more than one card, with exact names.
- `## Global Constraints`: rules every card follows (style from both CLAUDE.md files, test style, security rules).
  `cards.py` appends this section to every card.
- `## Card Map`: table of id, title, epic, points, blocked by.
- `## File Structure`: every file and the card that creates it.

Then one `## Epic: <Name>` per epic, and one card section per card under a heading `### T-<EPIC><n>: <Title>`
(for example `### T-B2: SQLite Store`). Refer to other cards by their `T-` id; `cards.py` swaps in the Jira keys.
Each section has, in order:

- `**Goal:**` What changes, why, the design decisions, and what is out of scope. Cite `R-` ids it meets.
- `**Files:**` with `- Create:`, `- Modify:`, `- Delete:` lines, each path in backticks.
- `- [ ] **Step 1: <Name> test.**` steps in pairs: a test that names the exact test names, inputs, and expected
  results, then the implementation that makes it pass (signatures, error messages starting with an "-ing" verb).
- `**Acceptance criteria:**` the tests that pass, `Needs Taylor:` hand checks, and the pre-PR command exiting 0.

Write each card for a less capable model working without this conversation. Points (1, 2, 3, 5, 8) measure the
user's review effort: more for large diffs, security- or data-sensitive code, languages the user is new to, and
on-device testing.

The first epic is Project Setup. Its cards create the repo (README, .gitignore, PR template, Makefile with
`.DEFAULT_GOAL := pre-pr`), the dev environment, CI, and the `main` ruleset. A card that runs before the repo
exists, and any card of manual steps or decisions for the user, sets `"workflow": false`. Manual cards carry the
`needs-taylor` label.

## Manifest

`cards.json` describes the cards; the plan holds their text. `cards.py` adds the Workflow, Blocked by, and Global
Constraints sections, the `parallelizable` and `needs-refinement` labels, and the sprint order. Never set those
labels yourself.

```json
{
  "project": "HALO",
  "plan": "<scratchpad>/plan.md",
  "plan_ref": "Obsidian vault `Projects/Halo/Implementation Plan.md`",
  "spec": "<scratchpad>/spec.md",
  "repo": "halo",
  "setup": "Run `npm ci` first.",
  "pre_pr": "make pre-pr",
  "epics": [{"id": "S", "name": "Project Setup", "description": "Repo, CI, and the shared contract."}],
  "cards": [
    {"id": "T-S1", "epic": "S", "points": 2, "blocked_by": [], "labels": ["needs-taylor"], "workflow": false},
    {"id": "T-S2", "epic": "S", "points": 3, "blocked_by": ["T-S1"]}
  ],
  "future": [{"title": "Meal Photos", "epic": "S", "description": "One paragraph.", "requirements": ["R-F-9"]}],
  "sprint": {"goal": "Repo and CI, so feature cards can run in parallel.", "cards": ["T-S1", "T-S2"]}
}
```

A card for another repo sets its own `"repo"`, and its own `"setup"` and `"pre_pr"` when they differ.

`future` holds cards that must exist but are not refined yet; they get `needs-refinement` for `/refine`. Every
requirement in the spec must be cited by a card section or a future card, or `check` fails. Size the sprint to the
user's review capacity, and include every blocker of a sprint card. The sprint joins the current cadence period;
when less than a week of it is left, ask the user, and set `"start": "YYYY-MM-DD"` (a cadence Monday) to begin with
the next one.

## Reviewer Prompts

**Builder check:** "You are a talented engineer experienced with <stack>. You've been handed a design spec to plan
and build, and you can't talk to its author. Read <spec path>. Report only the questions you'd need answered before
you could plan well: places you'd have to guess where a wrong guess would matter. For each, give the question and
why the answer changes the plan, ranked by importance. Skip what the spec leaves to the builder and what you could
decide yourself. If nothing important is left, say 'nothing important left'."

**Security check:** "You are a security engineer reviewing a design before any code exists. The system will run on
the author's own machines and hold their personal data. Read <spec path>. Report the threats the spec misses or
under-specifies: exposed services, weak authentication, secrets handling, data leaving the machine, logging of
sensitive data, supply chain, host hardening, backups, and recovery. For each, give the attack or failure, its
impact, and the requirement you'd add. Rank by risk. Skip generic advice the spec already covers."

## Common Mistakes

- Treating security or operations as "later". Every Baseline Requirement is in the spec, or dropped by the user.
- Creating cards, epics, links, or sprints with curl or one-off scripts. Use `cards.py` and `jira.py`.
- Implementing cards. `/project` ends when the sprint is ready; the user runs `/card`.
- Leaving manual steps or decisions in chat. They are `needs-taylor` cards.
