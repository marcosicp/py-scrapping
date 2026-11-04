# Copilot instructions

This repository maintains a single tool-agnostic agent-context file:

**Read [`/AGENTS.md`](../AGENTS.md) first.** It is the authority.

Minimum just to be safe in this repo:

- **`static/` is build output and is NOT versioned.** A fresh clone has no bundle:
  `/` answers 503 with the build command until you run `cd adminpro && npm ci &&
  npm run build`. Never edit it by hand; the source is `adminpro/src/`.
- **`.gitignore` ignores `*.json` globally** (`.gitignore:56`). New JSON files
  are silently untracked unless you add an exception.
- **`adminpro/node_modules` is not installed**, and **`.venv` is broken** — it
  must be recreated before `pip` works.
- **There is no test suite.** Do not claim tests pass.
- **ChromeDriver is pinned** to `/usr/local/bin/chromedriver-141` in all five
  scrapers.
- **The live MongoDB database is `lalistitadev`**, collection `productos` — not
  `lalistita` as `app.py:33` implies.

Deep dives: [`docs/agent-context/repo-map.md`](../docs/agent-context/repo-map.md),
[`docs/agent-context/runbook.md`](../docs/agent-context/runbook.md),
[`docs/agent-context/known-issues.md`](../docs/agent-context/known-issues.md).

Do not add guidance here that duplicates `AGENTS.md`. Drift between the two is
the failure mode this file exists to prevent.
