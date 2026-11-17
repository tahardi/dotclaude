# Trust Model

Maple is a desktop app that runs Jira cards with Claude. Taylor is its only user, on their own machine.

## Assets

- `jira-token`: the Jira API token in the shared env file. If it leaks, someone could read and change every card.

## Who Might Attack

- `pr-author`: anyone who can open a PR or comment on GitHub. They reach the CI jobs only.

## Trust Boundaries

The app has four parts. Only `ci` is reachable from outside; the rest are internal-only.

- `renderer`: the app window that draws the board.
- `main-process`: the Node process that runs git, gh, and Jira calls.
- `hook-server`: the local socket that takes hook events from Claude.
- `ci`: the GitHub Actions jobs that run on every PR.
- `renderer-to-main`: IPC calls from the window to the Node process. Every argument gets a schema check.

## What We Trust

Any part that runs Claude can be misled, so its trust is a best effort and its limits carry the weight.

- `renderer`: trusted with drawing outside text, nothing else. Limited by the window sandbox and the schema check on
  every IPC call.
- `main-process`: trusted with Taylor's gh login and Jira token. Nothing limits it; it is the trusted base.
- `hook-server`: trusted with passing hook events from Claude sessions to the main process. Limited by listening only
  on a local socket and the schema check on every event.
- `ci`: trusted with running the tests on every PR. Limited by read-only repo permissions and no secrets on PRs.

## Users and Access

- `taylor`: the owner, who can do everything. Access is the desktop login, GitHub owner, and Jira admin.

## Build, Deploy, and Monitor

Built with `make pre-pr` locally and GitHub Actions on PRs. Installed from a local build. Watched through the event
log in the config dir.

## Accepted Risks

None yet.

## Severity Overrides

None yet.
