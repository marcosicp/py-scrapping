# Feature: agent-context-bootstrap

| Field | Value |
| --- | --- |
| Status | in progress |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `main` (work is docs-only; no branch yet) |
| Created | 2026-11-03 |

## Problem

This repository had no agent-facing context file. The only machine-directed
document was `.github/copilot-instructions.md`, which is:

- Copilot-specific (not read by Pi, Claude Code, Codex, Cursor, opencode, etc.).
- Stale on the two facts that break a first run: it claims Python 3.11 while the
  deploy target is 3.10, and Angular 16 while `adminpro/package.json` pins
  Angular 19.
- Silent on the real traps: the broken `.venv`, the hardcoded
  `/usr/local/bin/chromedriver-141`, the `*.json` gitignore that swallows new
  config files, the committed Angular build output under `static/`, and the
  "everything touches `current_app.mongodb_client` but it is only set inside
  `__main__`" defect.

A new agent session therefore spends its first turns rediscovering the stack and
re-discovers the same defects from scratch.

## Goal

Give any agent that opens this repo a trustworthy, verified entry point: one
authority file plus three deep-dive documents, all consistent with the code at
`main@06b37b7`, and a clarified boundary with the pre-existing Copilot file.

## Non-goals

- Fixing any of the defects documented in `known-issues.md`. Those become
  separate, reviewable work units.
- Touching application behavior, dependencies, or the Angular build.
- Rebuilding `static/`.
- Adding project skills. Deferred until a real repeated recipe exists.
- Committing. Left to the user's explicit decision.

## Deliverables

| Path | Role |
| --- | --- |
| `AGENTS.md` | Single source of truth: stack, commands, layout, conventions, hard rules, traps |
| `CLAUDE.md` | Pointer to `AGENTS.md` for Claude Code style loaders |
| `.github/copilot-instructions.md` | Rewritten as a short pointer to `AGENTS.md` |
| `docs/agent-context/repo-map.md` | Architecture, request flow, endpoint table, scraper contract, data schema |
| `docs/agent-context/runbook.md` | Verified setup/run/build/deploy commands and their real status |
| `docs/agent-context/known-issues.md` | Defects found during recon, with `path:line`, severity, and causality |

## Tasks

- [x] T1 Recon: map backend, frontend, scrapers, deploy paths, env reality
- [x] T2 Scaffold this feature document + Engram mirror
- [x] T3 Author `AGENTS.md`
- [x] T4 Author `CLAUDE.md` pointer
- [x] T5 Rewrite `.github/copilot-instructions.md` as pointer
- [x] T6 Author `docs/agent-context/repo-map.md`
- [x] T7 Author `docs/agent-context/runbook.md`
- [x] T8 Author `docs/agent-context/known-issues.md`
- [x] T9 Structural verification: links resolve, commands match files, zero secrets
- [x] T10 Persist project context to Engram

## Decisions

- **D1 — One authority file.** `AGENTS.md` holds the rules; `docs/agent-context/*`
  holds detail. Duplicated prose across the two tiers is prohibited because
  stale duplicates are worse than no documentation.
- **D2 — Copilot file becomes a pointer.** Keeping 217 lines of contradicting
  guidance guarantees drift. The user explicitly approved the rewrite.
- **D3 — Verification is structural, not test-first.** This change adds no
  behavior, so there is no RED to observe. Verification = link resolution,
  command-to-file cross-checks, and a secret scan.
- **D4 — Defects are documented, not fixed.** Each leaking bug is evidence-backed
  and belongs to its own task so review stays focused.

## Verification plan

| Check | Method | Result |
| --- | --- | --- |
| Every relative link in the new docs resolves | scripted markdown-link extraction + existence test | **0 broken** |
| Every `path:line` citation matches the cited source | scripted needle-at-line check, 30 citations | **0 mismatches** after 9 corrections |
| Markdown anchors in `known-issues.md` resolve | anchor id vs `#k-N` reference diff | **17 ids / 17 refs, none missing** |
| No credentials in new files | regex scan for URIs with embedded users, keys, tokens | **0 hits** |
| UTF-8 clean, no replacement characters | byte decode + U+FFFD count | **0** |
| New files are not swallowed by `*.json` gitignore | `git check-ignore` on all seven paths | **none ignored** |

Corrections made by this pass (recorded so the pattern is visible): five
off-by-one `path:line` citations, one wrong claim about ag-grid loading CSS from
`unpkg` (it imports from `src/styles.css:3-4`), one wrong claim that all five
scrapers use ChromeDriver (SuperMami uses `requests_html` only), and one
over-claim about Carrefour's subcategory count.

## Evidence log

| Task | Evidence |
| --- | --- |
| T1 | `api/routes.py:1-184`, `app.py:1-46`, `api/scrapers/*.py`, `adminpro/package.json`, `adminpro/angular.json:16-20`, `Dockerfile`, `Procfile`, `.github/workflows/python-app.yml` |
| T2 | this file; Engram mirror `odd/agent-context-bootstrap/tasks` (observation 690) |
| T3 | `AGENTS.md`, 244 lines — 11 sections, 11 traps with `path:line` |
| T4 | `CLAUDE.md`, 17 lines, pure pointer |
| T5 | `.github/copilot-instructions.md`, 217 → 27 lines |
| T6 | `docs/agent-context/repo-map.md`, 219 lines — 14 endpoints, 5 scrapers, record schema |
| T7 | `docs/agent-context/runbook.md`, 188 lines — every command labelled VERIFIED / INFERRED / BLOCKED |
| T8 | `docs/agent-context/known-issues.md`, 345 lines — K-1..K-17 + 5 minor observations |
| T9 | verification table above; no commit made |
| T10 | Engram observations 689, 691, 692, 693 + this mirror (690) |

## Handoff

Nothing was committed. Suggested work-unit split for review:

1. `docs: add AGENTS.md as the single agent-context authority` — `AGENTS.md`
2. `docs: collapse tool-specific instructions into pointers` — `CLAUDE.md`, `.github/copilot-instructions.md`
3. `docs: add deep agent context (map, runbook, known issues)` — `docs/agent-context/`
4. `chore(odd): record agent-context bootstrap feature` — `odd/tasks/`

Each of the 17 registered defects is a separate future feature under `odd/tasks/`.
