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

## Protected Users unlock — AdminSDHolder inheritance gap (2026-08-19)
Alex reported being unable to act on Protected Users group members at
all. Confirmed live (not assumed): 6 of the group's 9 current members
(including Mitch Spence) have `adminCount=1`, which — via AdminSDHolder/
SDProp — disables ACL inheritance on that specific object. The domain-root
`dsacls ... /I:S` grant from account provisioning (above) relies entirely
on inheritance, so it silently never reached these 6 accounts even though
the grant itself is correctly in place for everyone else.
Two fixes were possible, with very different blast radius — surfaced to
Alex explicitly rather than picked silently:
- Modify the AdminSDHolder template itself: dynamic (SDProp
  auto-propagates to any future adminCount=1 object, hourly-ish), but
  reaches *every* protected principal domain-wide — real Domain Admins,
  Enterprise Admins, Schema Admins, krbtgt, etc. — not just Protected
  Users, a materially bigger domain-wide security-control change.
- **Chosen**: a direct (non-inherited), unlock-only ACE
  (`WP;lockoutTime` — no reset/enable-disable/attribute-edit/LAPS) on
  today's 6 adminCount=1 members specifically, discovered live each run
  rather than hardcoded
  (`SAA/playbooks/admin_grant_unlock_protected_users.yml` in the
  Semaphore repo, run via a temporary template, now deleted — task
  history in Semaphore #80-81). Narrow and fully reversible, at the cost
  of not being dynamic: a **new** Protected Users member with
  `adminCount=1` won't automatically get this and needs a playbook rerun.
- **Bug found via live testing**: `dsacls` rejected the grant with "user
  is specified as Inherited Object Type. /I:S must be present" when the
  ACE included the `;user` object-type qualifier — that qualifier implies
  an inheritable/propagating ACE, which doesn't apply to a direct grant on
  a single leaf object. Fixed by dropping `;user` entirely for this
  leaf-object case (kept for the domain-root inherited grant, where it's
  correct).
- **Live-verified end-to-end**: unlocking `ms` (Mitch Spence) through the
  actual running app succeeded after the grant.

## Windows LAPS retrieval — hybrid LDAPS + Semaphore (2026-08-18)
Confirmed live (`SAA/playbooks/admin_check_laps_variant.yml` in the
Semaphore repo, read-only): this forest runs **Windows LAPS with password
encryption on** — `msLAPS-EncryptedPassword` is populated,
`msLAPS-Password` (plaintext) is empty. Decrypting the encrypted value
needs a real Windows-side call to the domain's Group Key Distribution
Service (`Get-LapsADPassword -AsPlainText`) — not reachable from a plain
LDAPS client, so `app/core/ldap_client.py` no longer has a LAPS function
at all (removed the legacy-`ms-Mcs-AdmPwd` one, which targeted an
attribute that doesn't even exist in this forest's schema).
- **Design**: the `/ad/{sam}/laps` route still uses LDAPS to confirm the
  computer exists and apply OU scoping (same as every other action), then
  triggers `SAA/playbooks/admin_read_laps_password.yml` via Semaphore's
  REST API (`app/core/semaphore_client.py`) — reusing Semaphore's already-
  proven Kerberos/WinRM trust to the DCs instead of adding that whole
  stack (krb5 client, pykerberos, /etc/krb5.conf) into this container too,
  which would also mean holding a second broad domain credential here,
  working against the whole point of provisioning a scoped
  `svc-adminconsole` account in the first place.
- **The password never touches Semaphore's persistent storage.** Confirmed
  live that Semaphore has no task-output deletion API
  (`DELETE /api/project/{id}/tasks/{id}` → 400) — anything printed to
  stdout there sits in Semaphore's history indefinitely, which would
  violate the spec's "never cached beyond the single view" for LAPS.
  Instead the Ansible task POSTs the password directly to a per-request,
  single-use, ~30s-TTL callback URL
  (`/internal/laps-callback/{token}`, `app/core/laps_pending.py` +
  `app/routers/internal.py`) that the app is already awaiting — Semaphore
  only ever sees non-secret status (`delivered`/`callback_failed`/
  `laps_read_failed`) in its own task log.
- **Semaphore access**: a dedicated `adminconsole-svc` Semaphore user was
  created with **task_runner** role scoped to project 2 only (confirmed:
  not owner/admin) — the app never uses the shared `admin@saa.sc` Semaphore
  login. Configured in Settings → Automation
  (`semaphore.url`/`username`/`password`/`project_id`/`laps_template_id`).
- **STATUS: ✅ live-verified end-to-end** (2026-08-18, against SAA-asedgwick
  via the running app as break-glass): LDAPS lookup → OU scope check →
  Semaphore trigger → `Get-LapsADPassword` on SCAA-PRD-DC1 → callback
  delivery → rendered in the UI with 30s auto-hide. Confirmed both ends
  stayed secret-free: the app's audit log shows `laps_reveal ... delivered`
  with no password, and the Semaphore task's own output shows only
  `STATUS=delivered` — never the value. Four real bugs found and fixed to
  get here (see "Bugs found via live testing" below); worth knowing this
  took several iterations, not a first-try success.

## Bugs found via live testing (2026-08-18) — first real end-to-end run
Every one of these was invisible from code review alone; each surfaced
only once actually exercised against the real stack. Kept here as a
concrete reminder that "builds and imports cleanly" is not "works":

1. **LDAPS CERTIFICATE_VERIFY_FAILED**: `ldap_client.bind()`'s `Tls()` had
   no `ca_certs_file` — the DC's cert is issued by the internal SAA-CA,
   which isn't in the container's default trust store. Fixed by wiring the
   already-existing (but previously unused) `CA_CERT_PATH` setting into
   `Tls(ca_certs_file=...)`; cert deployed to
   `/opt/appdata/adminconsole/certs/saa-ca-root.pem`, pulled from
   Authentik's own crypto store (`SAA-CA Root`, already registered there).
2. **Same root cause, different path — OIDC discovery failed too**: the
   `*.saa.sc` wildcard cert NPM uses for `auth.saa.sc` is *also* SAA-CA-
   issued (confirmed: `openssl s_client` shows `issuer=...CN=SAA-CA`).
   Every earlier successful `curl` test to `auth.saa.sc` in this session
   ran from Alex's own domain-joined machine, which already trusts SAA-CA
   via GPO — not proof the cert is publicly trusted. `oidc.py`'s `_client()`
   already read `ca_cert_path`, so fix #1 fixed this too, for free.
3. **Authentik provider had `grant_types: []`** — the API creation call
   never specified this field, and unlike the UI it didn't default to a
   sane set, so Authentik rejected every authorize request with "Invalid
   grant_type for provider" / `invalid_request`. Found by diffing the new
   provider's full config against itops's working one field-by-field.
   Fixed: `PATCH` to `["authorization_code", "implicit", "hybrid", "refresh_token"]`.
4. **LAPS lookup used the bare hostname** — AD computer accounts'
   `sAMAccountName` always ends in `$` (unlike user accounts); the LDAPS
   `find_user()` call for the computer needed `f"{sam}$"`. Semaphore's own
   `Get-LapsADPassword -Identity` call was unaffected (accepts the bare name).
5. **The LAPS playbook was never actually committed** — written to disk
   and referenced by a Semaphore template, but a `git add`/commit was
   missed for `SAA/playbooks/admin_read_laps_password.yml` specifically.
   Semaphore's task run failed with "the playbook ... could not be found"
   against the real repo — caught immediately by testing, not by review.
6. **Login page showed no SSO button / local-login 401 loop**: turned out
   nothing had ever been saved via Settings at all (confirmed: `select
   count(*) from app_settings` = 0) despite an earlier OIDC callback hit
   in the logs — that hit was the immediate "SSO is disabled" bounce, not
   a real attempt. Fixed by driving the break-glass login + Settings save
   flow directly (via curl, using the real generated credentials) instead
   of relying on manual copy-paste into the UI.

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
3. ✅ Graph reporting — **live-verified 2026-08-18** against the real
   SAA tenant (app/core/graph_client.py, app/core/reports.py,
   app/routers/reports.py). Confirmed live: token acquisition, the actual
   granted app roles (queried directly from the SP's own
   appRoleAssignments, not assumed) — `Directory.Read.All`,
   `User.Read.All`, `IdentityRiskyUser.Read.All`, `ServiceHealth.Read.All`,
   `Reports.Read.All`, plus `AuditLog.Read.All` and
   `UserAuthenticationMethod.Read.All` added mid-session (their calls
   still 403'd immediately after — normal Azure AD token-claim propagation
   delay, not a bug; graph_client's GraphPermissionError makes those
   sections self-resolve once it catches up, no rebuild needed). Two real
   bugs found live: Reports API endpoints 302-redirect to a signed blob
   URL (httpx doesn't follow redirects by default — needed
   `follow_redirects=True`), and those same endpoints return CSV unless
   `$format=application/json` is appended.
   **Deliberate v1 simplification**: no `sync.py` / cron / DB cache as the
   original spec describes — live Graph queries with a 5-minute in-process
   TTL cache instead (see reports.py's docstring). Revisit if load times,
   rate limits, or a need for historical trend data (not just point-in-
   time) make that insufficient.
   **Not built**: legacy-auth detection (dropped rather than guess at
   `auditLogs/signIns` filter syntax/field names I wasn't confident of —
   same "don't fake confidence" convention as everywhere else in this
   project), PDF export (CSV only), TOTP re-enrollment UI (break-glass
   TOTP secret is bootstrap-log-only), Helpdesk L1/L2 user management UI
   (v1 ships with zero seeded normal users by design — the first admin
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
