# IT Ops Portal — Claude AI Context File

Share this file with Claude when troubleshooting, extending, or deploying this app.

---

## What this app is

A self-hosted IT operations portal built with FastAPI + PostgreSQL + Authentik OIDC.
Single web app, single database, three modules:

- **IT Assets** — track laptops, monitors, phones etc; assign to users; warranty tracking
- **Users** — synced from Authentik OIDC on login; editable extended fields (phone, dept, title)
- **Equipment Lending** — loan projectors/cameras/gear to users, due dates, overdue alerts

---

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Language | Python 3.12 | |
| Framework | FastAPI | Sync (not async) route handlers |
| ORM | SQLAlchemy 2 | Sync sessions via `SessionLocal` |
| Migrations | Alembic | `alembic upgrade head` runs on container start |
| Templates | Jinja2 + HTMX | Bootstrap 5 dark theme, no build step |
| Auth | Authentik OIDC | OAuth2 Authorization Code flow |
| Database | PostgreSQL 16 | Single shared DB for all modules |
| Container | Docker Compose | 3 services: app, db, pgadmin |
| Sessions | Starlette SessionMiddleware | Signed cookie, 7-day expiry |

---

## Project layout

```
itops/
├── docker-compose.yml
├── .env                         # Never commit — copy from .env.example
├── .env.example
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── alembic.ini
    ├── root_ca.crt              # Your internal CA cert (Step-CA or similar)
    ├── main.py                  # App entrypoint, middleware, exception handlers
    ├── core/
    │   ├── config.py            # Pydantic settings — reads all env vars
    │   ├── database.py          # SQLAlchemy engine, SessionLocal, Base, get_db()
    │   ├── auth.py              # OIDC flow: state, code exchange, userinfo, upsert
    │   └── deps.py              # require_user dependency + RequiresLoginException
    ├── models/
    │   ├── __init__.py          # Imports all models (required for Alembic)
    │   ├── user.py              # User table (synced from Authentik)
    │   ├── asset.py             # ITAsset table
    │   └── equipment.py         # Equipment + LendingRecord tables
    ├── routers/
    │   ├── auth.py              # /auth/login, /auth/callback, /auth/logout
    │   ├── users.py             # /users/
    │   ├── assets.py            # /assets/
    │   └── equipment.py         # /equipment/ + /equipment/lending
    ├── templates/
    │   ├── base.html            # Sidebar layout, Bootstrap 5 dark
    │   ├── auth/login.html
    │   ├── users/{list,detail}.html
    │   ├── assets/list.html
    │   └── equipment/{list,lending}.html
    └── migrations/
        ├── env.py               # Alembic env — reads DATABASE_URL from environment
        ├── script.py.mako       # Required Alembic template file
        └── versions/            # Migration files
```

---

## Environment variables

All required. No inline comments allowed on value lines (pydantic-settings doesn't strip them).

```env
# PostgreSQL
POSTGRES_DB=itops
POSTGRES_USER=itops
POSTGRES_PASSWORD=<strong password>

# App
SECRET_KEY=<64 hex chars — generate: python3 -c "import secrets; print(secrets.token_hex(32))">
APP_BASE_URL=https://itops.yourdomain.com
APP_PORT=8000

# Authentik OIDC
AUTHENTIK_BASE_URL=https://auth.yourdomain.com
AUTHENTIK_SLUG=itops
AUTHENTIK_CLIENT_ID=<from Authentik provider settings>
AUTHENTIK_CLIENT_SECRET=<from Authentik provider settings>

# pgAdmin
PGADMIN_EMAIL=admin@yourdomain.com
PGADMIN_PASSWORD=<strong password>
PGADMIN_PORT=5050
```

---

## Database schema

### users
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| sub | String UNIQUE | OIDC subject claim from Authentik |
| username | String UNIQUE | preferred_username from OIDC |
| email | String UNIQUE | |
| full_name | String | from OIDC, re-synced on login |
| phone | String | locally editable |
| department | String | locally editable |
| title | String | locally editable |
| location | String | locally editable |
| groups | String | comma-separated Authentik groups |
| notes | Text | locally editable |
| is_active | Boolean | |
| created_at / updated_at | DateTime | |

### it_assets
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| name | String | e.g. "Dell XPS 15" |
| asset_tag | String UNIQUE | e.g. "AST-0042" |
| category | Enum | Laptop/Desktop/Monitor/Phone/Tablet/Printer/Networking/Server/Peripheral/Other |
| manufacturer, model | String | |
| serial_number | String | |
| status | Enum | available/assigned/maintenance/retired/lost |
| assigned_user_id | FK → users.id | nullable |
| purchase_date, warranty_expiry | Date | |
| purchase_price, supplier | String | |
| notes | Text | |

### equipment
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| name | String | e.g. "Epson EB-X51 Projector" |
| category | String | free text |
| serial_number, asset_tag | String | |
| status | Enum | available/on_loan/maintenance/retired |
| location | String | storage location |
| notes | Text | |

### lending_records
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| equipment_id | FK → equipment.id | |
| user_id | FK → users.id | borrower |
| lent_by_id | FK → users.id | staff who processed it |
| lent_at | DateTime | auto-set |
| due_at | DateTime | nullable |
| returned_at | DateTime | NULL = still on loan |
| notes | Text | |

---

## Auth flow (OIDC)

1. User hits any protected route → `require_user` dependency raises `RequiresLoginException`
2. `main.py` exception handler redirects to `/auth/login?next=<url>`
3. `/auth/login` generates signed state token (itsdangerous), stores in session, redirects to Authentik
4. Authentik redirects to `/auth/callback?code=...&state=...`
5. App verifies state, exchanges code for tokens at Authentik token endpoint
6. App fetches userinfo from Authentik userinfo endpoint
7. App upserts User record in local DB (creates if new, updates name/email/groups)
8. User dict stored in signed session cookie
9. Subsequent requests: `require_user` reads session, looks up User in DB

**Key OIDC URLs (Authentik):**
- Authorize: `{AUTHENTIK_BASE_URL}/application/o/authorize/`
- Token: `{AUTHENTIK_BASE_URL}/application/o/token/`
- Userinfo: `{AUTHENTIK_BASE_URL}/application/o/userinfo/`
- Logout: `{AUTHENTIK_BASE_URL}/application/o/{AUTHENTIK_SLUG}/end-session/`

---

## Authentik setup (required before first login)

1. **Providers** → New → OAuth2/OpenID Provider
   - Client type: `Confidential`
   - Redirect URI: `https://itops.yourdomain.com/auth/callback`
   - Scopes: `openid`, `profile`, `email`
   - Note the Client ID and Client Secret

2. **Applications** → New
   - Slug: `itops` (must match `AUTHENTIK_SLUG` in .env)
   - Provider: select the one above

---

## Internal CA / self-signed TLS

If your Authentik instance uses a certificate from an internal CA (e.g. Step-CA):

1. Copy your root CA cert to `app/root_ca.crt` before building
2. The Dockerfile installs it via `update-ca-certificates`
3. The `REQUESTS_CA_BUNDLE` and `SSL_CERT_FILE` env vars in docker-compose.yml point httpx at the system cert store

Without this, the token exchange with Authentik will fail with:
`SSL: CERTIFICATE_VERIFY_FAILED unable to get local issuer certificate`

---

## Alembic / migrations

**First deploy on a new host:**
```bash
docker compose up -d
# DB is empty, alembic upgrade head runs the init migration automatically
```

**After changing models:**
```bash
docker compose exec app alembic revision --autogenerate -m "describe change"
# Copy the generated file out to the host:
docker cp itops_app:/app/migrations/versions/<new_file>.py ./app/migrations/versions/
docker compose down && docker compose build app && docker compose up -d
```

**If alembic_version table is out of sync:**
```bash
docker compose exec db psql -U itops -d itops -c "DELETE FROM alembic_version;"
docker compose exec app alembic stamp head
```

**script.py.mako missing error:**
This file must exist at `app/migrations/script.py.mako`. It is included in this zip.
If it goes missing, it gets lost when containers are rebuilt — always keep it on the host.

---

## Common errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `TypeError: exceptions must derive from BaseException` | Old `deps.py` raises `RedirectResponse` instead of an exception | Replace `deps.py` and `main.py` with versions using `RequiresLoginException` |
| `TypeError: unhashable type: 'dict'` | Old Starlette `TemplateResponse(name, {"request": request, ...})` signature | Update to `TemplateResponse(request, name, {...})` — new signature in Starlette 0.41+ |
| `AmbiguousForeignKeysError on User.lendings` | `LendingRecord` has two FKs to `users` | Add `foreign_keys="LendingRecord.user_id"` to the `lendings` relationship in `user.py` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Internal CA not trusted inside container | Copy `root_ca.crt` to `app/` and rebuild |
| `Can't locate revision identified by '<hash>'` | Migration file lost after container rebuild | Rebuild image (file now in `app/migrations/versions/`), then `DELETE FROM alembic_version` and `alembic stamp head` |
| `FileNotFoundError: migrations/script.py.mako` | Template file missing | It's included in this zip at `app/migrations/script.py.mako` |
| `.env inline comments` | pydantic-settings includes comment text in value | Remove all inline comments — put comments on their own lines |

---

## Useful commands

```bash
# View live logs
docker compose logs app -f

# Run a migration after model changes
docker compose exec app alembic revision --autogenerate -m "my change"

# Open a psql shell
docker compose exec db psql -U itops -d itops

# Rebuild after code changes on host
docker compose down && docker compose build app && docker compose up -d

# Check env vars loaded in container
docker compose exec app env | grep -E 'AUTHENTIK|APP_BASE|SECRET'
```

---

## Reverse proxy (NPM)

Once working on direct IP, put it behind Nginx Proxy Manager:

1. Add A record in DNS: `itops.yourdomain.com` → NPM IP
2. NPM proxy host: forward to `<docker-host-ip>:8000`
3. Enable SSL with your wildcard cert
4. Update `.env`: `APP_BASE_URL=https://itops.yourdomain.com`
5. Update Authentik redirect URI to match
6. Set `https_only=True` in `main.py` SessionMiddleware
7. Rebuild: `docker compose down && docker compose build app && docker compose up -d`
