# dotclaude

Taylor's Claude Code configuration: global instructions, skills, and settings. Changes land only through reviewed PRs; the desktop and the Xena VM install from this repo.

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global instructions |
| `skills/card`, `skills/project`, `skills/refine`, `skills/retro` | Skills |
| `settings/desktop.json` | Desktop `~/.claude/settings.json`: permission prompts, sandbox on, no unsandboxed retries, auto-update off |
| `install.sh` | `install.sh desktop` links the files above into `~/.claude` and moves anything it replaces to `~/.claude/dotclaude-backup/` |

Never commit secrets, tokens, memory files, or transcripts. `make pre-pr` runs shellcheck, the skill script tests, the install script test, a JSON syntax check, and gitleaks. It needs shellcheck, Python 3, jq, and Go (for gitleaks).
