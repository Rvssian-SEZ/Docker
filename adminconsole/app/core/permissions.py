"""Permission registry + default matrix for the three fixed roles.

Adding a permission: add the key here (and to DEFAULTS); the Settings grid
renders from PERMISSIONS automatically (Phase 2 — see CLAUDE_CONTEXT.md).

Tiers (Alex, 2026-08-19 — supersedes the spec's original suggested
starting table for Helpdesk L2):
  Helpdesk L1 — unlock, reset password (standard-user OU only)
  Helpdesk L2 — everything Admin has EXCEPT settings.manage (the Settings
      tab, incl. Graph/Authentik/AD/break-glass-alerting/Automation
      credentials) — deliberately excludes ad.group_membership too, same
      as Admin (that permission is reserved/unused in v1 regardless).
  Admin       — everything except ad.group_membership (out of scope, see
      spec) — includes settings.manage, audit.view, users.manage,
      ad.laps_read, reports.export.
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
        "ad.group_membership",  # granted to no default role in v1 (out of scope, see spec) — reserved
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
    RoleName.helpdesk_l2: [p for p in ALL_PERMISSIONS if p not in ("ad.group_membership", "settings.manage")],
    RoleName.admin: [p for p in ALL_PERMISSIONS if p != "ad.group_membership"],
}
