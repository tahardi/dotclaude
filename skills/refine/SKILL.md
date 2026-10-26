---
name: refine
description: Use when the user runs /refine with a Jira project key (e.g. /refine MPL) to rewrite every open needs-refinement card so /card can implement it
argument-hint: <PROJECT KEY>
disable-model-invocation: true
---

# Refine Jira Cards

Rewrite every open card in the project labeled `needs-refinement` so the /card skill can implement it without asking anything. Change no code, create no worktrees, and commit nothing. Jira is the only thing you change.

**Arguments:** `$ARGUMENTS`. The first word is the project key (`[A-Z][A-Z0-9]+`).

**Jira helper:** `python3 ~/.claude/skills/card/scripts/jira.py` with `get KEY`, `list PROJECT [--label X]`, `update KEY [--description -] [--add-labels a,b] [--remove-labels c,d] [--points N] [--epic KEY]` (`--description -` reads the description from stdin), `link BLOCKER BLOCKED`, and `create PROJECT SUMMARY [--epic KEY] [--labels a,b] [--points N] [--blocked-by K1,K2] [--blocks K3]` (description on stdin). Never print or echo `~/.config/jira/env`.

## Process

1. **Find the cards.** Run `jira.py list PROJECT --label needs-refinement`. If it prints nothing, say so and stop. Run `jira.py list PROJECT` to get every open card and the epics (type `Epic`).
2. **Read.** Run `jira.py get` on each card to refine and on each card it mentions. Read the repo's CLAUDE.md, `~/.claude/CLAUDE.md`, `~/.claude/skills/card/SKILL.md`, and the code each card touches.
3. **Ask once, up front.** List every product question the code cannot answer: behavior, placement, wording, scope, and which of two designs to use. Ask them all with AskUserQuestion before writing any card. Use as few calls as you can (up to 4 questions each), and put your recommended option first, marked "(Recommended)". Skip this step if there are no questions.
4. **Research.** Start one `general-purpose` subagent per card, in parallel. Each reads only and changes nothing. Give it the card text, Taylor's answers, the open card list, the Template and Rules below, and tell it to return: a draft description, an epic, points, the Files list, blockers, and any question it could not settle. Check every path, function, and test name in the drafts against the code yourself.
5. **Settle leftovers.** If the drafts raise new product questions, ask them in one more AskUserQuestion round.
6. **Size.** Give each card 1, 2, 3, 5, or 8 points. Split a card over 8 into slices of 8 or less, each a full description in the Template. The original card becomes the first slice. Create the rest with `jira.py create` (no `needs-refinement` label), each blocked by the slice before it.
7. **Label.** Remove `needs-refinement`. Add `parallelizable` only when the card's Files share no path with the Files of any other open card, including the others in this batch and cards In Progress or In Review. If another card has no Files list yet, judge from its text. Keep every other label.
8. **Post.** For each card, pipe its description to `jira.py update KEY --description - --points N --epic EPIC --remove-labels needs-refinement`, adding `--add-labels parallelizable` when step 7 allows it. Then run `jira.py link BLOCKER KEY` for each blocker that `get` does not already list.
9. **Report.** One line per card: key, summary, epic, points, labels, blocked by, blocks. Then list the cards created by splits and any question still open.

## Template

Write plain text with `**bold**` and backticks, sections in this order and separated by blank lines:

**Source:** <who asked and when>: "<the card's original text, trimmed>". <Taylor's answers that shaped it>. Builds on <Done cards it extends>.

**Workflow:**

1. `git -C <repo path> fetch origin && git -C <repo path> worktree add ~/Documents/code/wts/<repo>-<key>-<slug> -b <key>-<slug> --no-track origin/main` (<key> is the card key in lower case; <slug> is two or three words)
2. Work only inside that worktree. Never commit to `main`. <setup command, e.g. Run `npm ci` first.>
3. Follow the steps in order: write the test, see it fail, then implement.
4. `<the repo's pre-PR command>` from the worktree root must exit 0.
5. Open the PR titled `[<KEY>] <Summary in Title Case>`, fill in the PR template, and link this card.

**Goal:** One dense paragraph: what changes for the user, what exists today (with the real function and file names), the design decisions and why, and what is out of scope.

**Files:**

- Create: <exact paths>
- Modify: <exact paths>
- Delete: <exact paths>
- [ ] **Step 1: <Name> test.** <describe/test names, inputs, and expected results>. Run it and see it fail.
- [ ] **Step 2:** <implementation: function signatures, props, error messages>

**Acceptance criteria:**

- The Step 1, 3, ... tests pass.
- Needs Taylor: <the hand test in the repo's try command, on `test-card` cards, naming what Taylor should see>.
- `<the repo's pre-PR command>` exits 0.

## Rules

- Every path, function, and test you cite exists on `origin/main`, or the card creates it.
- Steps come in pairs: a test step naming the exact `describe` and `test` names, then the implementation it drives.
- Name function signatures and error messages; error messages start with an "-ing" verb.
- Follow both CLAUDE.md files: tests next to the code, `// given` `// when` `// then`, `test.each` for cases with one shape, one unit per file, no comments.
- Drop bug-report logs, and quote only the lines that explain the bug.
- Never change a card that is not labeled `needs-refinement`, except to link it as a blocker.
