# Trust Model

dotclaude is Taylor's Claude Code configuration: the global instructions, skills, settings, and plugin allowlist that
every Claude session follows, on the desktop and in the Xena VM. Taylor is its only user. This model describes the
Xena setup, where agentic sessions run only in the VM and desktop Claude runs in prompt mode. Until Xena runs, desktop
sessions still skip permissions and run agentically, so any change that weakens the desktop settings is rated as if
desktop sessions were agentic, and any change to the skill scripts is rated as if they hold Taylor's own Jira token.

## Assets

- `desktop-guardrails`: the desktop settings that keep desktop Claude in prompt mode, with the sandbox, deny rules,
  network allowlist, and push-to-main hook. Sandboxed Bash runs without a prompt, and `gh pr merge`,
  `git branch -D`, and `git worktree remove` run outside the sandbox. If lost, Claude on the desktop gets Taylor's
  machine, logins, vault, and secrets store. Gap: the push-to-main hook never blocks, because grep rejects its pattern.
- `vm-exits`: the parts of the VM settings that open a path out of the VM, such as MCP servers, hooks, folders the
  desktop reads, connectors, and marketplaces. If lost, a VM session reaches the desktop, the full vault, or
  claude.ai connectors.
- `claude-config`: the instructions and skills every session follows. If lost, every session follows bad
  instructions.
- `plugin-allowlist`: the pinned plugins and marketplaces, with cloud and telemetry features off. If lost, outside
  code runs in every session or data leaves.
- `vm-tokens`: the hour-long GitHub token and Jira bot token the skill scripts use. If lost, someone can push PRs to
  named repos and edit cards, but not merge or administer.
- `findings`: the scripts and trust model rules that decide which findings reach Taylor. If lost, real findings are
  quietly dropped or downgraded.
- `command-log`: the desktop log of every Bash command. If lost, a secret typed on the command line leaks.

## Who Might Attack

- `misled-vm-session`: a VM session steered by text, a plugin, or code it runs. It reaches the VM sessions, the skill
  scripts, and CI, and through PRs on dotclaude every part of the config, which takes effect only once Taylor merges.
  It also reaches Maple, which reads the hook events and finding files it writes.
- `public-reader`: anyone on the internet, who can read the public repo and open fork PRs. Reaches CI only.
- `malicious-upstream`: a bad plugin, marketplace, GitHub Action, or the gitleaks module. Plugin code runs inside
  sessions, so it reaches what they reach, plus desktop Claude, CI, and Maple. On the desktop, plugin hooks and helper
  servers run as Taylor outside the sandbox.
- `misled-desktop-claude`: desktop Claude steered by text it reads. It runs sandboxed Bash without a prompt, and
  anything else only as Taylor approves. Until Xena runs, desktop card sessions skip prompts and merge their own PRs,
  so it reaches the desktop settings, instructions, skills, plugin list, and install script as well as itself and the
  status bar.

## Trust Boundaries

The parts are Maple, the desktop and VM settings, the instructions, the skills and their scripts, the plugin list, the
install script, the status bar, CI, and the Claude sessions on each side. Changes reach the installed config only
through a merged PR.

- `pr-to-main`: PRs from VM sessions and forks, then the merge. Checked by the main ruleset and its required checks,
  pinned actions, a read-only token, and Taylor merging the reviewed commit from Maple. Gaps: 0 approvals are
  required, and until Xena runs, card sessions on the desktop merge PRs themselves, not pinned to the reviewed commit.
- `main-to-vm`: files copied root-owned into the VM. The VM user cannot change them, and the guard suite reruns. Gap:
  the installed commit is not recorded.
- `main-to-desktop`: symlinks into the main checkout. The audit reports local changes and unpushed commits.
- `sessions-to-scripts`: finding JSON, card text, review threads, and scanned files. Checked by schema and length
  checks, card key patterns, summaries passed through files, and models read from the base commit. Gap: the Jira
  helper has no request timeout.
- `maple-to-scripts`: Taylor's decisions. Only Maple records them, and session-written decisions are ignored.
- `scripts-to-maple`: finding files. Maple schema-checks, caps, and shows them as text.
- `vm-exits`: the vault socket and the hook events file. Checked by managed-only hooks, permissions, and MCP servers,
  connectors off, and allowed marketplaces only.

## What We Trust

Any part that runs Claude can be misled, so its trust is a best effort and its limits carry the weight.

- `maple`: trusted with Taylor's decisions, merges, and starting VM sessions. Nothing limits it; it is the trusted
  base, with Xena's desktop services.
- `desktop-settings`: trusted with keeping desktop Claude in prompt mode with the sandbox, deny rules, and network
  allowlist. Limited by Taylor's PR review and the audit flagging any setting that allows more.
- `vm-settings`: trusted with closing the VM's exits. Limited by the VM wall, being root-owned, the guard suite, and
  the VM settings test on every PR.
- `instructions`: trusted with how every session behaves. Nothing enforces it; the VM wall, scoped tokens, and
  Maple's checks carry the weight.
- `skills`: trusted with steering each card through the security pass and the PR without merging unapproved. Limited
  by VM tokens that cannot merge, Maple's pinned merge, decisions kept in Maple, and models read from the base commit.
  Gap: until Xena runs, card sessions on the desktop merge PRs themselves, not pinned to the reviewed commit.
- `skill-scripts`: trusted with the VM tokens and with writing and filtering findings. Limited by the VM sandbox,
  narrow tokens, Maple's schema checks, decisions from Maple, and unit tests. Gap: a change that quietly drops
  findings is caught only by tests and review. Gap: until Xena runs, desktop card sessions run these scripts with
  Taylor's own Jira token.
- `plugin-list`: trusted with naming the only outside code sessions run. Limited by the VM's marketplace list, the
  proxy allowlist, the audit, and the VM settings test on every PR. Gap: the desktop loads whatever is installed until
  the audit runs.
- `install-script`: trusted with putting reviewed files in place. Limited by the root-owned VM copy, the guard suite,
  and the audit. Gap: the installed commit is not recorded.
- `statusline`: trusted with drawing session data. Limited by being read-only with the session's own rights.
- `ci`: trusted with running the checks on every PR. Limited by a read-only token, no secrets, and pinned actions.
- `vm-sessions`: trusted with card work as a best effort. Limited by the VM wall, scoped short-lived tokens, and no
  merge or approve.
- `desktop-claude`: trusted with interactive help as a best effort. Limited by prompt mode for anything outside the
  sandbox; sandboxed Bash runs without a prompt, bound by the sandbox, the network allowlist, and the deny rules.

## Users and Access

- `taylor`: the owner, who can do everything. Access is the desktop login, the gh login with a YubiKey, and Jira.
- `vm-session`: Claude in the VM, which can push branches, open PRs, comment, and edit cards, but cannot approve,
  merge, or change settings. Access is the hour-long GitHub App token and the Jira bot token.
- `desktop-claude`: Claude on the desktop, which runs sandboxed Bash without a prompt and anything else only as
  Taylor approves. No tokens of its own.
- `public`: anyone, who can read the repo and open fork PRs.

## Build, Deploy, and Monitor

Built with `make pre-pr` and GitHub Actions on every PR and push to main, with pinned actions and weekly Dependabot
updates for actions; the gitleaks pin is not kept current. The desktop links to the main checkout and goes live at a
pull; the VM copies files root-owned at build time; neither records the installed commit. Watched by `/audit`, the
plugin drift check, the guard suite, the security pass reading this model from the base commit, and the desktop
command log.

## Accepted Risks

None yet.

## Severity Overrides

None yet.
