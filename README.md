# dotclaude

Taylor's Claude Code configuration: global instructions, skills, and settings. Changes land only through reviewed PRs; the desktop and the Xena VM install from this repo.

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global instructions |
| `skills/card`, `skills/project`, `skills/refine`, `skills/retro` | Skills |
| `settings/desktop.json` | Desktop `~/.claude/settings.json`: permission prompts, sandbox on, no unsandboxed retries, write access to each repo's `.git` |
| `settings/vm-managed.json`, `settings/vm-managed-mcp.json` | Xena VM managed settings and MCP servers, installed root-owned as `/etc/claude-code/managed-settings.json` and `managed-mcp.json` |
| `plugins.yaml` | Allowed plugins and MCP servers, pinned to versions and commits, with the hosts each reaches and the features that must stay off |
| `scripts/check_plugins.py` | Prints installed plugins and MCP servers that differ from `plugins.yaml` as JSON; exits 1 on drift |
| `install.sh` | `install.sh desktop` links the files above into `~/.claude` and moves anything it replaces to `~/.claude/dotclaude-backup/`; `install.sh vm` copies the VM files into `/etc/claude-code` |

Never commit secrets, tokens, memory files, or transcripts. `make pre-pr` runs shellcheck, the skill and script tests, the install script test, JSON and YAML syntax checks, and gitleaks. It needs shellcheck, Python 3 with PyYAML (`python3-yaml`), jq, and Go (for gitleaks).
