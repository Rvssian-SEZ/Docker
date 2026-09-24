# Coffer

Self-hosted, single-tenant business-operations app: ledger transactions, envelope budgeting,
contracts/subscriptions with renewal tracking, consumable/checkoutable inventory, and reporting/exports.
Elixir + Phoenix LiveView, Postgres, OIDC login via Authentik. See `AGENTS.md` for the full spec this was
built against.

## Running it

This app is designed to run in Docker — there's no supported bare-metal/local `mix phx.server` workflow
documented here, since every deployment so far has been container-based.

1. Copy `.env.example` to `.env` and fill in real values (`SECRET_KEY_BASE` — generate with `mix
   phx.gen.secret` or `openssl rand -base64 48`; `POSTGRES_PASSWORD` — any strong random string; the
   `OIDC_*` values come from registering an OAuth2/OIDC Provider + Application in your Authentik
   instance, redirect URI `<your-host>/auth/callback`).
2. `docker compose up -d --build`. Migrations and the base-currency seed run automatically on boot (spec
   §11 — convenient for test/staging; see below for promoting past that).
3. Visit the app at whatever host/port you exposed. Login redirects to Authentik.

### Local dev tweaks

Copy `docker-compose.override.yml.example` to `docker-compose.override.yml` (gitignored, personal —
compose picks it up automatically) for things like exposing the Postgres port to the host.

### Promoting to a hardened deployment

The base `docker-compose.yml` is intentionally test/staging-oriented (spec §11). Promoting further is
meant to be a config change, not a rebuild:

- **TLS**: put a reverse proxy in front (nginx, Caddy, NPM, etc.) doing TLS termination, and set
  `URL_SCHEME=https` + `URL_PORT=443` in `.env` so the app generates correct absolute URLs (OIDC
  redirect_uri, etc.) even though it only ever listens on plain HTTP internally. No compose or code
  change needed for this — confirmed working this way against a real reverse proxy.
- **Resource limits / restart policy / log rotation**: layer `docker-compose.prod.yml` on top:
  ```
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
  ```
- **Backups**: `./scripts/backup.sh [output_dir]` dumps the database (via `pg_dump`, not a raw
  filesystem copy) and archives the `app_storage` volume. Run it on a schedule (cron) for anything that
  actually matters.

## Migrations on start

`docker-compose.yml`'s `app` service runs migrations (and the base-currency seed) automatically every
time the container starts — convenient for test/staging, but for a deployment where migrations should be
a deliberate, reviewed, out-of-band step, run them explicitly instead:

```
docker compose run --rm app /app/bin/migrate
```

and change the image's `CMD` to skip the automatic migrate step.

## Learn more

* Phoenix: https://phoenix.hexdocs.pm/overview.html
* Deployment guides: https://phoenix.hexdocs.pm/deployment.html
