# dotclaude

Taylor's Claude Code configuration: global instructions, skills, and settings. Changes land only through reviewed PRs; the desktop and the Xena VM install from this repo.

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global instructions |
| `skills/card`, `skills/project`, `skills/refine`, `skills/retro` | Skills |
| `skills/learn` | `/learn <note path>` writes a security lesson and per-finding tie-ins into a Maple lesson note |
| `skills/audit` | `/audit` runs `xena audit`, explains each drift, and checks Claude config drift the binary cannot |
| `skills/repo-security-review` | `/repo-security-review` reviews a whole repo and files each finding as a Jira card |
| `settings/desktop.json` | Desktop `~/.claude/settings.json`: permission prompts, sandbox on, no unsandboxed retries, write access to each repo's `.git` |
| `settings/vm-managed.json`, `settings/vm-managed-mcp.json` | Xena VM managed settings and MCP servers, installed root-owned as `/etc/claude-code/managed-settings.json` and `managed-mcp.json` |
| `plugins.yaml` | Allowed plugins and MCP servers, pinned to versions and commits, with the hosts each reaches and the features that must stay off |
| `scripts/check_plugins.py` | Prints installed plugins, marketplaces, and MCP servers that differ from `plugins.yaml` as JSON; exits 1 on drift and warns about listed MCP servers that are missing |
| `statusline.sh` | Two-line status bar for Claude Code: model, folder, branch, context use, and plan limits. Needs jq and git |
| `install.sh` | `install.sh desktop` links the files above into `~/.claude` and moves anything it replaces to `~/.claude/dotclaude-backup/`; `install.sh vm` copies the VM settings, `CLAUDE.md`, the status line, and the skills into `/etc/claude-code`, where the VM user cannot change them |

`/card` runs a security pass after CI passes. A finding with a clear fix is fixed in the PR, and Taylor only reads about it. Every other medium or high finding goes, in plain English, to the card's findings file in `$MAPLE_FINDINGS_DIR` (default `~/.config/maple/findings`), where Maple shows it for Taylor to decide. Low findings are dropped, and no finding keeps the card out of In Review. In a repo opted in with a trust model, findings are rated by who can reach the code, accepted and tracked risks are skipped, and existing issues in changed files are reported too. The card that writes a repo's trust model checks the whole repo once, and each existing medium or high issue becomes a backlog card when its PR merges, so later cards do not raise it. Once Taylor has decided every finding, Maple asks `/card` to apply the decisions: it fixes Fix now findings, files Fix later cards for refinement, posts one summary on the PR, and runs the security pass again. Accepted risks, severity overrides, and Fix later cards are written into the trust model in the card's PR. Any other edit to the model is raised as a finding, and a change the model does not describe, such as a new network listener, gets a proposed model update as a finding.

When `/card` finds a PR Taylor merged, it treats the PR as approved and skips review: card to Done, worktree and branch removed, the PR's card impacts applied (which can create new Jira cards), and its test cards moved to Done.

Never commit secrets, tokens, memory files, or transcripts. `make pre-pr` runs shellcheck, the skill and script tests, the install script test, JSON and YAML syntax checks, and gitleaks. It needs shellcheck, Python 3 with PyYAML (`python3-yaml`), jq, and Go (for gitleaks).
