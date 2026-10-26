# <Name>: Design Spec

Status: Draft <YYYY-MM-DD>
Jira: <board URL>
Repo: `tahardi/<repo>` (created by a setup card)
Origin: <the Ideas note entry, copied word for word>

## Purpose

> Guide: Who it is for, the long-term goal, and what V1 proves. One or two paragraphs.

## Users and Data

> Guide: Who uses it and from where. Every kind of data it stores or sends, rated public, personal, or sensitive
> (health, location, contacts, credentials, money). Where each kind lives, and who could read it.

## Requirements

> Guide: V1 behavior as `- **R-F-1:** ...` lines, each one testable.

## Architecture

> Guide: Components, the machines they run on, how they talk, the stack and why. The API contract or data model.

## Security and Privacy

Built as if real clients depended on it. Each rule is a requirement a card must meet.

### Threat Model

> Guide: Assets, who might attack them (other devices on the network, a stolen phone, a leaked token, a malicious
> dependency, a third-party API), trust boundaries, and the worst outcome of each.

### Data Handling

> Guide: Encryption in transit and at rest, what leaves the machine (third-party and LLM APIs) and why, retention,
> deletion, and what must never be logged. As `- **R-PRIV-1:** ...` lines.

### Secrets

> Guide: Every secret, where it is stored (never in the repo), who can read it, and how it is rotated. CI secret
> scanning. As `- **R-SEC-n:** ...` lines.

### Network Exposure

> Guide: What listens where (bind address, port), how clients authenticate (Tailscale, keys), authorization, and
> limits on request size and rate.

### Supply Chain

> Guide: Pinned versions and lockfiles, dependency audit in CI, Dependabot alerts and security updates, as few
> dependencies as possible. Every lint or scanner ignore directive carries a one-line reason.

### Host

> Guide: The OS user it runs as (not root, not the login user if avoidable), service sandboxing (for example systemd
> hardening), disk encryption, firewall, and how the host is patched.

## Operations

### Deployment

> Guide: How it is built, released, installed, started on boot, and rolled back. As `- **R-OPS-n:** ...` lines.

### Observability

> Guide: Structured logs (with no sensitive data), a health check, the metrics that show it works, and how Taylor
> learns that it broke.

### Upgrades and Migrations

> Guide: Versioning, schema migrations, dependency and runtime upgrades, and compatibility between old clients and a
> new server.

### Backup and Recovery

> Guide: What is backed up, where, how often, how a restore is tested, and how long a restore may take.

## Testing

> Guide: Unit, integration, and live tests, what each covers, and which CI checks gate a merge.

## Out of Scope

> Guide: What V1 leaves out on purpose, and the future ideas worth keeping.

## Open Questions

> Guide: Questions still open. Must say "None." before approval.
