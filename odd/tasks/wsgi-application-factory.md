# Feature: wsgi-application-factory

| Field | Value |
| --- | --- |
| Status | in progress |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `main` (owner commits to main locally) |
| Created | 2026-11-03 |

## Problem

Two critical defects share one root cause: **everything the app needs is wired up
inside `if __name__ == '__main__':`**, so nothing is wired under a WSGI server.

- **K-1** — `configure_sockets(app)` at `app.py:26` is inside that block. Any
  hosted runtime imports the module instead of running it, so
  `socketio.init_app()` never happens and `notifyStatus()`
  (`api/sockets.py:48`) emits on an uninitialized server. `/scrape` goes silent
  with no error.
- **K-2** — `app.mongodb_client` is assigned at `app.py:32` and `app.py:42`, also
  inside that block. Five call sites read `current_app.mongodb_client`
  (`api/routes.py:93` plus all four scrapers). Under WSGI they raise
  `AttributeError`. `/supermercados` catches it and returns an empty payload, so
  the failure looks like "no data" rather than "misconfigured app".

## Design

**D1 — Introduce `create_app()`.** One function that assembles the app:
Flask instance, CORS, secret key, blueprint, SocketIO, Mongo handles. Every entry
point calls it; nobody depends on import-time side effects.

**D2 — `main.py` as the WSGI entry.** `gunicorn main:app` is what the Dockerfile
already expects (`Dockerfile:36`). Creating it also **closes K-5**, which was
blocked on this work: the image previously built fine and crashed at start
because `main.py` did not exist.

**D3 — `python app.py` keeps working.** The `__main__` branch becomes two lines
that call the factory and `app.run()`. Local development is unchanged.

**D4 — Always create a Mongo client, with a documented default.** The old code
skipped creation entirely when `MONGODB_URI` was unset in the "production" branch,
which reproduces K-2 silently. Now the URI defaults to
`mongodb://localhost:27017/` and the database name to `lalistitadev` through a new
`MONGODB_DB` variable.

**D5 — Fold in K-3 while rewriting the same function.** `app.database` used to
point at `"lalistita"` while every consumer used `lalistitadev`. Rewriting this
function and knowingly leaving a wrong value in it would be shipping a trap; it
is a one-line correction and is called out in the commit.

**D6 — SECRET_KEY becomes configurable, same default.** `os.getenv('SECRET_KEY',
'secret!')` preserves behaviour exactly while allowing the real value to live in
the environment. K-13 wants a real rotation; that stays a separate unit.

`MongoClient` is lazy, so importing the app does not open a connection. That
matters: a WSGI import must not block.

## Non-goals

- SocketIO worker class. Without `eventlet`/`gevent` in the tree, `async_mode` is
  `threading`: SocketIO works over HTTP long-polling, WebSocket transport is not
  available. Documented, not solved.
- Rotating `SECRET_KEY`, restricting CORS, or authenticating the scraper routes
  (K-13).
- Choosing the single deploy story. `Procfile` and `gunicorn_config.py` are left
  untouched.

## Tasks

- [ ] T1 `app.py`: `create_app()` + `_init_mongo()`, `__main__` reduced to two lines
- [ ] T2 `main.py`: WSGI entry point
- [ ] T3 Verify factory: Mongo handle attached, 15 routes, SocketIO initialized
- [ ] T4 Verify `current_app.mongodb_client` inside a request context
- [ ] T5 Verify under real gunicorn: start it, `GET /` returns 200
- [ ] T6 Verify `python app.py` path still constructs and serves
- [ ] T7 Update docs: AGENTS traps T-2/T-3, repo-map bootstrap section, known-issues K-1/K-2/K-3/K-5

## Verification plan

| Check | Method | Expected |
| --- | --- | --- |
| Factory attaches Mongo | `create_app().mongodb_client` | not None |
| Routes registered | `len(app.url_map.iter_rules())` | 15 |
| SocketIO initialized | `socketio.server` / test client connects | no error |
| Import does not block | time `import main` | fast (lazy client) |
| `current_app.mongodb_client` works | inside `app.app_context()` | resolves |
| Real WSGI | `gunicorn main:app`, `curl /` | 200 |
| Dockerfile CMD target exists | `ls main.py` | present |
| No new dependencies | `pip-audit` | still 0 |
