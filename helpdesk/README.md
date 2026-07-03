# IT Helpdesk

A self-hosted helpdesk running on `docker-test` (192.168.110.50), sharing the `itops` PostgreSQL
database with the ITOps asset management app. Authenticates via Authentik OIDC.

---

## Prerequisites

- `itops` Docker stack is running (`docker-test` host)
- `itops_net` Docker network exists
- `itops_db` container is healthy (PostgreSQL 16 with `itops` database)
- Authentik instance reachable at your `AUTHENTIK_BASE_URL`

---

## 1. Authentik — create the OIDC provider

1. Log into Authentik Admin → **Applications → Providers → Create**
2. Choose **OAuth2/OpenID Provider**
3. Configure:
   - **Name:** `IT Helpdesk`
   - **Client type:** `Confidential`
   - **Redirect URIs:** `http://192.168.110.50:8001/auth/callback`
   - **Scopes:** `openid`, `profile`, `email`, `groups`
4. Copy the **Client ID** and **Client Secret**
5. Create an **Application** linked to this provider

### Authentik Groups for roles

Create two groups in Authentik:

| Group name | Role in Helpdesk |
|---|---|
| `helpdesk-tech` | Technician — sees all tickets, can assign, update, change status |
| `helpdesk-admin` | Admin — all tech permissions + reports |

Users not in either group get `user` role (see only their own tickets).

---

## 2. Configure environment

```bash
cd /opt/docker/helpdesk    # or wherever you place this
cp .env.example .env
nano .env                  # fill in all CHANGE_ME values
```

Key values:
- `ITOPS_DB_PASSWORD` — must match the password in your `itops` stack `.env`
- `SECRET_KEY` — generate with `openssl rand -hex 32`
- `AUTHENTIK_BASE_URL` — e.g. `https://auth.home.internal`
- `SMTP_HOST` / `SMTP_PORT` / credentials — your internal mail relay

---

## 3. Start the stack

```bash
# Confirm itops stack is up first
docker compose -f /opt/docker/itops/docker-compose.yml ps

# Start helpdesk
docker compose up -d

# Check logs
docker compose logs -f helpdesk
```

Alembic will automatically create the `hd_tickets` and `hd_ticket_updates` tables on first start.
It will **not** touch the existing `users` or `it_assets` tables.

---

## 4. Accessing the app

| URL | Description |
|---|---|
| `http://192.168.110.50:8001` | Helpdesk (redirects to `/tickets`) |
| `http://192.168.110.50:8001/admin` | Tech/Admin dashboard |
| `http://192.168.110.50:8001/reports` | KPI reports |

Add a DNS entry `helpdesk.home.internal → 192.168.110.50` and proxy via NPM if you want HTTPS.

---

## Architecture

```
docker-test (192.168.110.50)
├── helpdesk_app (port 8001)
│   ├── Connects to itops_net → itops_db:5432/itops
│   ├── Tables: hd_tickets, hd_ticket_updates (new)
│   └── References: users, it_assets (existing, read/write)
└── [itops_app already running on port 8000]
```

The helpdesk shares the `itops` database. No duplicate user records — it reads the same
`users` and `it_assets` tables created by the ITOps app.

---

## Roles

| Role | Ticket visibility | Actions |
|---|---|---|
| `user` | Own tickets only | Submit, reply, reopen |
| `tech` | All tickets | All above + assign, change status, internal notes, dashboard |
| `admin` | All tickets | All above + KPI reports, CSV export |

Roles are derived from Authentik group membership on every login.

---

## Email notifications

| Event | Recipients |
|---|---|
| Ticket created | Assigned tech (if any), else all techs + `HELPDESK_ADMIN_EMAIL` |
| Reply added | Ticket owner + assigned tech (excluding the author) |
| Status changed | Ticket owner + assigned tech |
| Resolved / Closed | Ticket owner |

---

## SLA definition

| Priority | Resolution target |
|---|---|
| Critical | 4 hours |
| High | 8 hours |
| Medium | 72 hours |
| Low | 120 hours |

SLA is calculated from ticket creation time. Overdue tickets show a pulsing badge in the UI and are
highlighted on the admin dashboard.

---

## KPI Reports (tech/admin only)

Navigate to `/reports`. Select period (Monthly / Quarterly / Yearly) and year.

Metrics:
- **Volume** — tickets opened vs closed per period
- **SLA compliance** — % of closed tickets resolved within SLA
- **Avg resolution time** — mean hours to close
- **By category / priority** — distribution donut charts
- **Per technician** — ticket count and avg resolution time

Export to CSV via the **Export CSV** button (filtered by year).

---

## First migration (if Alembic doesn't auto-run)

```bash
docker compose exec helpdesk alembic revision --autogenerate -m "init helpdesk tables"
docker compose exec helpdesk alembic upgrade head
```

---

## NPM reverse proxy (optional)

Add a Proxy Host in NPM:
- **Domain:** `helpdesk.home.internal`
- **Forward host:** `192.168.110.50`
- **Forward port:** `8001`
- **SSL:** use your Step-CA wildcard cert

Update `APP_BASE_URL` in `.env` to `https://helpdesk.home.internal` and update
the Authentik redirect URI accordingly.
