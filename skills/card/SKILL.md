---
name: card
description: Use when the user runs /card with a Jira card key (e.g. /card DIG-12) to implement that card end to end
argument-hint: <JIRA-KEY> [force|close]
disable-model-invocation: true
---

# Implement a Jira Card

Implement the card named in the arguments, get it green locally and in CI, and leave a PR for the user to review. On later runs, address the user's PR comments. The card is the spec. You merge only after the user approves the PR (see "Review Round").

**Arguments:** `$ARGUMENTS`. The first word is the card key (`[A-Z]+-\d+`). If the second word is `force`, skip the blocker check. If the second word is `close`, skip the Workflow and run only "Close" below.

**Jira helper:** `python3 ~/.claude/skills/card/scripts/jira.py` with `get KEY`, `transition KEY STATUS`, `comment KEY TEXT`, `assign KEY`, `strike-blockers KEY`, `open-siblings KEY`, `update KEY [--add-labels a,b]`, `test-card PROJECT SUMMARY` (Markdown description on stdin), or `create PROJECT SUMMARY [--epic KEY] [--labels a,b] [--points N] [--blocked-by K1,K2] [--blocks K3]` (description on stdin). It reads credentials from `~/.config/jira/env`. Never print or echo that file.

## Precedence

1. The user's CLAUDE.md rules (worktrees, PR title format, no comments, Go test style).
2. The card: files, names, types, steps, commands, and acceptance criteria. The card's Amendments (printed by `jira.py get`) override its description where they conflict.
3. Plugin skills such as the Expo skills: use them for API details, but where a skill suggests a different library, pattern, or structure than the card, follow the card.
4. Your own defaults.

If rules 1 and 2 conflict, stop and ask the user.

## Workflow

1. **Read the card.** Run `jira.py get KEY` and read all of it. If the card is `In Review` and has an open PR, skip to "Review Round".
2. **Check blockers.** If any "Blocked by" card is not `Done` and `force` was not given, stop. Tell the user which blockers are open, and change nothing.
   Otherwise run `jira.py strike-blockers KEY` to strike through the finished blockers in the card's description.
3. **Start.** Run `jira.py assign KEY` (assigns the card to the user unless already assigned to them), then
   `jira.py transition KEY "In Progress"`.
4. **Create the worktree** with the commands in the card's Workflow section, adding `--no-track` to any `git worktree add -b`. Work only inside it. Never commit to `main`.
5. **Check tools.** Run `go version` and `node --version`.
   - If `node` is not found, load nvm in the same command: `. ~/.nvm/nvm.sh && nvm use default >/dev/null && <command>`. Do this for every `node`, `npm`, `npx`, and `make pre-pr` command.
   - If a tool the card needs is missing or older than the card requires, stop and ask.
6. **Implement the steps in order.**
   - For each test step, write the test, run it, and see it fail for the expected reason before you implement.
   - Do only what the card asks.
   - Put throwaway files, such as reference clones, in this session's scratchpad directory, never in the worktree.
7. **Handle card problems.** A card may name an API, flag, or version that doesn't exist. Make the smallest change that still meets the card's goal and acceptance criteria. Record each one as a deviation: what the card said, what you did, and why.
8. **Verify locally.**
   - Run the formatters: `npm --prefix app run format` if `app/` exists and the card touched it.
   - Run `make pre-pr` from the worktree root. It must exit 0. On failure, find the root cause, fix it, and run it again.
   - Check each acceptance criterion and note the evidence: a test name, a command and its output, or a file.
   - Criteria you cannot check (on-device checks, anything needing the user's hardware or accounts) go in a "Needs Taylor" list. They do not block the PR.
   - If a Needs Taylor check needs made-up cards, create each one with `jira.py test-card PROJECT SUMMARY`, with
     a description that has whatever the check needs (headings, lists, and so on). It adds the `[TEST]` prefix and
     the `test-card` label, assigns the card to Taylor (unassigned cards don't show in Taylor's sprint), and adds it
     to the active sprint. Name each card's key in the Needs Taylor item that uses it, and say to move it to `Done`
     afterward.
9. **Self-review.** Run "Self-Review" below. It ends with `make pre-pr` exiting 0 again.
10. **Commit and push.** Use plain-English commit messages that follow this session's attribution instructions. Then `git push origin HEAD`.
11. **Open the PR** with `gh pr create`:
   - Title: `[KEY] <card summary>`.
   - Body: follow `.github/pull_request_template.md` and fill in every section. Link the card with its URL from `jira.py get`.
   - Add a section listing each acceptance criterion with its evidence.
   - Add "Deviations from the card" and "Needs Taylor" sections, or write "None" in each.
   - Add a "Card impacts" section from "Card Impacts" below, or write "None".
   - Add a "Reviewer notes" section from "Self-Review" below, or write "None".
   - Add a "Tests" section: one bullet per test added or changed, naming the behavior it guards. End the section
     with "Added by Self-Review:" and a list of the tests Self-Review added, or "None".
12. **Comment on the card:** `jira.py comment KEY "PR: <url>"`.
13. **Watch CI.**
    - Wait until `gh pr checks <number>` lists checks. They can take up to a minute to appear.
    - Run `gh pr checks <number> --watch --interval 60` in the background, and continue when it finishes.
    - If a check fails, run `gh run view <run-id> --log-failed`, fix the root cause, run `make pre-pr`, push a new commit, and watch again.
    - Stop after 3 fix rounds. Then comment on the card and tell the user what is still failing.
14. **After CI passes,** do any card steps that depend on a CI run, such as adding required status checks to the ruleset. If a step needs permissions you don't have, add it to "Needs Taylor".
15. **Finish.**
    - Run `jira.py transition KEY "In Review"`.
    - Comment on the card with the CI result, deviations, the Needs Taylor list, card impacts, and reviewer notes.
    - Report to the user in the same order: the PR URL, the CI status, deviations, Needs Taylor, card impacts, and
      reviewer notes. Then list the tests, and the tests Self-Review added.
    - Then run "Review Round" once.

## Self-Review

Run this at step 9, before the first commit. A fresh reviewer answers the questions Taylor would otherwise ask on the
PR, so the PR reaches Taylor with those already handled.

1. Run `git add -A` in the worktree so new files show in the diff. Get the base with `git merge-base origin/main HEAD`,
   and the card's `Created` date from `jira.py get KEY`.
2. Start one `general-purpose` subagent with the Agent tool. It has none of this session's context, so give it the
   card key, the worktree path, the base commit, and the `Created` date. Tell it to read only, change nothing, and
   answer every question below with findings (file, line, what, and why) or "none". It reads the card with
   `python3 ~/.claude/skills/card/scripts/jira.py get KEY`, the diff with `git -C <worktree> diff <base>`, and both
   `~/.claude/CLAUDE.md` and the repo's `CLAUDE.md`. The questions:
   1. **Tests:** for every test file the diff adds or changes, are the cases sufficient? List each missing case worth
      adding (error paths, edge inputs, boundaries, ordering, cleanup) and the behavior it would guard. Skip cases that
      repeat existing ones.
   2. **Conventions:** does every changed line follow both CLAUDE.md files? List each violation and the rule it breaks,
      including rules lint cannot catch: no comments, one unit per file, file naming, "-ing" error messages,
      given/when/then sections, `test.each` tables, and the language-specific rules.
   3. **Since the card was written:** read `git -C <worktree> log origin/main --since=<Created>` and the merged PRs in
      it that touch the same files or features, plus the card's "Blocked by" cards. Does anything there make the
      card's plan or this diff wrong, outdated, or duplicated?
   4. **Later cards:** read every card in this card's "Blocks" list and the cards from `jira.py open-siblings KEY`.
      Does this diff change anything they rely on in a way their description and Amendments do not reflect?
   5. **Same problem elsewhere:** does the change also belong in similar code the card did not name, such as another
      tab type, caller, screen, or platform with the same issue?
   6. **File placement:** do new files and folders match the repo's layout and naming? Are there stray files, such as
      docs, scratch files, or generated output?
   7. **Hard-coded settings:** does the diff hard-code a value Taylor would likely want to change without a PR, such
      as a speed, size, limit, timeout, or path?
   8. **Text and numbers a user sees:** are new labels, messages, and fields clear to someone who did not write the
      code? Are shown numbers a believable size and unit?
   9. **Logging:** do new failure paths and important state changes log the same way, and at the same level, as the
      code around them?
   10. **Security:** can untrusted input (user text, files, network data, URLs, environment variables) reach a shell,
      file path, query, `eval`, or rendered HTML without checks? Does the diff log, print, commit, or send secrets or
      tokens? Does it loosen auth, permissions, CORS, TLS, or sandbox settings? Does it add a dependency that is
      unmaintained or broader than the card needs?
3. Act on the findings:
   - Questions 1 and 2: fix each finding. Add tests test-first as in step 6.
   - Question 3: if the card's goal still holds, adapt the code and record a deviation. If it no longer holds, stop
     and ask.
   - Question 4: carry each finding into "Card Impacts".
   - Questions 5 to 9: change nothing. Write each finding as a question for Taylor in the PR's "Reviewer notes"
     section.
   - Question 10: fix each finding that is inside the card's scope, test-first as in step 6. Write each finding
     outside the card's scope as a question for Taylor in "Reviewer notes".
   - A finding you judge wrong: skip it and list it in "Reviewer notes" with the reason.
4. Run `make pre-pr`. It must exit 0.

Self-Review runs once per card. Review Rounds do not repeat it.

## Card Impacts

Run this after Self-Review and before opening the PR (step 11). Deviations and discoveries can make other cards wrong
or show missing work.

1. List what changed from the card: every deviation, every name, file, interface, command, or value that differs from
   what the card said, and anything you found that no card covers (a missing step, a bug, a needed follow-up).
2. Read the cards that could depend on it: `jira.py get` on every card in this card's "Blocks" list, and
   `jira.py open-siblings KEY` for the other open cards in the epic (read any that mention what changed).
3. For each card that would now be wrong, write one bullet: `- <OTHER KEY>: <exact change, e.g. "use parseFoo(text)
   not parseFoo(text, opts)">`. For missing work, write `- New card: <summary> (epic <KEY>, blocked by <keys>, blocks
   <keys>, <points> pts): <what it covers>`.
4. Put the bullets in the PR's "Card impacts" section, or "None". Do not change other cards now. They are applied at
   merge, after the user has reviewed them.

## Review Round

Run this when `/card KEY` is run on a card that is `In Review`, and once at the end of step 15. Work in the card's
existing worktree. If it is gone, recreate it from the PR branch with `git worktree add <path> <branch>`.

1. **Gather the PR's comments.** Run `gh api user --jq .login` to get the user's login. Only comments by that login
   count; ignore everyone else, including bots. Collect:
   - top-level comments and review bodies: `gh pr view <number> --json comments,reviews,commits,mergeable`;
   - inline review threads:
     `gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<number>){reviewThreads(first:100){nodes{id isResolved comments(first:50){nodes{author{login} body path line}}}}}}}'`.
2. **Sort them.** Every reply you post starts with `**Claude:**`. That marks what is already handled.
   - An **approval** is a top-level comment or review body posted after the last commit's `committedDate` that plainly
     approves, such as "LGTM", "Looks good to me", "merge", or "ship it", with no conditions. "LGTM once X is fixed" is feedback.
   - **Open feedback** is any other top-level comment or review body with no later `**Claude:**` comment, and any
     unresolved inline thread whose last comment is not a `**Claude:**` reply.
3. **If there is open feedback,** first run "Sync with Main", then address the feedback, even if there is also an
   approval:
   - Treat each comment as an amendment to the card. Where it contradicts the card, follow the comment. Where it
     contradicts CLAUDE.md, or is unclear, stop and ask.
   - Make the changes, following the Workflow rules: tests first where behavior changes, `make pre-pr` exits 0, plain
     new commits, `git push origin HEAD`.
   - Update the PR body if the acceptance evidence, deviations, Needs Taylor list, or card impacts changed. A comment
     that drops or changes a card impact counts as feedback; update the "Card impacts" section to match.
   - Reply to each comment. Inline threads: reply in the thread with `**Claude:** <what changed> in <short sha>`, then
     resolve it with the `resolveReviewThread` GraphQL mutation. Top-level comments and review bodies: one top-level
     comment starting with `**Claude:**` that lists each point and what changed.
   - Watch CI as in step 13, then comment on the card with a short summary of the changes.
   - Report the changes and the CI result to the user, and stop. The user approves on a later `/card KEY`.
4. **If there is an approval and no open feedback,** merge:
   - Run `gh pr view <number> --json mergeable,mergeStateStatus`. If `mergeable` is `CONFLICTING` or
     `mergeStateStatus` is `BEHIND`, run "Sync with Main". If it merged cleanly and CI passes, keep going. If you had to
     resolve conflicts, the code changed after approval: report it to the user and stop.
   - Every check in `gh pr checks <number>` must pass, and `mergeable` must be `MERGEABLE`. If not, tell the user what
     blocks the merge, and stop.
   - Run `git worktree remove`, `git worktree prune`, `git branch -D`, and `gh pr merge` each as its own Bash call
     from the main repo root: no `cd ... &&`, no `;` or `&&` chaining, no `-C`. The sandbox mounts `.git` read-only,
     and its exclusion for these commands only matches the bare command.
   - Remove the worktree: run `git worktree remove <worktree path>` from the main repo checkout. If it has uncommitted
     changes, stop and tell the user. Never pass `--force`.
   - Run `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`. From the main repo checkout,
     run `gh pr merge <number> --delete-branch` with `--squash` if allowed, else `--merge`, else `--rebase`. This
     deletes the remote and local branch. Never use `--admin` or `--auto`.
   - Confirm both branches are gone: `git branch --list <branch>` and `git ls-remote --heads origin <branch>` print
     nothing. Delete any leftover with `git branch -D <branch>` or `git push origin --delete <branch>`.
   - Run `jira.py transition KEY "Done"`, then `jira.py comment KEY "Merged: <PR url>"`.
   - Apply the PR's "Card impacts" as in "Applying Card Impacts", unless the section says "None".
   - Report the merge, the cleanup, the card status, and the applied impacts (with any new card keys) to the user.
5. **If there is neither,** run "Sync with Main". If the branch was already up to date, tell the user the PR is
   waiting for review, and stop. Otherwise report the sync and the CI result, and stop.

### Applying Card Impacts

Read the "Card impacts" section from the merged PR body (`gh pr view <number> --json body`). It is final: the user
reviewed it with the code.

1. **Changes to existing cards:** for each one, run
   `jira.py comment <OTHER> "Card impact from KEY (<PR url>): <the change>"`. The comment must start with
   `Card impact from`; `jira.py get` prints those comments as Amendments. Never edit another card's description.
2. **New cards:** for each one, pipe its description to
   `jira.py create <PROJECT> "<summary>" --epic <epic> --labels <labels> --points <n> --blocked-by <keys> --blocks <keys>`.
   Use the label `needs-refinement` unless the impact gave the card full steps and acceptance criteria. Add
   `parallelizable` only when the impact says so. Note the new key it prints.
3. **The plan:** if the card's description names a plan note in the Obsidian vault, append one line per impact under
   an `## Amendments` heading at the end of that note (create the heading if missing), using the obsidian-notes skill:
   `- YYYY-MM-DD KEY: <impact>, applied as <OTHER key or new key>`.
4. Comment on this card listing each impact and where it was applied.

### Sync with Main

1. In the worktree, run `git fetch origin`, then `git merge-base --is-ancestor origin/main HEAD`. Exit 0 means the
   branch already has everything in main: skip the rest.
2. Run `git merge origin/main`. Never rebase or force-push.
3. On conflicts, read both sides and the commits on main that caused them (`git log HEAD..origin/main`). Keep both
   intents: the card's changes and main's changes. If you cannot tell how to combine them, run `git merge --abort`,
   then stop and ask.
4. Run `make pre-pr`. It must exit 0. Fix anything main broke, such as renamed functions or changed fixtures, in a
   separate commit.
5. `git push origin HEAD`, then watch CI as in step 13.
6. Comment on the card: `Merged main into the PR` plus the conflicts you resolved, if any. Do not comment on the PR:
   a `**Claude:**` comment there would mark open feedback as handled.

## Close

Run this when `/card KEY close` is run. Taylor no longer wants the card's feature and has already confirmed in Maple.
Close the PR without merging, remove the worktree and branch, and keep the card as `Done` with the `wont-do` label.

1. Run `jira.py get KEY`. In the card's worktree, get the branch with `git branch --show-current` and the main checkout
   from the first line of `git worktree list`.
2. Find the PR: `gh pr list --head <branch> --state all --limit 1 --json number,url,state`. If its state is `MERGED`,
   tell the user the feature is already merged and stop.
3. Run `git status --porcelain` in the worktree. If it prints anything, list the files, ask the user whether to discard
   them, and stop until they answer.
4. Run `git worktree remove`, `git worktree prune`, `git branch -D`, and `gh pr close` each as its own Bash call from
   the main repo root, as in "Review Round" step 4: no `cd ... &&`, no `;` or `&&` chaining, no `-C`.
5. Remove the worktree: `git worktree remove <worktree path>`, then `git worktree prune`. Pass `--force` only if the
   user said to discard changes in step 3.
6. If the PR is `OPEN`, run `gh pr close <number> --comment "Closed without merging: no longer wanted."`.
7. Delete the branch: `git branch -D <branch>`. If `git ls-remote --heads origin <branch>` prints anything, run
   `git push origin --delete <branch>`. Confirm both branches are gone.
8. Run `jira.py transition KEY "Done"` and `jira.py update KEY --add-labels wont-do`. Then run
   `jira.py comment KEY "Closed without merging: <PR url>"`, or
   `jira.py comment KEY "Closed without merging; no PR was opened."` when there was no PR.
9. Report to the user: the PR closed (or none), the worktree and branches removed, and the card status and label.

## Never

- Merge without an approval comment from the user, approve the PR, enable auto-merge, or bypass rules with `--admin`.
- Push to `main`, force-push, or rewrite pushed history. Fix problems with new commits.
- Move the card to `Done` before its PR is merged, except in "Close".
- Turn off, skip, or weaken tests, linters, or CI checks to get green. That includes `t.Skip`, `.skip`, lint-disable comments, and loosened assertions, unless the card itself calls for it.
- Work on other cards or fix unrelated code. If you notice something, mention it in your report.

## Stop and Ask When

- A blocker is open (step 2).
- The card contradicts itself or CLAUDE.md in a way the smallest-change rule cannot settle.
- A command needs `sudo`, an interactive login, or a secret you don't have.
- CI is still failing after 3 fix rounds.
- A PR comment contradicts CLAUDE.md or is unclear.
- The worktree has uncommitted changes when it is time to merge.
