# CLAUDE_CONTEXT.md — IT Helpdesk (Docker Test 2)

Use this file to restore context when continuing work on this project in a new chat.

---

## What this is

A self-hosted IT helpdesk web application running on `docker-test` (192.168.110.50), port **8001**.
Part of the "Docker Test" series sharing a single PostgreSQL 16 database (`itops`) with the IT Ops Portal (port 8000).

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI + Jinja2 + HTMX |
| Frontend | Bootstrap 5 dark theme |
| Database | PostgreSQL 16 — shared `itops` DB on `itops_db` container |
| Auth | Authentik OIDC (external at `https://auth.home.internal`) |
| Email | aiosmtplib async SMTP via Mail LXC (192.168.110.35, port 25, no auth) |
| Container | Docker Compose — joins `itops_itops_net` external network |

---

## Infrastructure

| Host | IP | Purpose |
|---|---|---|
| docker-test | 192.168.110.50 | Runs this app |
| itops_db | (container) | PostgreSQL 16, DB name: `itops` |
| auth.home.internal | 192.168.110.49 | Authentik SSO |
| Step-CA | 192.168.110.41 | Internal CA (root_ca.crt baked into image) |
| Mail LXC | 192.168.110.35 | Postfix SMTP relay, port 25 |

---

## Project layout

```
/opt/docker/helpdesk/          ← live location on docker-test
├── docker-compose.yml
├── .env                       ← not in git
├── .env.example
├── README.md
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── alembic.ini
    ├── main.py
    ├── root_ca.crt            ← not in git, baked into image for Step-CA trust
    ├── core/
    │   ├── auth.py            ← Authentik OIDC flow, session cookies
    │   ├── config.py          ← pydantic-settings, all env vars
    │   ├── database.py        ← SQLAlchemy engine + SessionLocal
    │   ├── deps.py            ← require_user / require_tech / require_admin deps
    │   └── email.py           ← aiosmtplib async notifications
    ├── models/
    │   └── models.py          ← User + ITAsset (extend_existing) + hd_tickets + hd_ticket_updates
    ├── routers/
    │   ├── auth.py            ← /auth/login, /auth/callback, /auth/logout
    │   ├── tickets.py         ← full ticket CRUD + HTMX endpoints
    │   ├── admin.py           ← /admin dashboard (tech/admin only)
    │   └── reports.py         ← /reports KPI data + CSV export
    ├── migrations/
    │   ├── env.py             ← scoped to hd_* tables only, version_table=alembic_version_helpdesk
    │   └── versions/
    └── templates/
        ├── base.html
        ├── error.html
        ├── auth/login.html
        ├── admin/dashboard.html
        ├── partials/asset_options.html
        ├── reports/kpi.html
        └── tickets/
            ├── list.html
            ├── detail.html
            └── create.html
```

---

## Database

Shares the `itops` PostgreSQL database. Helpdesk owns only:

| Table | Description |
|---|---|
| `hd_tickets` | Tickets with status, priority, category, SLA, FK to users + it_assets |
| `hd_ticket_updates` | Replies and internal notes per ticket |
| `alembic_version_helpdesk` | Alembic version tracking (isolated from itops) |

References (read/write, never recreated by this app's Alembic):

| Table | Key columns used |
|---|---|
| `users` | id, email, username, full_name, phone, department, title, groups |
| `it_assets` | id, name, asset_tag, category, manufacturer, model, serial_number, assigned_user_id, status |

**Important:** The FK column in `it_assets` is `assigned_user_id` (NOT `assigned_to_id`).
The asset type column is `category` (NOT `asset_type`).

---

## Roles

Derived from Authentik group membership on every login — never stored locally.

| Authentik Group | Role | Permissions |
|---|---|---|
| `helpdesk-admin` | admin | All tickets, KPI reports, CSV export, assign, status change |
| `helpdesk-tech` | tech | All tickets, dashboard, assign, status change, internal notes |
| (none) | user | Own tickets only, submit + reply + reopen |

---

## Auth — known quirks

- `httpx.AsyncClient` must use `verify="/app/root_ca.crt"` (both calls in `core/auth.py`) — Step-CA cert is not in certifi's bundle
- `root_ca.crt` is fetched from `https://192.168.110.41/roots.pem` and baked into the Docker image via Dockerfile
- Authentik OIDC redirect URI: `http://192.168.110.50:8001/auth/callback`
- Session cookie: `hd_session` (HMAC-SHA256 signed, 7-day expiry)
- State cookie: `hd_oauth_state` (5-minute expiry)

---

## Docker network

The compose file uses:
```yaml
networks:
  itops_net:
    external: true
    name: itops_itops_net   ← Compose-prefixed name of the itops stack network
  helpdesk_int:
    driver: bridge
```

The itops stack must be running before helpdesk starts.

---

## Alembic

- Version table: `alembic_version_helpdesk` (isolated — does not touch itops `alembic_version`)
- `include_object` filter: only manages tables starting with `hd_`
- Runs automatically on container start via CMD in Dockerfile

If migration state gets corrupted:
```bash
docker exec itops_db psql -U itops -d itops -c "DELETE FROM alembic_version_helpdesk;"
docker compose restart helpdesk
```

---

## Email notifications

All via `BackgroundTasks` — failures are logged, never crash requests.

| Trigger | Recipients |
|---|---|
| Ticket created | Assigned tech or all techs + HELPDESK_ADMIN_EMAIL |
| Reply added | Ticket owner + assigned tech (excluding author) |
| Status changed | Ticket owner + assigned tech |
| Resolved/Closed | Ticket owner only |

---

## SLA

| Priority | Target |
|---|---|
| critical | 4 hours |
| high | 8 hours |
| medium | 72 hours |
| low | 120 hours |

Overdue tickets show a pulsing red badge in list and admin dashboard.

---

## KPI Reports (/reports)

Tech/admin only. Three periods: Monthly / Quarterly / Yearly.

Charts (Chart.js, rendered client-side from `/reports/data` JSON endpoint):
- Tickets opened vs closed (bar)
- SLA compliance % (line)
- Avg resolution time in hours (line)
- By category (donut)
- Per technician count + avg hours (horizontal bar + table)

CSV export: `/reports/export/csv?year=YYYY`

---

## Known fixes applied during deployment

1. `pydantic-settings` was missing from `requirements.txt` — added `pydantic-settings==2.6.1`
2. Shared `alembic_version` table had stale itops revision — deleted row + added `version_table="alembic_version_helpdesk"` to both `context.configure()` calls in `migrations/env.py`
3. Docker network name is `itops_itops_net` not `itops_net` — fixed in `docker-compose.yml` with `name:` override
4. `httpx` SSL verification fails with internal CA — fixed by passing `verify="/app/root_ca.crt"` to both `AsyncClient()` calls in `core/auth.py`
5. Form `asset_id` and `on_behalf_of` fields send empty string `""` not `None` — fixed with `str = Form(default="")` + manual int conversion
6. `it_assets` FK column is `assigned_user_id` not `assigned_to_id` — fixed in `models/models.py` and all router queries
7. `it_assets` type column is `category` not `asset_type` — fixed in `models/models.py`
8. Device list empty on ticket create for tech/admin — fixed by pre-loading assets for current user + plain JS `fetch()` on user dropdown change (HTMX attribute approach with `{value}` placeholder didn't work)

---

## Common commands

```bash
# On docker-test
cd /opt/docker/helpdesk

# Start / restart
docker compose up -d
docker compose restart helpdesk

# Full rebuild (after code changes)
docker compose up -d --build

# Logs
docker compose logs -f helpdesk
docker compose logs helpdesk --tail=50

# Check tables
docker exec itops_db psql -U itops -d itops -c "\dt hd_*"

# Check users
docker exec itops_db psql -U itops -d itops -c "SELECT id, email, full_name, groups FROM users;"

# Check assets
docker exec itops_db psql -U itops -d itops -c "SELECT id, name, assigned_user_id, status FROM it_assets;"

# Manual migration reset
docker exec itops_db psql -U itops -d itops -c "DELETE FROM alembic_version_helpdesk;"
```

---

## GitHub

Repo: `https://github.com/Rvssian-SEZ/Docker/tree/main/helpdesk`

Workflow for changes:
1. Edit files in `/opt/docker/helpdesk/app/` on docker-test
2. `docker compose up -d --build` to apply
3. SCP changed files to Mac: `scp user@192.168.110.50:/opt/docker/helpdesk/app/changed_file.py ~/Docker/helpdesk/app/`
4. `cd ~/Docker && git add helpdesk/ && git commit -m "describe change" && git push`
