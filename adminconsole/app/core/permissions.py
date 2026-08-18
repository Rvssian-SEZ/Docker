"""Permission registry + default matrix for the three fixed roles.

Adding a permission: add the key here (and to DEFAULTS); the Settings grid
renders from PERMISSIONS automatically (Phase 2 — see CLAUDE_CONTEXT.md).

Tiers and their intended scope come straight from the spec's suggested
starting table:
  Helpdesk L1 — unlock, reset password (standard-user OU only)
  Helpdesk L2 — + enable/disable, non-privileged attribute edits
  Admin       — + LAPS retrieval, group membership changes, settings, audit
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
    RoleName.helpdesk_l2: [
        "ad.search",
        "ad.unlock",
        "ad.reset_password",
        "ad.enable_disable",
        "ad.edit_attributes",
        "reports.view",
    ],
    RoleName.admin: [p for p in ALL_PERMISSIONS if p != "ad.group_membership"],
}
