# SAA Admin Console — Claude Context

## What this is
Combines read-only M365/Entra reporting with on-prem AD account management
(unlock, password reset, enable/disable, attribute edits, LAPS retrieval).
Built from `o365-dashboard-spec.md` (Alex's build spec, scope expanded from
the original read-only "O365 Dashboard" to include AD writes). **This is
not read-only — every write path is treated as high-risk.**

## Locked-in decisions (agreed with Alex, 2026-08-18)
- **Stack:** FastAPI + Jinja2 + Bootstrap 5 dark theme, async SQLAlchemy 2,
  **SQLite** (not Postgres — deliberately simpler than itops2's stack,
  per spec) for app state, in a **physically separate SQLite file** for
  the append-only audit trail (see app/core/audit.py) — not just a
  separate table, so a bug in the app-state session can never touch an
  audit row. No HTMX in v1 — plain server-rendered forms throughout;
  sensitive-action confirmations (unlock/reset/disable/LAPS) are full-page
  modals-on-submit, deliberately not partial-swap trickery.
- **Deployment:** saa-docker (10.10.160.59), external port **8010**
  (placeholder — confirm free before first deploy; only Semaphore/3001 is
  confirmed in use on this host so far). Repo folder `adminconsole/` in
  Rvssian-SEZ/Docker; **standalone app, deliberately NOT folded into
  itops2** even though itops2's own conventions (settings-at-rest,
  audit log, break-glass, permission registry) were used as the direct
  template for this app's equivalents — Alex was explicit about this
  staying its own deployable unit. CI publishes
  `ghcr.io/rvssian-sez/adminconsole:latest` + `:{version}`.
- **AD integration: LDAPS (ldap3)**, not WinRM — chosen over the
  WinRM/pypsrp alternative because SAA-CA/PKI already exists for it and it
  avoids an extra PowerShell hop + credential to manage. See
  app/core/ldap_client.py.
- **RBAC:** three FIXED roles (Helpdesk L1, Helpdesk L2, Admin) +
  Break-glass, which is deliberately **not a role** — it's a separate
  local credential store (app/core/models.BreakGlassCredential), never a
  `users` row, mandatory TOTP, never deactivatable. Permission matrix
  registry in app/core/permissions.py, defaults per the spec's suggested
  tiers. Authentik OIDC group claims map to roles
  (auth.oidc.group_role_map JSON setting); highest-privilege mapped group
  wins if several match.
- **OU scoping:** enforced in app/routers/ad_accounts.py
  (`_check_scope`), not the permission registry — a permission is
  action-level only ("can unlock"); ad.scoped_ous / ad.excluded_ous are
  DN-suffix checks applied on top, for Helpdesk L1/L2 only (Admin and
  break-glass are never scoped).
- **Settings-at-rest encryption:** Fernet (cryptography lib), key from
  the `FERNET_KEY` env var — the one secret allowed to live in the
  environment; everything it protects (Graph client secret, Authentik
  client secret, AD bind password) lives only in the encrypted
  `app_settings.value` column. Missing/invalid key = that section reads
  as "not configured", never a crash (see app/core/crypto.py). Secret
  fields are write-only in the UI (is_set() badge, never the value); a
  blank field on save means "keep existing", never "clear".
- **Settings page re-auth:** `require_reauth` (app/core/auth.py) — a
  5-minute freshness window, separate from the 15-minute idle-session
  timeout. Local/break-glass users re-enter password(+TOTP); OIDC users
  are bounced back through `/auth/oidc/login?reauth_next=...`, which
  marks reauth fresh on a successful callback instead of the normal
  post-login redirect to "/". Live-verified end-to-end (see Build order).
- **Audit trail immutability:** enforced at the SQLite engine level with
  `BEFORE UPDATE`/`BEFORE DELETE` triggers that `RAISE(ABORT, ...)` on the
  audit_log table (app/core/audit.py `ensure_schema`) — this is the
  practical ceiling of "insert-only" achievable in SQLite (no per-connection
  grants like Postgres). **Live-verified**: a direct `sqlite3` UPDATE and
  DELETE against a running instance's audit.db both raised
  `IntegrityError`. Kept OUT of Alembic deliberately (see below) — the
  audit schema is simple and fixed, and keeping it out of the app-DB
  migration story reinforces that it's a genuinely separate subsystem.
- **Rate limiting:** in-memory sliding window (app/core/ratelimit.py) on
  password reset (5/10min per user) and LAPS reveal (10/10min per user).
  Deliberately in-memory, not Redis — single container, no horizontal
  scaling planned; resets on restart, which is fine for an
  abuse-slowdown control (the audit log + alerting are the hard controls).
- **Break-glass alerting:** app/core/alerting.py — best-effort
  email (Postfix relay) and/or webhook, fires on every break-glass login
  AND every break-glass write/LAPS-reveal action (not just login). Never
  blocks or fails the action it's alerting about; falls back to a log
  warning if no channel is configured. The audit row is always written
  regardless of whether the alert send succeeds.
- **Attribute edit allowlist:** app/core/ldap_client.py
  `EDITABLE_ATTRIBUTES` — name/title/department/phone/manager only.
  Group membership and AdminSDHolder-protected accounts are out of scope
  for v1 by design (spec) — no route exists for either.

## Authentik integration — provisioned 2026-08-18
Created directly on the real `auth.saa.sc` instance (matching the existing
`itops` provider's conventions exactly — same signing key, same
implicit-consent authorization flow, same standard invalidation flow):
- OAuth2 Provider "SAA Admin Console" (pk 4), redirect URI
  `https://adminconsole.saa.sc/auth/oidc/callback`, scope mappings
  openid/profile/email (Authentik's default `profile` mapping already
  returns a `groups` claim — no custom mapping needed, confirmed by
  reading its expression before relying on it).
- Application slug `adminconsole` → issuer discovery confirmed live at
  `https://auth.saa.sc/application/o/adminconsole/.well-known/openid-configuration`
  (200 OK) — matches `auth.oidc.issuer`'s default in settings_store.py.
- Three empty groups created for the role mapping:
  `adminconsole-admins` / `adminconsole-helpdesk-l2` / `adminconsole-helpdesk-l1`
  (`auth.oidc.group_role_map` default updated to map all three). **Nobody
  is a member of any of them yet** — assigning real users to these groups
  is an identity decision left to Alex, not automated here.
- Client ID/secret were generated by Authentik and handed to Alex directly
  in chat (never committed) — go into Settings → Authentik after first
  deploy, along with issuer `https://auth.saa.sc/application/o/adminconsole/`.
- Provisioned via a short-lived Authentik API token (created and revoked
  in the same session via `docker exec authentik-server ak shell` on
  saa-docker, since scripting the SPA's flow-executor login over raw HTTP
  proved unreliable and wasn't worth pursuing against a production IdP) —
  not a standing credential.
- **The redirect URI depends on `adminconsole.saa.sc` existing** — DNS +
  an nginx-proxy-manager host pointing at whatever port the container
  ends up on. Not yet created; do this alongside the actual deploy.

## AD service account — provisioned 2026-08-18
Created via a new one-off Semaphore playbook
(`Rvssian-SEZ/Semaphore` → `SAA/playbooks/admin_provision_adminconsole_service_account.yml`,
run through a temporary Semaphore template, now deleted — task history
stays in Semaphore #52-55 for audit trail), reusing the project's existing
Kerberos/WinRM access to the DCs rather than direct DC access from here.
- **Account**: `svc-adminconsole`, real DN
  `CN=svc-adminconsole,OU=Service Accounts,OU=SCAA Users,DC=saa,DC=sc`
  (discovered live via `Get-ADOrganizationalUnit -Filter` — the OU is
  nested under `OU=SCAA Users`, not directly under the domain root as
  first assumed; the playbook now discovers it by filter rather than
  hardcoding the DN, so this self-corrects on any future rerun).
  `password_never_expires` + `user_cannot_change_password` set, no group
  membership — least privilege is via `dsacls` only, per the spec.
- **Scope: domain-wide by explicit choice** (Alex: "will actually need
  domainwide access" — helpdesk needs to reach accounts across the whole
  org, not one OU). Granted at `DC=saa,DC=sc` with `/I:S` (inherit to
  subobjects). AdminSDHolder/SDProp strips inherited ACEs from protected
  principals (Domain Admins/Enterprise Admins/krbtgt and members), so this
  grant does not reach those regardless of inheritance — noted to Alex
  before running, not assumed silently.
- **Grants confirmed live** (11 of 12 succeeded — see gap below):
  reset password, write `lockoutTime`, write `userAccountControl`, write
  givenName/sn/displayName/title/department/telephoneNumber/mobile/manager
  — all exactly match `app/core/ldap_client.py`'s `EDITABLE_ATTRIBUTES` and
  the app's unlock/reset/enable-disable code paths.
- **Password handed to Alex out of band** (same pattern as the break-glass
  and Authentik client-secret handoffs) — not committed anywhere. Goes
  into Settings → AD as `ad.bind_password`, alongside `ad.bind_dn` (above)
  and `ad.base_dn = DC=saa,DC=sc`.

### Known gap: legacy LAPS is not usable yet — schema not extended
The `RP;ms-Mcs-AdmPwd;computer` grant failed with `dsacls`'s own error
**"No GUID Found for ms-Mcs-AdmPwd"** — not a permissions problem, the
attribute doesn't exist in this forest's schema at all. Legacy Microsoft
LAPS has never been schema-extended here (`Update-AdmPwdADSchema` or the
LAPS.msi schema step was never run). This is a real, one-time, forest-wide
schema change requiring Schema Admins rights — **not attempted**, since
it's a different order of magnitude of change (forest schema, not a scoped
delegation) from everything else done in this session, and genuinely
irreversible in practice. Before LAPS retrieval can work at all:
- Confirm which LAPS is actually in play here — this could instead be
  **Windows LAPS** (built into Server 2019+/2022+, a different attribute
  `msLAPS-Password` + `msLAPS-EncryptedPassword`, not `ms-Mcs-AdmPwd`) —
  worth checking before assuming legacy LAPS is even the right target,
  since `app/core/ldap_client.py`'s `read_laps_password()` currently only
  reads `ms-Mcs-AdmPwd`.
  If it's Windows LAPS, `ldap_client.py` needs a different attribute name
  and a different `dsacls` grant syntax entirely (Windows LAPS uses its
  own `Set-LapsADReadPasswordPermission` cmdlet, not raw `dsacls`).
- If legacy LAPS is the intended path, extending the schema is a decision
  for Alex to make deliberately (with its own change window), not
  something to fold into this account's provisioning.
Every other AD write path (unlock/reset/enable-disable/attribute-edit)
is unaffected — only LAPS retrieval is blocked pending this decision.

## v1 lessons already encoded here (carried over from itops2 + found live)
- HTML checkboxes are absent from form data when unchecked — the Settings
  save route explicitly writes "false" for a missing bool-typed key
  instead of silently leaving the old value in place (found and fixed
  during this build's own live verification, same class of bug itops2's
  CLAUDE.md documents for its own Settings toggles).
- `alembic/env.py` rewrites `sqlite+aiosqlite://` to `sqlite://` for the
  sync migration run — aiosqlite is async-only, alembic needs a sync
  driver, and SQLite's stdlib sqlite3 driver handles DDL-only migration
  runs fine even though the app itself connects async.
- Absolute `sqlite:////c/...` URLs under Git Bash / MSYS don't resolve
  the way you'd expect for one-off scripts — use a relative path
  (`sqlite:///./data/...`) for anything run outside the container, where
  `/data` is guaranteed to exist as the Docker volume mount.

## Build order & status
1. ✅ Scaffold + auth + settings + audit, **built and live-verified in
   this session** (uvicorn boot against real SQLite files, not just
   import-checked): compose, Dockerfile, CI workflow, Alembic (app DB
   only), async DB (app DB) + separate audit DB with triggers, base
   models (roles/permission matrix/users/settings/break-glass credential),
   permission registry, bootstrap seeding (roles, default matrix,
   break-glass credential — degrades cleanly with a CRITICAL log line if
   FERNET_KEY is unset), local + break-glass + OIDC auth, Settings UI
   (Graph/Authentik/AD/break-glass-alerting/SMTP sections) with
   re-auth gate and encrypted write-only secret fields, Audit Log viewer
   with actor/action/target/date-range filters, base layout + sidebar
   (permission-gated nav), healthz.
   **Verified live in this session**: full boot (bootstrap logs +
   break-glass TOTP secret printed once), break-glass login with a real
   TOTP code, idle/reauth session flags, `/settings` correctly redirecting
   to `/settings/reauth` then back after confirmation, an AD Settings
   save round-tripping through Fernet encryption (confirmed the DB column
   is ciphertext AND decrypts back to the original value), the write-only
   "set" badge never showing plaintext, a `settings_change` audit row
   appearing in the filtered Audit Log view, and the audit_log
   UPDATE/DELETE triggers actually raising `IntegrityError` against a
   live SQLite file.
2. 🔶 AD account management — **routes and LDAPS client are built
   (app/core/ldap_client.py, app/routers/ad_accounts.py: search, unlock,
   reset password, enable/disable, attribute edits, LAPS reveal, OU
   scoping, reason-required + rate-limited + audited + break-glass-alerted
   on every write), but NOT yet live-tested against SAA.SC AD** — no
   dsacls delegation exists yet for a real service account (spec's own
   "AD Delegation Prerequisites" is an explicit manual pre-flight step,
   not assumed). Honestly flagged rather than claimed working, same
   convention itops2 used for its own LDAP/OAuth2 features before they
   were verified against a real endpoint. **Before first real use**:
   grant the dsacls delegation to a pilot OU (per spec's Open Decisions),
   fill in the Settings → AD section, then verify search/unlock/reset/
   enable-disable/LAPS one at a time against a test account.
3. ⬜ NOT STARTED: Graph reporting (license overview, security posture,
   mailbox health, activity trends, service health ticker, stale
   accounts), `sync.py` standalone cron script, CSV/PDF export, TOTP
   enrollment UI (break-glass TOTP secret is currently bootstrap-log-only
   — no in-app re-enrollment flow yet if it's lost), Helpdesk L1/L2 user
   management UI (creating local/reviewing OIDC-provisioned accounts —
   v1 ships with zero seeded normal users by design; the first real admin
   signs in via Authentik with a mapped group).

## Deploy procedure (once ready for saa-docker)
```
scp -r ./app ./alembic ./requirements.txt ./Dockerfile ./docker-compose.yml root@10.10.160.59:/opt/docker-repo/adminconsole/
ssh root@10.10.160.59 "cd /opt/docker-repo/adminconsole && docker compose up -d --build"
```
- **Never** scp or otherwise overwrite the server's `.env` — it holds
  `FERNET_KEY`, which is unrecoverable if lost (every encrypted setting
  becomes unreadable and must be re-entered).
- **Alex's standing instruction**: if saa-docker starts running low on
  disk, clean out old/dangling Docker images before anything else
  (`docker image prune -a` after confirming what's actually unused, or a
  targeted `docker rmi` on superseded adminconsole tags) — check this
  before troubleshooting anything that looks like a disk-pressure symptom
  on that host.
- Confirm port 8010 is actually free on saa-docker before the first
  `docker compose up` (only Semaphore/3001 is confirmed in use there so
  far — this repo has no prior app on that host to check against).
- Check `docker logs adminconsole` after deploying.

## Repo/infra reminders
- Git via SSH only: git@github.com:Rvssian-SEZ/Docker.git
- Workflow file lives at repo root `.github/workflows/adminconsole-ci.yml`.
- SSH to hosts as root@ (per this repo's other apps' convention) — not yet
  confirmed working specifically for saa-docker in this session (an
  earlier, unrelated Semaphore-troubleshooting session found direct SSH
  to 10.10.160.59 rejected for several common usernames; all Semaphore
  work that session went through its REST API instead). Confirm SSH
  access to saa-docker separately before relying on the scp-based deploy
  procedure above.
