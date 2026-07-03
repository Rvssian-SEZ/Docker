# IT Ops Portal

Unified IT asset management, user directory, and equipment lending — single FastAPI app with a shared PostgreSQL database, authenticated via Authentik OIDC.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI |
| ORM / Migrations | SQLAlchemy 2, Alembic |
| Frontend | Jinja2 templates, Bootstrap 5, HTMX |
| Auth | Authentik (OIDC) |
| Database | PostgreSQL 16 |
| Container | Docker Compose |

## Modules

- **IT Assets** — track laptops, monitors, phones etc; assign to users; warranty tracking
- **Users** — OIDC-synced from Authentik; editable extended details (phone, department, title)
- **Equipment** — projectors, cameras and other loanable gear
- **Lending** — loan equipment to users, track due dates, process returns, overdue alerts

---

## Setup

### 1. Authentik — Create an OAuth2/OIDC Provider

In your Authentik admin panel:

1. **Providers** → New → **OAuth2/OIDC Provider**
   - Name: `ITOps`
   - Client type: `Confidential`
   - Redirect URI: `https://itops.home.internal/auth/callback` (or your APP_BASE_URL + `/auth/callback`)
   - Scopes: `openid`, `profile`, `email`
   - Note the **Client ID** and **Client Secret**

2. **Applications** → New
   - Name: `IT Ops Portal`
   - Slug: `itops`  ← this is `AUTHENTIK_SLUG`
   - Provider: select the one you just created

3. Optionally assign the application to a group to restrict access.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in all required values
# Generate SECRET_KEY: python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Start

```bash
docker compose up -d
```

Alembic migrations run automatically on container start.

### 4. First login

Navigate to `http://localhost:8000` (or your APP_BASE_URL).  
You'll be redirected to Authentik. After authenticating, a local User record is created/updated automatically.

---

## Development

For live reload, uncomment the volume mount in `docker-compose.yml`:

```yaml
volumes:
  - ./app:/app
```

Then restart with:

```bash
docker compose up -d --build
```

### Running Alembic manually

```bash
# Generate a migration after model changes
docker compose exec app alembic revision --autogenerate -m "describe your change"

# Apply migrations
docker compose exec app alembic upgrade head

# Rollback one step
docker compose exec app alembic downgrade -1
```

### pgAdmin

Available at `http://localhost:5050`.  
Add a server connection:
- Host: `db`
- Port: `5432`
- Username/Password: from your `.env`

---

## Project Layout

```
itops/
├── docker-compose.yml
├── .env.example
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── alembic.ini
    ├── main.py                  # FastAPI app, middleware, router registration
    ├── core/
    │   ├── config.py            # Pydantic settings (reads .env)
    │   ├── database.py          # SQLAlchemy engine + session
    │   ├── auth.py              # OIDC flow, session helpers
    │   └── deps.py              # FastAPI dependencies (require_user)
    ├── models/
    │   ├── user.py              # User (synced from Authentik)
    │   ├── asset.py             # ITAsset
    │   └── equipment.py         # Equipment + LendingRecord
    ├── routers/
    │   ├── auth.py              # /auth/login, /callback, /logout
    │   ├── users.py             # /users/
    │   ├── assets.py            # /assets/
    │   └── equipment.py         # /equipment/ + /equipment/lending
    ├── templates/
    │   ├── base.html            # Sidebar layout (Bootstrap 5 dark)
    │   ├── auth/login.html
    │   ├── users/{list,detail}.html
    │   ├── assets/list.html
    │   └── equipment/{list,lending}.html
    └── migrations/
        ├── env.py               # Alembic env (reads DATABASE_URL)
        └── versions/            # Migration files (auto-generated)
```

---

## Adding to NPM

Once running, add a proxy host in Nginx Proxy Manager:
- Domain: `itops.home.internal`
- Forward host: `itops_app` (or the container name)
- Forward port: `8000`
- SSL: use your Step-CA wildcard cert

Then set `APP_BASE_URL=https://itops.home.internal` in `.env` and `AUTHENTIK_SLUG` redirect URI to match.

Set `https_only=True` in `main.py` SessionMiddleware once behind HTTPS.

---

## Notes

- **User data ownership**: Core identity (name, email) comes from Authentik and is re-synced on every login. Extended fields (phone, department, title, notes) are edited locally and are not overwritten.
- **OIDC groups**: Authentik group memberships are stored as a comma-separated string in `users.groups`. Future work: use this for role-based access control within the app.
- **No API yet**: The app is HTML-first (Jinja2 + HTMX). The FastAPI JSON API is available at `/api/docs` for future integrations (e.g. a mobile app or Ansible inventory script).
