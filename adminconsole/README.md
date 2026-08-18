# SAA Admin Console

M365/Entra reporting + on-prem AD account management (unlock, password
reset, enable/disable, attribute edits, LAPS retrieval) for SAA's helpdesk.
**Not read-only** — every write path is high-risk by design; see
CLAUDE_CONTEXT.md for the full architecture rationale and current build
status.

## Quick start (local dev)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste the output into .env as FERNET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

First boot creates the break-glass admin (`BREAKGLASS_USERNAME`/
`BREAKGLASS_PASSWORD` from `.env`) and logs its TOTP secret **once** —
capture it into an authenticator app immediately, it is never shown again.

## Configuration

Bootstrap-only settings (DB paths, secret key, FERNET_KEY, break-glass
initial credential) live in `.env`. Everything else — Graph app
registration, Authentik SSO, AD service account, break-glass alerting,
SMTP — is configured at runtime in the in-app Settings page (Admin role,
requires re-authentication to view/edit).

## AD delegation prerequisite

Before AD account management will work against a real domain controller,
the service account configured in Settings → AD needs explicit `dsacls`
delegation for: reset password, write `lockoutTime`, write
`userAccountControl`, write to the specific non-privileged attributes this
app edits, and **read** `ms-Mcs-AdmPwd` (confidential attribute — needs an
explicit ACL grant beyond generic read-attribute delegation). This is a
manual pre-flight step, not something the app assumes exists — pilot
against one OU first.

## Deployment

Docker Compose, deployed to saa-docker (10.10.160.59). See
CLAUDE_CONTEXT.md's "Deploy procedure" section.
