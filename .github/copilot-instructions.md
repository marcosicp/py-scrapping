# Copilot instructions

This repository maintains a single tool-agnostic agent-context file:

**Read [`/AGENTS.md`](../AGENTS.md) first.** It is the authority for the stack
reality, the hard rules, the runnable commands, the scraper contract, and the
traps that break a first run. Do not rely on summaries of it — including older
versions of this file.

Deep dives, only when the task needs them:

- [`docs/agent-context/repo-map.md`](../docs/agent-context/repo-map.md) — architecture, endpoints, data schema
- [`docs/agent-context/runbook.md`](../docs/agent-context/runbook.md) — install, run, build, deploy
- [`docs/agent-context/known-issues.md`](../docs/agent-context/known-issues.md) — known defects

Do not add guidance here that duplicates `AGENTS.md`. Drift between the two is
the failure mode this file exists to prevent — if something is missing, fix
`AGENTS.md` instead.
