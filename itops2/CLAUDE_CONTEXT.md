# ITOps v2 — Claude Context

## What this is
Ground-up rewrite of the ITOps portal ("v1", port 8000 on docker-test), inspired by
Snipe-IT's data model and responsiveness, with all v1 features migrating in over time.
Deployed to home lab and external client sites.

## Locked-in decisions (agreed with Alex, July 2026)
- **Stack:** FastAPI + Jinja2/HTMX + Bootstrap 5 dark theme, async SQLAlchemy 2,
  PostgreSQL 16 in a **new dedicated container** (not v1's shared `itops` DB).
- **Deployment:** docker-test (192.168.110.50), external port **8004**.
  Repo folder `itops2/` in Rvssian-SEZ/Docker; CI publishes
  `ghcr.io/rvssian-sez/itops2:latest` + `:{version}`.
- **Shared-DB discipline:** table prefix `core_`, Alembic version table
  `alembic_version_core`, `include_object` filter in alembic/env.py.
  Helpdesk v2 / CRM v2 / EmailClient v2 will later join this same Postgres
  with their own prefixes + version tables. Docker network `itops2_net`.
- **Auth:** three sources — Authentik OIDC, generic LDAP/LDAPS
  (bind + create-on-first-login, group→role mapping), local accounts.
  **Break-glass local admin always active** (ensured on every startup,
  cannot be deactivated). Runtime auth config in Settings UI, not env.
- **Permissions:** FIXED roles only — Admin, Manager, Technician, Viewer —
  with a configurable permission matrix (core_role_permissions), edited in a
  Settings grid. NO custom role creation. Registry in app/core/permissions.py.
- **Multi-company:** optional. `company_id` columns from day one; a settings
  toggle enables it, plus a second toggle: users scoped to their company vs
  company as label-only.
- **Assets (Snipe-IT-style):** Manufacturers → Categories → Models → Assets;
  status labels; checkout to **user, location, or asset**; auto asset tags with
  configurable prefix/format, manually editable; full audit log
  (core_audit_log, written on EVERY mutation — infrastructure, not feature).
  Hard delete only when an asset has zero checkout history, zero
  attachments, AND zero maintenance records (FK-guard style, Phase 6
  added the third); otherwise archive (status → an archived-type
  label) is the only "delete".
- **Two polymorphism styles, deliberately, not an inconsistency:**
  checkout targets (`checked_out_to_user_id` / `_location_id` / `_asset_id`
  on core_assets and core_checkouts) use **real FK columns**, one per
  possible target type, because the target set is small and fixed (3
  types, unlikely to grow) and we want the DB itself to block deleting a
  user/location/asset that's currently a checkout target — same
  FK-guard-with-friendly-toast pattern as Catalog. Attachments
  (core_attachments) use the **entity_type + entity_id string pattern**
  instead (matching core_audit_log), because attachments are meant to
  generalize to entities that don't exist yet (Contracts, Maintenance in
  later phases) — a fixed FK per entity type doesn't scale to "any
  future entity," and losing DB-level referential integrity there is an
  acceptable tradeoff since assets can never be hard-deleted while they
  still have attachments (checked by an explicit COUNT, not a FK) in the
  first place.
- **Printer fields live in a THIRD style — a 1:1 extension table**
  (`core_printer_details`, `asset_id` is both PK and FK), decided with
  Alex before building Phase 6 specifically because it sets the pattern
  for every future asset-type extension. Rejected: nullable columns on
  `core_assets` (the central, most-referenced table would grow wider
  with every future asset type's fields, mostly NULL for the other
  99% of assets); a generic key-value `asset_extras` table (loses
  DB-level typing/indexing for a flexibility need that doesn't exist —
  asset types needing extra fields are a small, dev-curated set, like
  `StatusType`/`AuthSource` already are Python enums, not
  runtime-configurable). "Is this asset a printer" is still driven by
  its model's category name (`== "Printer"`, case-insensitive) per the
  original decision below — the extension table only holds the
  IP/hostname/consumable-notes *values*, created lazily on first save.
- **Printers:** assets in a Printer category (matched by category name,
  not a flag — see above) + a dedicated page that's a specialized VIEW,
  not a separate entity: lists IP, status, and maintenance cost totals
  (converted to default currency via the exchange-rate table, at each
  maintenance record's own date — same historical-value rule as
  purchase costs). Maintenance records themselves are generic (any
  asset, not printer-specific).
- **Depreciation & warranty/EOL:** implemented, policy-configurable in settings.
- **Multi-currency:** amount + currency code on all money fields; manual
  exchange-rate table with DATED rates (historical value at purchase date);
  default currency SCR, changeable in settings. UK date formats, English only.
- **Licenses & Contracts:** one unified simple module (renewals + reminders),
  NOT Snipe-IT seat-tracking. Optional M2M coverage of assets
  (core_contract_assets) — the only CASCADE-delete relationship in this
  schema (see the polymorphism note above); everything else blocks
  deletion instead. List sorts by next renewal (end_date, required —
  a contract you can't track toward renewal isn't useful here), with
  expired/expiring-soon states driven by contracts.renewal_alert_days
  (its own setting, not reused from warranty.alert_days — same pattern,
  own key, so tweaking one never silently affects the other).
- **Inventory:** quantity-tracked items sharing the Catalog category
  tree (no separate lookup). Quantity changes ONLY through a +/- adjust
  action (delta + required reason) — never a direct field edit — so
  every stock change has an auditable reason; adjustments write
  straight to core_audit_log, no separate ledger table needed (unlike
  Checkout/Maintenance, there's no richer per-event data to justify one).
- **Attachments:** volume at /data/attachments (host /opt/appdata/itops2/attachments),
  organized by entity (assets/<id>/ etc.), metadata in an attachments table.
- **Notifications:** SMTP only — unauthenticated relay (Postfix .35:25) or
  authenticated (O365/Gmail), configured in Settings. Per-user event
  subscription list. (v1 lesson: aiosmtplib needs explicit
  username=None/password=None on unauthenticated port 25.)
- **Reporting:** CSV export on tables. Nothing fancier.
- **v1 import:** one-time admin wizard, module-pickable, takes a v1 DB
  connection string, parses v1's free-text currency fields ("1000 SCR", "£200")
  into amount+currency, flags unparseables for manual review, preserves asset
  tags. Built LAST (needs stable target schema).
- **Versioning:** single source app/version.py; shown in sidebar footer +
  Settings→About (app + schema version); CI reads it for image tags.

## Performance is a requirement
v1 felt sluggish on save. v2 hard requirements: HTMX targeted partial swaps on
save (no full-page rerenders), all email/external calls in BackgroundTasks with
PRIMITIVE args only (never ORM objects — session is closed), indexes on FKs and
search columns, async engine with pooling (already configured in app/core/db.py).

## v1 lessons already encoded here
- Starlette 0.41+: TemplateResponse(request, name) — request first positional.
- RequiresLoginException + exception handler for auth redirects (in app/main.py).
- No inline comments on .env value lines.
- Review autogenerated migrations; strip drops of non-core_ tables.
- docker compose down && build && up -d when deps/mounts change.
- httpx to Authentik needs verify=<Step-CA root path> (CA_CERT_PATH).
- Alembic: an inline `sa.Enum(...)` column type in `op.create_table` auto-creates
  the Postgres enum type. Don't also call `.create(checkfirst=True)` on it first —
  the table-create's implicit create then collides (DuplicateObject) and the
  whole migration rolls back. Only reference the enum inline (as 0001 does for
  role_name/auth_source); `.drop(checkfirst=True)` explicitly in downgrade() only.
- FastAPI: a bare `field: str = Form(...)` genuinely-required-at-request-layer
  field, when actually missing/malformed, 422s with a raw JSON body — htmx
  doesn't render that into the toast area, so the user sees nothing at all,
  not even an error. Found in Contracts (Phase 7) and fixed there by using
  `Form("")` with the existing app-level "is it empty?" check instead (which
  already produced a friendly toast). Assets and Maintenance (Phases 5–6)
  use bare `Form(...)` for some required fields too and may have the same
  latent gap — not audited/fixed yet, since real `<input>`/`<select>` form
  submissions always include the field (even empty), so it's only reachable
  via a malformed/non-browser request. Worth a sweep before v1 import or a
  public API surface makes malformed requests more likely.

## Build order & status
1. ✅ Scaffold: compose (app + postgres:16-alpine), Dockerfile, CI workflow,
   versioning, config, async DB, base models (users/roles/matrix/settings/audit),
   permission registry, bootstrap seeding, base layout + sidebar, healthz.
2. ✅ App shell: local auth (login/logout, session, bcrypt direct — passlib
   DROPPED, incompatible with bcrypt>=4), CurrentUser + require(permission)
   dependencies, permission-gated sidebar, settings framework
   (core_settings + typed store in settings_store.py — register every key
   in DEFAULTS there + LABELS in routers/settings.py), General + About tabs,
   HTMX toast-save pattern (hx-post -> #toast-area swap; checkboxes absent
   when unchecked -> compare form.get(key) == "true").
   E2E tested on sqlite+aiosqlite (login, 403s, matrix gating, persistence,
   audit rows).
3. 🔶 PARTIAL — done: Permissions grid (Settings tab; per-checkbox HTMX
   toggle saves, lockout guard: settings.manage locked for Admin), Users
   page (create local users, inline role/company/active edit via
   hx-trigger=change, admin password reset modal; deactivate-only — never
   hard delete, audit rows reference users; break-glass: role locked,
   cannot deactivate, password CAN change), /profile self password change
   (min 10 chars). Permission checks hit DB per request — matrix edits
   apply instantly. E2E: 24 checks green.
   OIDC (Authentik): ✅ DONE and **tested + live in production** —
   app/core/oidc.py (discovery, code exchange, userinfo, group→role
   mapping, user provisioning), Settings→Authentication tab
   (app/routers/settings.py AUTH_KEYS), login page SSO button.
   LDAP: ⬜ NOT STARTED beyond placeholders — `auth.ldap.*` keys exist in
   settings_store.py DEFAULTS and `AuthSource.ldap` exists in
   app/core/models.py, but there is no bind/search logic, no
   create-on-first-login, no group→role mapping, no login route, and no
   Settings UI fields (AUTH_KEYS in settings.py only lists auth.oidc.*).
   REMAINING: generic LDAP/LDAPS (bind + create-on-first-login,
   group→role map from auth.ldap.group_role_map JSON setting), add its
   fields to the Settings→Authentication tab.
4. ✅ Core lookups + currency, **deployed and verified in production**.
   Part A (lookups): app/routers/catalog.py, sidebar "Catalog" link,
   /catalog/{manufacturers,categories,models,status-labels,locations,companies}.
   Companies/locations/manufacturers/categories share one generic CRUD
   implementation (`_register_simple_entity` in catalog.py — id+name only,
   unique name, hard delete blocked by FK with a friendly toast on
   IntegrityError). Models (core_models) belong to a manufacturer + category
   (composite unique on name+manufacturer_id, not globally unique) and carry
   optional `depreciation_months` / `eol_months` overrides of the
   depreciation.default_months / warranty.alert_days settings — blank means
   "inherit the default". Status labels (core_status_labels) carry a
   `status_type` enum (deployable/deployed/pending/archived,
   app.core.models.StatusType) separate from the free-text label name —
   asset workflow rules (Phase 5) key off status_type, not the label.
   Permission gating: catalog.view (read) / catalog.manage (write) for
   locations/manufacturers/categories/models/status-labels; companies.manage
   alone gates Companies (view AND manage — no separate companies.view,
   matches the existing permissions.py registry, admin-only by default).
   Migration 0002 (alembic/versions/0002_phase4a_lookups.py).
   Part B (currency): core_currencies (code as PK, symbol, active) seeded
   idempotently in app/core/bootstrap.py with SCR/USD/GBP/EUR (never
   overwrites an admin's edits on restart); core_exchange_rates (from/to
   FK to currencies.code, Numeric(18,6) rate, effective_date, unique per
   from+to+date) — manual entry only, no rate API. Lives under
   Settings → Currency (app/routers/settings.py, settings/currency.html),
   gated by settings.manage like the rest of Settings. Deleting the
   currency currently set as general.default_currency is blocked with a
   toast (change the default first). Migration 0003
   (alembic/versions/0003_phase4b_currency.py).
   0002 initially hit the inline-Enum migration gotcha noted above — caught
   before the deploy stuck (transaction rolled back cleanly, no manual DB
   cleanup needed).
5. ✅ Assets + checkout/checkin + audit wiring + attachments,
   **deployed and verified in production**. app/routers/assets.py
   (list, detail/edit page — too many fields for Catalog's inline-row
   pattern), sidebar "Assets" link (pre-existed from Phase 1 scaffold,
   was 404ing until now). Migrations 0004 (core_assets, core_checkouts,
   core_attachments).
   Fields: tag/serial/model/status/company/location, purchase
   date+cost+currency, warranty_months, depreciation/EOL month
   overrides (asset override → model override → global default
   cascade; EOL has no global default, computed at render time, never
   stored). Asset tag auto-suggested (scan existing tags matching
   asset_tag.prefix, +1, zero-padded to asset_tag.pad) if left blank,
   always manually editable; a same-tick collision is caught by
   `UNIQUE(asset_tag)` → friendly toast, not a 500.
   Status lifecycle: `status_type == deployed` reachable ONLY via
   checkout (general create/edit form's dropdown excludes it, rejected
   server-side if forced); editing status while `checked_out_at IS NOT
   NULL` is rejected — must checkin first (this invariant spans two
   tables so it's enforced in the routers, not a DB constraint).
   Archived assets are read-only except a restore action (pick a
   non-archived destination status; nothing else editable in that
   request). Audit action is archive/restore when a transition crosses
   that boundary, update otherwise.
   Checkout: requires exactly one of the three targets + a destination
   status restricted to `status_type == deployed`; opens a
   core_checkouts row (includes `expected_checkin_at` due-date field).
   Checkin: any non-deployed destination status; closes the open
   core_checkouts row, clears the asset's `checked_out_to_*` pointer.
   `core_checkouts` has a **partial unique index**
   (`ON (asset_id) WHERE checked_in_at IS NULL`) — DB-level guarantee
   of at most one open checkout per asset, not just an app-level check.
   Attachments: multipart upload streamed to disk in 1MB chunks, capped
   at 25MB; stored under a UUID-based filename (never trust the
   uploaded name for the on-disk path); disk layout
   `{attachments_dir}/{entity_type}/{entity_id}/{stored_filename}` —
   entity_type used raw ("asset"), no pluralization. No dedicated
   attachments.* permission — upload/delete reuse assets.edit, download
   reuses assets.view.
6. ✅ Maintenance records + Printers page, **deployed and verified in
   production**. Migration 0005 (core_maintenance, core_printer_details
   — see the extension-table decision above).
   Maintenance (app/routers/maintenance.py): generic against any asset,
   shown as a section on the asset detail page (not a separate page) —
   date/type(repair|maintenance|upgrade)/description/cost+currency/
   performed_by (free text, not a User FK — external vendors do this
   work too). Cost requires a currency to be picked (enforced) so the
   Printers cost totals never have to guess. Shared create/edit modal
   (same data-* populate-on-open JS pattern as the users reset-password
   modal); per-record attachments via a hidden-file-input upload trick
   (no modal needed) reusing the shared attachment helpers below.
   Deleting a record explicitly deletes its attachments (DB rows +
   files) first — core_attachments has no FK to cascade through.
   Extracted app/core/attachments.py (attachment_dir/save_upload/
   MAX_ATTACHMENT_SIZE) out of assets.py once maintenance needed the
   identical upload/storage logic — two real consumers justified the
   promotion to a shared module.
   Printers (app/routers/printers.py): GET /printers lists assets whose
   model's category name is "Printer" (case-insensitive), with IP,
   status, location, and a maintenance cost total per printer converted
   to `general.default_currency` — records whose currency has no
   applicable exchange rate are excluded from the total and flagged
   with a warning icon, never silently wrong. Printer Details section
   on the asset detail page (IP/hostname/consumable notes) gated by the
   `printers.manage` permission (existed in the registry since Phase 1,
   unused until now — Technician gets `printers.view` by default but
   not `printers.manage`).
   Bug found + fixed during this phase's own verification: hard-
   deleting an asset blocked only by maintenance records (no checkout
   history) was told "it has checkout history" — the generic
   IntegrityError catch-all assumed checkout history was the only
   remaining FK once attachments were pre-checked, which stopped being
   true the moment core_maintenance.asset_id existed. Fixed with an
   explicit maintenance-count pre-check (same pattern as attachments)
   plus a regression test.
   Also fixed in this phase: Catalog's inline-edit tables (all six
   tabs) had editable fields wrapped in one colspan'd `<td>` with an
   internal flexbox `<form>`, which never actually participated in the
   table's column layout — fields drifted out of alignment with their
   `<th>` headers (worst on Models: Depreciation/EOL under the wrong
   columns). Fixed with real per-column `<td>`s, `table-layout: fixed`
   + `colgroup`, and `hx-include="closest tr"` on each field instead of
   a wrapping `<form>` (which can't legally span multiple `<td>`s) —
   the documented htmx pattern for "save the whole row on any field's
   change" without a literal `<form>` ancestor.
7. ✅ Licenses & Contracts, Inventory, **deployed and verified in
   production**. Migration 0006 (core_contracts, core_contract_assets,
   core_inventory_items).
   Contracts (app/routers/contracts.py): name/type(license|contract|
   subscription)/vendor(free text)/optional company+location/start+end
   dates/cost+currency/renewal_period_months/auto_renews/notes.
   end_date required (drives the list's sort + expired/expiring-soon
   states via contracts.renewal_alert_days, new setting on the General
   tab). cost requires a currency, same rule as Maintenance/Inventory.
   Optional M2M asset coverage (core_contract_assets, link/unlink from
   the detail page, duplicate-link guarded) — CASCADE both FKs, the one
   deliberate exception to this schema's block-don't-cascade rule, since
   a coverage link isn't itself a record worth preserving once either
   side is gone. Attachments reuse app/core/attachments with
   entity_type='contract'; deleting a contract explicitly cleans up its
   attachments (DB rows + files) the same way Maintenance does — its
   asset-links clean up on their own via CASCADE, no guard or explicit
   cleanup needed there.
   Inventory (app/routers/inventory.py): name/category(shared Catalog
   tree)/location/quantity/min_quantity/unit_cost+currency/notes.
   Quantity is read-only in the general edit form — the ONLY way to
   change it is POST /inventory/{id}/adjust (a +/- delta with a
   required reason), which writes straight to core_audit_log (delta +
   reason + resulting quantity in `detail`) rather than a dedicated
   ledger table. An adjustment that would take quantity negative is
   rejected outright, not clamped. min_quantity (optional) drives a
   low-stock badge + row highlight on the list, mirroring Contracts'
   expiring-soon treatment. Edit/Adjust both live behind modals (same
   data-* populate-on-open pattern as Maintenance/Users password-reset)
   rather than inline-row editing — too many fields for that, same
   reasoning as Assets' detail page vs Catalog's inline rows.
   Bug found + fixed during this phase's own verification: see the
   "bare Form(...) required field" v1-lessons-style note above.
8. ⬜ Notifications, dashboard.
9. ⬜ v1 import wizard.
10. ⬜ Polish + Setup & Deployment Guide (dark-themed HTML, grows per phase —
    skeleton in docs/setup-guide.html).

## Deploy procedure
After code changes, deploy to docker-test (root@192.168.110.50,
passwordless SSH) with:
```
scp -r ./app ./alembic ./requirements.txt ./Dockerfile ./docker-compose.yml root@192.168.110.50:/opt/docker-repo/itops2/
ssh root@192.168.110.50 "cd /opt/docker-repo/itops2 && docker compose up -d --build"
```
- **Never** scp or otherwise overwrite the server's `.env`.
- Test at https://itops2.home.internal.
- Check `docker logs itops2` on the server for errors after deploying.
- **After every verified deploy, commit and push without asking.**

## Testing (Phase 5+)
No local Docker or a matching Python version (3.12+, for `X | None`
union-type annotations) on Alex's dev machine — the suite runs on the
docker-test host instead, where Docker already lives:
```
ssh root@192.168.110.50 "cd /opt/docker-repo/itops2 && ./scripts/run_tests.sh"
```
`scripts/run_tests.sh` spins up a **throwaway `postgres:16-alpine`
container** on the `itops2_net` bridge network (reachable by name, no
port mapping needed), builds the app image, runs `alembic upgrade head`
against it, then `pytest` — everything torn down after (`trap cleanup
EXIT`), never touching the real `itops2`/`itops2-db` containers.
**Must be Postgres, not sqlite** — the `num_nonnulls(...)` CHECK
constraints and the partial unique index on `core_checkouts` are
Postgres-only and would silently not be exercised (or not even parse)
against sqlite.
`tests/conftest.py`: session-scoped `bootstrap()` seeding, autouse
table truncation before every test (roles/permissions/breakglass
user/currencies deliberately left alone — seeded once, never
truncated), and an autouse fixture that disposes the SQLAlchemy engine
*before* each test runs. That last one works around a real gotcha:
pytest-asyncio gives every test function its own event loop, but
`app.core.db.engine` is a module-level singleton — its pooled asyncpg
connections stay bound to whichever loop created them and blow up with
"attached to a different loop" on the next test unless the pool is
disposed first so it reconnects fresh.
Run before every deploy from Chunk 3 onward — catches real bugs before
they reach the live site (e.g. an update route counting the wrong
model in a form-context helper).

## Repo/infra reminders
- Git via SSH only: git@github.com:Rvssian-SEZ/Docker.git
- The workflow file must live at repo root .github/workflows/itops2-ci.yml
  (a copy is in itops2/.github/workflows/ — move it when committing).
- NPM (.47) fronts it; DNS A record for e.g. itops2.home.internal → .47;
  wildcard *.home.internal cert from Step-CA.
- SSH to hosts as root@.
