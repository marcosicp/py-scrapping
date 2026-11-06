# Feature: local-docker-prod-parity

| Field | Value |
| --- | --- |
| Status | blocked on data (image verified) |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `main` (verification only; no source writes yet) |
| Created | 2026-06-14 |

## Problem

Every deploy story in this repo is verified by reading files, not by running the
image: `docs/agent-context/deploy-render.md` marks its end-to-end checks as
📖 INFERRED because the live Render URL was never reached from a session, and
the recent Coolify question has the same shape — "the same Dockerfile, so the
same image", argued from the Dockerfile rather than observed.

Render has been failing in practice. Before moving the deploy to a local Coolify,
the image has to be proven runnable as production: built from this worktree,
started with the production entry point, serving the SPA, reading Mongo, and
able to launch Chromium for the scrapers.

## Goal

One recorded round of "local, as if production": `docker build` from this tree,
`docker run` with production-shaped env, and an observed result for every
production surface. No source change unless a check fails.

## Non-goals

- No scraper run against the live database. `replace_products` REPLACES the
  `supermercado`/`categoria` slice (AGENTS.md rule 7), so the browser is proven
  with a standalone Chrome smoke test inside the container, not with a scrape.
- No Coolify deployment and no `render.yaml` change.
- No commit, push or PR.

## Decisions

| Decision | Why |
| --- | --- |
| Use the Atlas URI from `.env` (read-only endpoints only) | A real data path proves more than an empty local Mongo, and every check below is a GET. |
| Publish the container on host port **3000** (`-p 3000:10000`) | `adminpro/src/app/service/app.service.ts:21` hardcodes `http://127.0.0.1:3000/api/productos/agrupados`. Publishing on 3000 makes the *unfixed* SPA work against the container, which also demonstrates the size of that defect: any other host port leaves the grid empty. |
| `--build-arg INSTALL_CHROMIUM=1` (the default) | Chromium is what the deploy actually depends on; a lean image proves nothing about scraping. |
| Generated throwaway `SECRET_KEY` | The container must not inherit the `"secret!"` default (K-13), and this key is not meant to survive the test. |

## Checks

Each line is closed only with an observed result.

- [x] C1 `docker build` succeeds from this worktree (`lalistita:local`, 988 MB, exit 0)
- [x] C2 image carries `/usr/bin/chromium` and `/usr/bin/chromedriver`
- [x] C3 `.env` is **not** in the image (`/app/.env` absent) — the `.dockerignore` fix; bundle present at `/app/static/index.html`
- [x] C4 container boots, gunicorn 26.2.0 listens on 10000, worker `gthread`, health `healthy`
- [x] C5 `GET /` answers 200 (SPA bundle present)
- [x] C6 `GET /api/scrapers` lists the five slugs without Mongo being needed
- [ ] C7 `GET /api/productos/agrupados` returns a non-empty grouped payload from Atlas — **environment, not the image**: the endpoint answers 200 with zero rows, no `error` key (success path), and `lalistitadev.productos` holds 0 documents on `cluster0.fosxvtw.mongodb.net` (server 8.0.37). The cluster is empty for this user.
- [x] C8 `GET /scrape` answers 200 (registry-generated monitor page)
- [x] C9 Socket.IO handshake answers on the polling transport (`threading` async mode)
- [x] C10 Chromium + chromedriver launch a page inside the container (`chrome=156.0.8078.79`, SPA title rendered) — **ran once, before the no-browser-tests constraint below**

## Constraints

- **Never run browser tests again.** The user forbade them explicitly (token budget).
  No Selenium smoke tests, no Playwright/ego-browser, no “just one page load” — not
  as a check, not to diagnose a check. UI verification goes back to static reading
  plus a `curl` of the endpoint payload (AGENTS.md §8), or the human looks at it.

## Verification log

Round 1 — hypothesis: the Dockerfile is the deploy contract, so the image is
runnable as production. Commands: `docker build`, `docker run -p 3000:10000` with
production-shaped env, then one bounded read-only battery.

Observation: 9 of 10 checks green on the first attempt. Two reds, both outside the
image:

1. **Empty collection.** With the container's own Atlas credentials,
   `lalistitadev.productos` counts 0 documents and `GET /supermercados` returns the
   same zeros without an `error` key. The image serves the truth about an empty
   database.
2. **Container egress DNS is unreliable.** `mongodb+srv` resolved and answered
   (dnspython/SRV), while plain `getaddrinfo` for `example.com` failed with
   `Errno -2`, and Chrome reported `ERR_NAME_NOT_RESOLVED`. Resolver is Docker
   Desktop's `192.168.65.7`. This is a host/Docker Desktop condition, not an image
   property, and it is exactly what would break a scraper on any host.

Conclusion: the image is production-shaped (SPA, control API, monitor page,
realtime handshake, Mongo connectivity, Chromium binaries all confirmed). The
dashboard grid being empty is a *data* fact, not a hosting fact — which is worth
weighing before attributing the Render trouble to Render.

Round 2 — the Render console error, and the fix that survived it.

Hypothesis: the production 500s in the browser are `adminpro/src/app/service/app.service.ts`
hitting an absolute loopback URL, not a server defect.

Observation (from the user's Render console):

```
Access to XMLHttpRequest at 'http://127.0.0.1:3000/api/productos/agrupados' from origin
'https://p-cd22.onrender.com' has been blocked by CORS policy: Permission was denied for
this request to access the `loopback` address space.
GET http://127.0.0.1:3000/api/productos/agrupados net::ERR_FAILED
```

That is Chrome's Private Network Access, not Flask's CORS: a public HTTPS origin
may not reach `loopback`. No server-side CORS header can grant it, and no host
change can fix it — the target is the *viewer's* machine.

Fix: the request path is now relative (`/api/productos/agrupados`), so it is
same-origin with the SPA under whatever host serves it.

Verified without a browser (per the constraint above): `npm run build` wrote
`static/main-QDP3J4UR.js`; that bundle contains 0 occurrences of `127.0.0.1:3000`
and 1 of `api/productos/agrupados`; the image was rebuilt, the container serves
that same chunk, and `/`, `/scrape`, `/api/scrapers`, `/api/productos/agrupados`
all answer 200.

Correction to round 1: `lalistitadev.productos` was **not** empty at round 2 —
`/api/productos/agrupados` answered `disco=923, mami=2500` with `carre=0,
hiper=0`. The round-1 zero read is stale, not a contradiction of the image.


