# Env file selector — one explicit database for both entry points

Branch: `chore/env-file-selector`, merged to local `main` (`0f2d88e`), plus the
review correction (`9239010`).

## Goal

Let the owner exercise the scrapers against the local `mongod` instead of the
deployed Atlas cluster, without either database being reached by accident.

## Why it was needed

`app.py` called a bare `load_dotenv()`, so it read `.env` (the deployed
cluster), while `python -m api.cli run` read **no file at all** and fell back to
the `localhost` defaults. Testing the price-integrity fix locally therefore
meant exporting variables by hand on every command, and the production cluster
was one forgotten export away. That is not a hypothetical: `coverage` once
reported 6.7 % multi-chain coverage because it had measured the local copy
(which carries no `ean`) instead of the deployed one.

## Decisions

- **E-1 · One helper, two entry points.** `api/config.py::load_env_file(default)`
  is the only place that decides which env file is read. `app.py` calls it with
  `".env"`, the CLI with the default its subcommand deserves.
- **E-2 · The selector wins, exports win over the file.**
  `LALISTITA_ENV_FILE` names the file; `override=False` keeps an already
  exported variable authoritative, so a one-off
  `MONGODB_URI=... python -m api.cli run` still behaves.
- **E-3 · Each subcommand keeps its own default, on purpose.** `coverage`
  defaults to `.env` (it must measure the database the dashboard reads); `run`
  has **no** default, so a scraper is never silently retargeted at production;
  `list` reads no environment at all.
- **E-4 · An explicitly selected file that does not exist is fatal.** Found by
  the native review as `R3-ENV-SELECTOR-FAIL-OPEN` (CRITICAL): returning `None`
  for a missing file meant a typo in the variable silently started the app or a
  scraper against the wrong database — the exact failure the feature exists to
  prevent. A missing *default* `.env` stays a no-op, because a fresh clone and
  CI have none; the two cases are different facts.
- **E-5 · `.env.local` is never versioned.** It is already covered by
  `.gitignore:3` and by `.dockerignore`'s `.env.*`, verified with
  `git check-ignore` before it existed.

## Usage

```bash
LALISTITA_ENV_FILE=.env.local python app.py
LALISTITA_ENV_FILE=.env.local python -m api.cli run changomas
LALISTITA_ENV_FILE=.env.local python -m api.cli coverage
```

`.env.local` holds `MONGODB_URI=mongodb://localhost:27017/`,
`MONGODB_DB=lalistitadev` and a throwaway `SECRET_KEY`.

## Evidence

- Gates: 562 passed / 16 skipped (opt-in MongoDB), flake8 CI gate 0. Test-first
  throughout: the helper tests were RED on a missing import, and the fail-fast
  correction was RED before it raised.
- The local database, measured before any run: 17 112 documents and
  **no `ean` at all** — ChangoMás is absent, Carrefour holds 1 480 zero-price
  documents, the other three chains are complete. So the local environment
  proves **prices**, never matching: the EAN layer is empty there.
- **Native review** `review-5078d77a90aca880` (medium, one `review-reliability`
  lens, 16 paths / 720 lines): the reviewer's refuter confirmed
  `R3-ENV-SELECTOR-FAIL-OPEN` as candidate-caused and deterministic, and the
  correction was applied, committed and re-gated within a declared 72-line
  budget (48 lines used).
- **Blocked**: the `provider_targeted_validator` capture of that correction is
  rejected by the facade with `collectBinding is missing or stale for current
  STATUS` twice, using the byte-exact binding the bound STATUS renders, with a
  fresh STATUS between the attempts. Same symptom as the packaging-tokens round
  (five attempts, three lineages). Two attempts, then stop: the lineage stays in
  `correction_required`, nothing burned, no verdict written, no delivery
  authority granted.

## Non-goals

- A `--env-file` CLI flag: the variable covers it and keeps one mechanism.
- Rotating `SECRET_KEY` for the local profile (known issue K-13).
