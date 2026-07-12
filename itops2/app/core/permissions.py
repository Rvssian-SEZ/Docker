"""Permission registry + default matrix for the four fixed roles.

Adding a permission: add the key here (and optionally to DEFAULTS);
the Settings grid renders from PERMISSIONS automatically.
"""

from app.core.models import RoleName

# Grouped for display in the Settings grid.
PERMISSIONS: dict[str, list[str]] = {
    "Assets": [
        "assets.view",
        "assets.create",
        "assets.edit",
        "assets.delete",
        "checkout.perform",
        "maintenance.manage",
    ],
    "Catalog": [
        "catalog.view",       # manufacturers, categories, models, status labels, locations
        "catalog.manage",
    ],
    "Licenses & Contracts": [
        "contracts.view",
        "contracts.manage",
    ],
    "Inventory": [
        "inventory.view",
        "inventory.manage",
    ],
    "Printers": [
        "printers.view",
        "printers.manage",
    ],
    "Users & Companies": [
        "users.view",
        "users.manage",
        "companies.manage",
    ],
    "System": [
        "settings.manage",
        "audit.view",
        "import.run",
        "reports.export",
    ],
}

ALL_PERMISSIONS: list[str] = [p for group in PERMISSIONS.values() for p in group]

_VIEW_ONLY = [p for p in ALL_PERMISSIONS if p.endswith(".view")] + ["reports.export"]

DEFAULTS: dict[RoleName, list[str]] = {
    RoleName.admin: ALL_PERMISSIONS,
    RoleName.manager: [
        p for p in ALL_PERMISSIONS if p not in ("settings.manage", "import.run", "companies.manage")
    ],
    RoleName.technician: _VIEW_ONLY
    + ["assets.create", "assets.edit", "checkout.perform", "maintenance.manage", "inventory.manage"],
    RoleName.viewer: _VIEW_ONLY,
}
