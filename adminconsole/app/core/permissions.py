"""Permission registry + default matrix for the three fixed roles.

Adding a permission: add the key here (and to DEFAULTS); the Settings grid
renders from PERMISSIONS automatically (Phase 2 — see CLAUDE_CONTEXT.md).

Tiers (Alex, 2026-08-19 — supersedes the spec's original suggested
starting table for Helpdesk L2):
  Helpdesk L1 — unlock, reset password (standard-user OU only). Does NOT
      get ad.create_user (Alex, 2026-08-24 — account creation is L2+),
      ad.delete_computer (Alex, 2026-09-07 — same reasoning, delete is L2+),
      ad.move_object (Alex, 2026-09-07 — same reasoning, move is L2+), or
      ad.manage_groups (Alex, 2026-09-07 — same reasoning, groups is L2+).
  Helpdesk L2 — everything Admin has EXCEPT settings.manage (the Settings
      tab, incl. Graph/Authentik/AD/break-glass-alerting/Automation
      credentials).
  Admin       — everything, including settings.manage, audit.view,
      users.manage, ad.laps_read, reports.export.
  Break-glass — everything, but it's not a role (see app/core/breakglass.py)
      and is never granted through this matrix.

OU scoping (a Helpdesk L1 shouldn't reach an account in a privileged OU
even though the role technically allows "unlock") is enforced in the AD
router against ad.scoped_ous, not here — this registry is action-level
only, matching this repo's existing permissions.py convention.
"""

from app.core.models import RoleName

PERMISSIONS: dict[str, list[str]] = {
    "AD Accounts": [
        "ad.search",
        "ad.unlock",
        "ad.reset_password",
        "ad.enable_disable",
        "ad.edit_attributes",
        "ad.laps_read",
        "ad.create_user",  # Admin + Helpdesk L2 only (Alex, 2026-08-24) — see DEFAULTS below
        "ad.delete_computer",  # Admin + Helpdesk L2 only (Alex, 2026-09-07) — see DEFAULTS below
        "ad.move_object",  # Admin + Helpdesk L2 only (Alex, 2026-09-07) — see DEFAULTS below
        # Renamed from "ad.group_membership" (Alex, 2026-09-07) — that key
        # was reserved/unused in v1 per the original spec's explicit
        # exclusion (group membership was called out as out of scope); Alex
        # asked to build it now, so it's active for Admin + Helpdesk L2
        # like the other bigger AD actions. Covers group search, view
        # members, add/remove member, create group, rename group — NOT
        # delete group (deliberately excluded, Alex's choice) and NOT a
        # hard-coded privileged-group blocklist (also Alex's explicit
        # choice — Domain Admins etc. are manageable like any other group
        # by anyone holding this permission; see CLAUDE_CONTEXT.md "Manage
        # Groups" for the tradeoff this accepts).
        "ad.manage_groups",
    ],
    "Reporting": [
        "reports.view",
        "reports.export",
    ],
    "System": [
        "settings.manage",
        "audit.view",
        "users.manage",
    ],
}

ALL_PERMISSIONS: list[str] = [p for group in PERMISSIONS.values() for p in group]

DEFAULTS: dict[RoleName, list[str]] = {
    RoleName.helpdesk_l1: [
        "ad.search",
        "ad.unlock",
        "ad.reset_password",
        "reports.view",
    ],
    RoleName.helpdesk_l2: [p for p in ALL_PERMISSIONS if p != "settings.manage"],
    RoleName.admin: list(ALL_PERMISSIONS),
}
