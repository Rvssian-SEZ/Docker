"""Company-scoping helper, shared by anywhere that needs to restrict a
query to the viewing user's own company when company.scoped_users is on.

A company-less user (e.g. the break-glass admin) is never scoped —
there's nothing to scope to, and blocking such a user from seeing
everything would be a worse default than the alternative.
"""

from app.core.auth import CurrentUser
from app.core.settings_store import SettingsStore


def company_scope(user: CurrentUser, store: SettingsStore) -> int | None:
    """Returns the company_id to filter to, or None for "no scoping"."""
    if (
        store.get_bool("company.multi_enabled")
        and store.get_bool("company.scoped_users")
        and user.company_id is not None
    ):
        return user.company_id
    return None
