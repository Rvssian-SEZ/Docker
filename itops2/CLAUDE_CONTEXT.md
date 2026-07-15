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
  username=None/password=None on unauthenticated port 25. v2 lesson,
  found live against O365: a single "Use TLS" boolean can't tell
  STARTTLS (port 587, plaintext-then-upgrade) from implicit TLS (port
  465, TLS from the first byte) apart — replaced with
  smtp.security: none/starttls/tls, explicit use_tls/start_tls kwargs
  to aiosmtplib for every mode, nothing left to its own port-based
  guessing. See build-order Phase 8 for the fix and the migration.)
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
  not even an error. Found in Contracts (Phase 7), then swept across every
  router (assets, checkout, maintenance, attachments, auth, users, catalog,
  permissions, settings) before Phase 8: every bare `Form(...)`/`File(...)`
  is now `Form("")`/`Form(None)`/`File(None)` with an explicit app-level
  check. Backstopped by a global `RequestValidationError` handler
  (app/main.py) that renders the toast partial instead of raw JSON whenever
  the request carries the `HX-Request` header — catches the remaining case
  the per-route fix can't (field present but wrong type, e.g.
  `model_id=notanumber`), for whatever a future route misses. Non-htmx
  requests are untouched (still get the normal 422) — this is a courtesy
  for the app's own UI, not a blanket behavior change.
- Inline-edit table rows: never wrap several editable fields in one
  colspan'd `<td>` with an internal flexbox `<form>` — a `<form>` can't
  legally span multiple `<td>`s, so the fields never actually
  participate in the table's column layout and drift out from under
  their `<th>` headers (first found in Catalog's six inline-edit tabs,
  Phase 6; recurred in the Users list until fixed post-Phase-9). The
  default for ANY table with per-row inline editing: real one-field-
  per-`<td>` matching the header count exactly, `table-layout: fixed`
  + an explicit `<colgroup>` (narrow fixed widths for short fields —
  phone/status/badges/switches — one flexible unwidthed `<col>` for
  free-text columns like name/description), `w-100` on each input/
  select, and `hx-post`/`hx-trigger="change"`/`hx-include="closest tr"`
  on every individual field (not a wrapping `<form>`) — htmx's
  documented pattern for "save the whole row on any field's change"
  without a `<form>` ancestor. Wrap the table in `.table-responsive`
  so a narrow viewport scrolls horizontally instead of wrapping cell
  content into misalignment. Purely read-only/display tables (one
  `<td>` per `<th>`, no inline form controls) don't need this — the
  bug only exists where multiple editable fields were squeezed into
  fewer cells than headers.

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
8. ✅ Notifications, dashboard, **deployed and verified in production**.
   Migration 0007 (core_notification_subscriptions). Scheduler mechanism
   (in-app asyncio task vs. a /tasks/daily endpoint + host cron) was
   proposed to Alex and approved before building; see chunk C below for
   the rationale.
   Chunk A — SMTP core (app/core/notifications.py): send_email_raising()
   does the real aiosmtplib send, explicitly passing
   username=None/password=None when the settings store's smtp.username/
   password are blank (the v1 lesson above); send_email() is the
   fire-and-forget wrapper used by BackgroundTasks/the scheduler, which
   swallows and logs failures so a notification can never become a
   user-facing error. EVENT_TYPES/EVENT_PERMISSION map each of the five
   event types to the permission a recipient must hold to receive it
   (e.g. contract_renewal_due -> contracts.view) — a subscription alone
   isn't enough, so a role downgrade can't leave someone receiving
   alerts about data they can no longer see. Settings -> Notifications
   tab (smtp.* keys existed as placeholders since Phase 1) plus a
   test-send button that awaits the send directly (not backgrounded) so
   a misconfigured relay reports its real error, not silence.
   Chunk B — event wiring: assets.py's checkout/checkin routes queue
   notify_checkout()/notify_checkin() as BackgroundTasks with PRIMITIVE
   args (asset_tag + the target's email) after commit. A checkout/
   checkin's direct target always gets a personal notice about their own
   asset regardless of subscription state, separate from and in addition
   to the broadcast to subscribed+permissioned users. /profile carries a
   per-user subscription checklist (core_notification_subscriptions —
   presence = subscribed, no defaults seeded, matching the
   RolePermission grant-row pattern), one instant-save toggle per event
   type, same HTMX pattern as the Settings permissions grid; only shows
   a checkbox for events the user's role can currently receive.
   Chunk C — daily scheduled checks (app/core/daily_checks.py): an
   in-app asyncio task (started in app/main.py's lifespan) wakes roughly
   hourly and runs warranty-expiring / contract-renewal-due /
   inventory-low-stock checks once per calendar day, each batched into
   ONE digest email per event type (never one email per row, and never
   an empty digest). Chosen over a /tasks/daily endpoint + host cron
   specifically because it needs no host-side setup beyond the existing
   scp+docker-compose deploy procedure — every other phase's background
   work has been entirely self-contained in the container. Idempotency
   ("no duplicate warnings on restart") is a persisted date marker
   (notifications.last_daily_run setting) checked by run_if_due(),
   pulled out of the scheduler loop specifically so it's unit-testable
   without driving an infinite sleep loop. Warranty-expiry uses its own
   month-arithmetic helper (app/core/dates.py add_months — no dateutil
   dependency, clamps day-of-month e.g. 31 Jan + 1mo -> 28/29 Feb);
   contract-renewal mirrors contracts.py's _renewal_state
   "expiring_soon" bucket exactly (re-derived rather than imported,
   since routers depend on core modules and not the reverse); low-stock
   matches inventory/list.html's badge condition exactly.
   Chunk D — Dashboard (app/routers/dashboard.py, replacing the Phase 2
   placeholder index() route): asset counts by status, checkouts
   overdue/due-soon, warranty expiring, contracts renewing, low stock —
   each card links into a NEW query-string filter on the underlying list
   page (?status_type=, ?checkout_state=overdue|due_soon,
   ?warranty=expiring on Assets; ?state=expiring_soon|expired on
   Contracts; ?low_stock=1 on Inventory — none of these pages had any
   filtering before this chunk). Every card is gated by the same
   permission its linked page requires. Company scoping
   (company.scoped_users): Asset/Contract counts are restricted to the
   viewing user's own company when the setting is on AND the user has a
   company assigned (no company assigned = no scoping, e.g. the
   break-glass admin always sees everything) — **dashboard-only for
   now**; the Assets/Contracts list pages themselves still don't enforce
   company.scoped_users, a gap that predates this phase and wasn't in
   scope to close here.
   Post-launch fix (found live against a real O365 tenant, before Phase
   9): smtp.use_tls (bool) replaced with smtp.security (none/starttls/
   tls) — see the v1-lessons-style note under Locked-in decisions
   above. bootstrap.py migrates the old setting once, using smtp.port
   to disambiguate what the old bool couldn't (587 -> starttls, 465 ->
   tls, regardless of the old bool's value) since that ambiguity is
   exactly what caused the bug. The already-deployed instance had
   already run the naive pre-fix migration (use_tls=true -> "tls" on
   port 587, still wrong) before the port-aware version shipped, so its
   smtp.security was corrected by hand via the Settings UI rather than
   by a second migration pass (the migration only runs once, and by
   design never overwrites a value that's already set).
   Post-launch feature (same pre-Phase-9 pass): filter bars added to
   every list view that didn't have one (Assets, Printers, Contracts,
   Inventory) — status label/category/model/location/company/
   checked-out-state/search on Assets, location/status/hostname-IP-
   search on Printers, type/renewal-state/vendor-search on Contracts,
   category/location/low-stock-toggle/name-search on Inventory. Common
   pattern across all four: the filter bar's `<form>` itself is the HTMX
   trigger element (hx-get back to the same list URL, hx-push-url so
   filter state lands in the URL and is bookmarkable), targeting a
   `#<page>-table` div swapped via a table-only partial template
   (`_table.html`) that the same route returns when the request carries
   HX-Request — one route and one filtering implementation serves both
   the full page and the swap, not two. All filtering happens in SQL
   (joins + WHERE), replacing the Dashboard-era (Phase 8 chunk D)
   Python-load-everything-then-filter approach for the params that
   originated there (status_type, checkout_state=overdue/due_soon,
   warranty=expiring on Assets; state= on Contracts; low_stock=1 on
   Inventory) — all of those deep links still work unchanged, now
   backed by SQL instead of a Python list comprehension. The one
   exception: Assets' warranty=expiring still finishes with a Python
   pass using app/core/dates.add_months, because Postgres's own
   date+interval arithmetic doesn't clamp short target months the same
   way (31 Jan + 1 month behaves differently) and this filter needs to
   agree with the Dashboard's own warranty-expiring count, which also
   uses add_months.
   Five more post-launch refinements (same pre-Phase-9 pass), one commit
   each:
   1. Contracts: the asset-link `<select>` had no blank leading
      `<option>`, so the browser silently preselected the first
      alphabetical asset — clicking "Link" without touching the
      dropdown linked whatever sorted first, not nothing. Fixed with a
      disabled/selected empty placeholder option.
   2. Printers: hostname already existed on core_printer_details (Phase
      6) and was already editable/displayed on the asset detail page
      and already part of the list's free-text search — the only real
      gap was the list TABLE itself never showing it as a column. Pure
      UI fix, no migration.
   3. Inventory adjustment history: a dedicated core_inventory_adjustments
      ledger table (migration 0008) rather than reconstructing history
      by parsing core_audit_log's formatted detail string — that string
      is for a human reading the audit trail, not for a program to
      parse back out reliably. The audit row stays exactly as it was
      (who-did-what); the new table is the queryable ledger
      (item_id, delta, quantity_after, reason, adjusted_by, adjusted_at
      — quantity_after stored explicitly, never replayed from deltas).
      item_id uses a plain blocking FK (not cascade): once an item has
      real adjustment history, that's data worth keeping, same
      reasoning as Assets blocking hard-delete with checkout history —
      a deliberate behavior change (previously any item was freely
      deletable). New GET /inventory/{id}/history route + a History
      button/modal on every row, gated by inventory.view (not .manage)
      since viewing history is a read operation.
   4. CSV export (Assets/Printers/Contracts/Inventory/Users): downloads
      exactly the CURRENT FILTERED view — each router's filter-building
      logic was pulled into a shared `_query_*()` function the HTML
      list route and the new `/export` route both call, so export can
      never drift from what the filter bar shows. New
      app/core/csv_export.py (UTF-8 BOM for Excel, UK date format). New
      `require_all()` in app/core/auth.py checks BOTH the list's own
      view permission AND reports.export — not just reports.export
      alone, since the permission matrix is admin-editable at runtime
      and export shouldn't be able to leak data the same role can't see
      in the UI. Company scoping (company_scope(), extracted from
      dashboard.py into app/core/scoping.py, dashboard.py now imports
      it) applies to Assets/Printers/Contracts/Users exports; Inventory
      has no company_id, never scoped, same as the Dashboard's cards.
   5. Two-level asset photos: a photo on the MODEL (shown as the
      default for every asset of that model) plus an optional per-asset
      photo that overrides it. Both levels reuse core_attachments (a
      new entity_type="model" value) rather than a dedicated column —
      "the photo" is simply the most recent image-type attachment for
      that entity; zero schema changes, one mechanism instead of two.
      Per-asset photos need no new upload UI — any image uploaded
      through an asset's EXISTING attachment form is automatically
      eligible. Model photos get a small dedicated modal (models.html
      has no attachments list UI to piggyback on) that keeps at most
      one image per model (a new upload deletes the previous). New
      app/core/photos.py: model_photo_attachment()/
      asset_photo_attachment()/effective_asset_photo() (asset's own >
      model's). Thumbnails are generated ONCE at upload time (Pillow,
      200x200 max, JPEG, stored alongside the original under
      .../thumbs/) — never resized on the fly at list-render time, plus
      `<img loading="lazy">` on list thumbnails, so a 50-row list with
      photos stays fast. Bug found during live verification (not by the
      test suite, whose Pillow-generated fixtures are always
      well-formed): a corrupt/truncated image upload raised a bare
      SyntaxError from PIL's PNG parser, not a subclass of the
      originally-caught UnidentifiedImageError/OSError, so it 500'd the
      whole upload instead of just skipping the thumbnail — broadened
      to a deliberate bare `except Exception` (thumbnailing is strictly
      best-effort). Also found while chasing that down:
      scripts/run_tests.sh's cleanup trap did `docker rm -f` without
      `-v`, leaking the throwaway Postgres container's anonymous data
      volume on every test run — enough accumulated runs filled the
      docker-test host's disk to 85% and broke a run outright. Fixed
      with `-v`; freed ~4GB pruning the backlog.
9. ✅ v1 import wizard, **deployed and verified in production**. Built as five
   reviewable chunks, in dependency order (each with its own tests, deployed
   and verified before the next started).
   Chunk 1 — schema: core_departments (name + optional company_id, scoped to
   Users only per the design decided with Alex — department_id lives on
   core_users, not core_assets); phone/job_title/department_id added to
   core_users; core_v1_import_batches + core_v1_import_rows, the wizard's
   whole traceability mechanism — one row per v1 source row examined, a join
   on (v1_table, v1_id, v2_entity_id) answers "which v1 row became which v2
   row" for anything, forever, instead of an imported_from_v1_id column
   scattered across every target table. A partial unique index enforces "at
   most one *created* v2 row per v1 source row" at the DB level (same
   DB-level-guarantee pattern as core_checkouts' one-open-checkout index),
   scoped to real (non-dry-run) rows via a denormalized is_dry_run column — a
   partial index's WHERE clause can't reach a joined table's column.
   Chunk 2 — read-only connection + currency parsing: app/core/v1_source.py's
   V1Source connects with `default_transaction_read_only=on` at the Postgres
   protocol level (v1 rejects any write structurally, not because app code
   chooses not to send one) and additionally wraps every fetch in its own
   read-only transaction; its public interface is fetch()/close()/connect()
   only — no execute() exists to reach for. app/core/v1_currency.py parses
   v1's free-text money fields ("1000 SCR", "£200", "Rs 10000.00") against
   the import.currency_symbol_map setting (not hardcoded — "Rs" only means
   SCR for one specific deployment); a bare number with no symbol/code is
   never defaulted to a currency, always flagged for manual review instead.
   Chunk 3 — module mappers (app/core/import_mappers/), one v1 module per
   file, all sharing Manufacturer/Category/Model/StatusLabel/Department/
   Location synthesis helpers (case-insensitive dedup, "Unknown X" placeholder
   for blanks, never a guessed specific value): Users (matched by username
   alone, mirroring oidc.py's own provision_user() — a match backfills only
   currently-NULL fields, never overwrites); Assets + Checkouts (v1's
   "assigned" status is never written directly to status_label_id — a
   deployed-type status is only reachable via a real checkout, so the asset
   is created Available first and a synthesized Checkout is opened once it
   has an id, replaying the same fields the live checkout route itself
   sets); Equipment + its full lending_records history (checkout state
   derived entirely from lending_records, not v1's own status enum, to avoid
   trusting two overlapping signals — every lend/return cycle becomes its
   own Checkout row, open or closed, not just a current-state snapshot);
   Printers + printer_repairs (no checkout replay — v1 printers have no
   assigned-user concept at all); Attachments (asset photos via v1's
   photo_is_model_photo flag, which maps directly onto v2's own two-level
   model/asset photo mechanism with no new logic needed; printer_attachments)
   — both copied from v1's read-only bind-mounted upload volumes via a new
   app/core/attachments.py:copy_from_disk(), same storage convention as the
   live upload routes; Contracts (v1's saas/support/vendor collapse onto
   v2's subscription/contract/contract — v1 has no license concept at all;
   a v1 "cancelled" status has nothing to map to since v2 computes
   active/expiring/expired from end_date rather than storing a status, so
   cancelled contracts are flagged, not imported); Inventory (opening_stock
   becomes the starting quantity, then stock_receipts + inventory_deployments
   are replayed as core_inventory_adjustments in TRUE chronological order
   merged across both v1 source tables — quantity_after is stored explicitly
   per InventoryAdjustment's own design, so replaying by insertion order
   instead of timestamp order would produce wrong running totals). Real bug
   caught by the test suite before it ever reached staging: a single v1 row
   producing two tracked artifacts (an asset's photo, a deployment's return)
   under the SAME v1_table/v1_id as its parent collided with the partial
   unique index — fixed by giving each derived artifact its own v1_table
   namespace (e.g. "it_assets_photo", "inventory_deployments_return").
   Chunk 4 — the wizard itself: app/core/import_mappers/orchestrator.py
   runs the selected modules in a FIXED dependency order (not
   admin-configurable — Users before anything referencing it, it_assets
   before its photos, etc.) and commits; there's no separate "roll back
   the preview" step because every mapper already skips its own
   target-table writes when batch.dry_run is set while STILL writing its
   V1ImportRow either way, which is the whole reason is_dry_run exists as
   a real, persisted column. A run that fails partway still commits
   whatever it already flushed — partial progress on a real run is real
   progress, and the partial unique index means a later re-run picks up
   exactly where it left off. Settings → Import (new tab) makes the four
   import.* settings (v1_database_url, currency_symbol_map, and the two
   upload paths) editable; the v1 Import page (sidebar, import.run
   permission) is a module picker + dry-run/real switch + batch history,
   and each batch's detail page is both the results view and the
   flagged-row manual-review queue (a simple filter on V1ImportRow.outcome,
   no separate mechanism needed).
   280 tests across the five chunks (up from 185 before Phase 9 started).
   Post-Phase-9 fix: the Users list table had inherited the same
   colspan'd-`<td>`-plus-flexbox-`<form>` bug the Catalog tables had
   before their Phase 6 fix (see "v1 lessons already encoded here" above)
   — Phone/Title/Department/Role/Company/Active all jammed into one
   merged cell, drifting out from under their headers, worst on
   Department where the "no department" placeholder truncated in a
   too-narrow select. Fixed with the same treatment: real per-column
   `<td>`s, `table-layout: fixed` + `colgroup` (Department widened to
   12rem specifically to stop the truncation), and `hx-include="closest
   tr"` on every field instead of the wrapping `<form>`. Swept every
   other table for the same pattern (asset detail tabs, contracts
   detail, import batch review, inventory adjustment history, currency
   settings, permissions grid) — none of the others had it; Catalog's
   own tables and the Contracts/Printers/Inventory list pages already
   had `table-layout: fixed` from having been built after the original
   fix. The pattern itself is now documented as the standing default
   for inline-edit tables, not just a one-off fix, so it doesn't need
   rediscovering a third time.
10. ⬜ Polish + Setup & Deployment Guide (dark-themed HTML, grows per phase —
    skeleton in docs/setup-guide.html; the v1 import section (§16) is
    already written as part of Phase 9).

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
