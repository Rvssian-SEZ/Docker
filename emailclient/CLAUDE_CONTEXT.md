# EmailClient — CLAUDE_CONTEXT.md

Docker Test 5 — IMAP webmail reader for home.internal Mail LXC.
FastAPI + Jinja2/HTMX + Bootstrap 5 dark. No database — IMAP is the data store.

## Infrastructure
- App: docker-test (192.168.110.50) port 8003
- Mail LXC: 192.168.110.35 port 993 (Dovecot, self-signed cert)
- Authentik: auth.home.internal (192.168.110.49)
- Step-CA: 192.168.110.41
- Docker network: itops_net (external, shared with itops/helpdesk/crm)

## Mailboxes
- nutwatch@home.internal — NUT UPS trigger receiver
- alex@home.internal
- admin@home.internal
- Master user: mailadmin / pI3xOcqEIvIO3vdeDxwreebMYujdj/W8
- Login syntax: "targetuser*mailadmin"

## Project layout
```
emailclient/
├── docker-compose.yml
├── .env                  ← never commit
├── .env.example
├── CLAUDE_CONTEXT.md
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── root_ca.crt       ← Step-CA root, copy before docker build
    ├── main.py
    ├── core/
    │   ├── config.py     ← pydantic-settings (no inline .env comments)
    │   ├── auth.py       ← OIDC: get_oidc_config, build_auth_url, exchange_code, fetch_userinfo
    │   ├── deps.py       ← require_user + RequiresLoginException
    │   └── imap.py       ← imap_for() context manager, list_messages, get_message, stats, mark/delete
    ├── routers/
    │   ├── auth.py       ← /auth/login /auth/callback /auth/logout
    │   └── mail.py       ← /mail (inbox) /mail/{uid} (detail) /mail/{uid}/unseen /mail/{uid}/delete
    └── templates/
        ├── base.html
        ├── auth/login.html
        └── mail/
            ├── inbox.html     ← filter bar + HTMX list refresh
            ├── message.html   ← message detail, mark unread, delete
            └── _list.html     ← HTMX partial (message rows only)
```

## Auth
- Session key "user": {sub, name, email, username, role}
- Role: "admin" if in Authentik group "emailclient-admin", else "user"
- RequiresLoginException → 302 /auth/login (registered in main.py exception_handler)
- OIDC discovery: https://auth.home.internal/application/o/emailclient/
- httpx uses CA_CERT = /app/root_ca.crt for all Authentik requests

## IMAP (core/imap.py)
- imap_for(mailbox_user): context manager, handles login/logout
- SSL: check_hostname=False, CERT_NONE (self-signed on Mail LXC)
- list_messages(): search criteria built from unread_only + search_q; msg_type filtered post-fetch
- _classify(subject): "fault" | "normal" (normal ac / recovery) | "other"
- Filters: HTMX GET /mail with HX-Request header → returns _list.html partial only

## Key gotchas
- root_ca.crt must be in app/ before docker build
- pydantic-settings: no inline comments on .env value lines
- TemplateResponse(request, "template.html", {...}) — Starlette 0.41+ signature
- itops_net must exist before compose up: docker network create itops_net
- Dovecot master passdb must have pass=no (not pass=yes) — otherwise PAM re-checks target user

## Adding a new mailbox user
On Mail LXC (192.168.110.35):
  bash /root/add-mail-user.sh <username> <password>
Then add username to MAIL_USERS in .env and restart the container.

## Deployment
```bash
scp -r emailclient/ root@192.168.110.50:/opt/emailclient
# copy Step-CA root cert
scp /path/to/root_ca.crt root@192.168.110.50:/opt/emailclient/app/root_ca.crt
ssh root@192.168.110.50
cd /opt/emailclient
cp .env.example .env && nano .env   # fill SECRET_KEY + OIDC values
docker compose up -d --build
```
