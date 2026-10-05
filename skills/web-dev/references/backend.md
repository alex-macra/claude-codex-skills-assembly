# Backend

Node and TypeScript (Express, Fastify) and Python (FastAPI, Django, Flask). Shared type and validation rules live in `SKILL.md`; auth and token discipline lives in `security-review`.

## Types and layout
- **Node:** `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`; `req.body: unknown` narrowed with `schema.parse`; no `as` casts. Workspaces for monorepos, `dist/` gitignored, Node pinned in `engines` and `.nvmrc`, lockfile committed.
- **Python:** annotate every signature, `pydantic` v2 at I/O boundaries, `from __future__ import annotations`. `src/` layout for libraries, `requires-python` pinned, deps locked (`uv`, `pip-compile`, `poetry`), authored in `pyproject.toml`.

## Async
- **Node:** async by default; never block the loop with sync I/O or CPU work (`worker_threads` or another process); stream large payloads with `pipeline()`.
- **Python:** one I/O model per service; no sync I/O (`requests`, `time.sleep`, blocking drivers) in async code; CPU work via `asyncio.to_thread` or another process.

## Frameworks
- **Express and Fastify:** validate at the edge before business logic. Middleware order: security headers, CORS, rate limit, body parser, auth, routes, error handler. One router per resource. Set `trust proxy` correctly behind a load balancer.
- **FastAPI:** pydantic models for every request and response; `Depends()` for auth, sessions and settings, not module globals.
- **Django:** fat models, thin views, `select_related` and `prefetch_related` against N+1. **Flask:** `create_app()` factory and blueprints.

## Data
- Parameterized SQL always; string-built SQL is injection.
- SQLite: WAL mode, `PRAGMA foreign_keys = ON` (off by default), `busy_timeout`. Postgres: a connection pool, `LISTEN` and `NOTIFY` over polling. Index the queries you run, after `EXPLAIN ANALYZE`.
- Context managers for files, connections and locks; stream large files; `tempfile` with cleanup, not fixed `/tmp` paths. `polars` for new dataframe pipelines unless the project uses `pandas`.

## Errors, logging, concurrency
- Throw and catch specific errors; a generic catch belongs only at the top of a worker loop and re-raises after logging.
- Structured logs (`pino`, `structlog`) configured once at entry: `log.info({ caseId, ms }, 'processed')`. No `console.log` or `print` in production paths; never log secrets, tokens, bodies or PII; redaction covers every key the app handles.
- Module-level mutable state is a bug; use a lock or a store. External mutations carry idempotency keys. Transactions stay short with no network awaits inside.

## Tooling
- Node: `eslint` and `prettier` (or `biome`), `tsc --noEmit` in CI, `vitest` or `jest`.
- Python: `ruff`, `mypy` or `pyright`, `pytest`, `pre-commit`. Tests: `qa-automation`.

## Deploy and CI

Manual steps are a bug: anything done twice gets a script, anything periodic gets a job runner.

- **One thing per script** (`build`, `test`, `deploy`); inputs by flags or env, output to stdout, errors to stderr; the runbook is `--help` and the README.
- **Fail loud:** `set -euo pipefail`, non-zero on any unhandled error, never `|| true`. Idempotent, reproducible from a clean checkout with no manual installs.
- **Pipelines:** one workflow per concern (`ci.yml`, `deploy.yml`, `nightly.yml`); lint, types and tests are required checks that block merge, never advisory; reuse with `workflow_call` or composite actions; cache by lockfile hash; matrix only where meaningful; build artifacts come from CI, never a laptop. Secrets and token pinning rules: `security-review`.
- **Check before action:** a deploy script without a smoke check automates the outage. Post-deploy smoke hits the deployed URL (`see-it-live`).
- **Containers:** one process each, multi-stage builds, non-root `USER`, a `HEALTHCHECK`.
- **Scheduled jobs and backups:** idempotent, logged, with a tested restore.

### Rollback
- Every deploy has a written rollback; "redeploy the previous version" counts once it is written down.
- Keep N previous releases on disk so rollback is a symlink swap, not a rebuild.
- Migrations run before the new version starts and stay compatible with the previous app version.
- A failed post-deploy health check triggers rollback, not a debugging session on production.
- Before done: run the script on a clean machine, read a successful and a forced-failure log as an on-call stranger would, and time it.
