"""LDAPS client for AD account management — unlock, password reset,
enable/disable, and attribute edits.

LAPS is deliberately NOT read here: this forest runs Windows LAPS with
password encryption on (confirmed live — see
adminconsole/CLAUDE_CONTEXT.md "AD service account" section), which
stores the password DPAPI-NG-encrypted; decrypting it needs a real
Windows-side call (Get-LapsADPassword), not a plain LDAP attribute read.
See app/core/semaphore_client.py + app/core/laps_pending.py for that path.

STATUS: the service account (svc-adminconsole) and its domain-wide dsacls
delegation for unlock/reset/enable-disable/attribute-edit are confirmed
live (see CLAUDE_CONTEXT.md) — the delegation exists. The app's own LDAPS
calls using that account have NOT yet been exercised end-to-end against a
real account; that's the next thing to verify, not assumed working here.

Connects with ldap3, TLS via LDAPS (not StartTLS — AD refuses plaintext
password operations regardless, but LDAPS is the simpler of the two to get
right and matches "you already have SAA-CA/PKI for it" from the spec).
Every function takes an already-open Connection (see bind()) rather than
opening its own — callers (the AD router) are responsible for closing it,
so one request's multiple operations (e.g. search then unlock) share a
single bind instead of re-authenticating per call.
"""

import logging
import ssl

from ldap3 import ALL_ATTRIBUTES, MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE, SUBTREE, Connection, Server, Tls
from ldap3.utils.dn import parse_dn

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# userAccountControl bits — see MS-ADTS 2.2.16. Flipping ACCOUNTDISABLE is
# how enable/disable actually works over LDAP (there is no separate
# "enabled" attribute). NORMAL_ACCOUNT is the base flag every regular user
# object needs; create_user() sets NORMAL_ACCOUNT|ACCOUNTDISABLE so a new
# account is never left enabled without a password already set on it.
UAC_ACCOUNTDISABLE = 0x0002
UAC_NORMAL_ACCOUNT = 0x0200


class LdapError(Exception):
    """User-presentable AD operation failure."""


def bind(ldaps_url: str, bind_dn: str, bind_password: str) -> Connection:
    # DC LDAPS certs are issued by the internal SAA-CA, not a publicly
    # trusted CA (unlike auth.saa.sc's wildcard cert, which httpx already
    # trusts via the system store) — confirmed live: without ca_certs_file
    # here, ldap3 raised CERTIFICATE_VERIFY_FAILED / unable to get local
    # issuer certificate on the very first real bind attempt.
    ca_cert_path = get_settings().ca_cert_path
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_cert_path)
    server = Server(ldaps_url, use_ssl=True, tls=tls)
    conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
    return conn


def find_user(conn: Connection, base_dn: str, sam_account_name: str) -> dict | None:
    """Returns the entry's dn + attributes dict, or None if not found."""
    conn.search(
        search_base=base_dn,
        search_filter=f"(sAMAccountName={_escape(sam_account_name)})",
        search_scope=SUBTREE,
        attributes=ALL_ATTRIBUTES,
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    return {"dn": entry.entry_dn, "attributes": entry.entry_attributes_as_dict}


def _classify(object_classes: list[str]) -> str:
    """"computer" / "contact" / "user" / "other" — search_accounts()'s
    filter matches on name-like attributes (sn/givenName/displayName/cn)
    that mail Contacts also have, so a plain "is it a computer, else
    assume user" check was mislabeling Contacts as real user accounts
    (found live, 2026-08-25) — they'd then show Unlock/Reset PW/Modify
    buttons that don't apply to them at all. AD's schema: a computer's
    objectClass chain includes "user" (computer IS-A user structurally),
    so "computer" must be checked before "user"; a Contact's chain never
    includes "user" at all (top/person/organizationalPerson/contact).
    """
    if "computer" in object_classes:
        return "computer"
    if "contact" in object_classes:
        return "contact"
    if "user" in object_classes:
        return "user"
    return "other"


def search_accounts(conn: Connection, base_dn: str, query: str, *, limit: int = 50) -> list[dict]:
    """Name/username search across users AND computers — sAMAccountName,
    givenName, sn, displayName, cn, all OR'd together, substring-
    wildcarded by default (e.g. "asedgwick" -> "*asedgwick*"). Confirmed
    live that prefix-only wildcarding ("asedgwick*") misses computers
    named "<PREFIX>-<username>" (e.g. "SAA-ASEDGWICK$" doesn't start with
    "asedgwick" at all, even though it contains it) — substring matching
    finds it without the caller needing to know the hostname's prefix
    convention, and the "$" suffix falls inside the wildcard either way.
    If the query already contains "*", it's used verbatim (the caller is
    writing their own wildcard pattern, e.g. "alexand*" for a prefix-only
    match) — only the no-wildcard default becomes a substring search.
    """
    pattern = query if "*" in query else f"*{query}*"
    escaped = _escape_wildcard(pattern)
    filt = (
        f"(|(sAMAccountName={escaped})(givenName={escaped})(sn={escaped})"
        f"(displayName={escaped})(cn={escaped}))"
    )
    conn.search(
        search_base=base_dn,
        search_filter=filt,
        search_scope=SUBTREE,
        attributes=[
            "sAMAccountName", "displayName", "mail", "objectClass",
            # Pre-fills the Modify modal (telephone/mobile/title/department) —
            # fetched here rather than on-demand so that modal can be plain
            # server-rendered, same convention as every other action modal
            # on this page.
            "telephoneNumber", "mobile", "title", "department",
        ],
        size_limit=limit,
    )
    results = []
    for entry in conn.entries:
        attrs = entry.entry_attributes_as_dict
        object_classes = [c.lower() for c in attrs.get("objectClass", [])]
        results.append(
            {
                "dn": entry.entry_dn,
                "sam": (attrs.get("sAMAccountName") or [""])[0],
                "display_name": (attrs.get("displayName") or [""])[0],
                "mail": (attrs.get("mail") or [""])[0],
                "telephone": (attrs.get("telephoneNumber") or [""])[0],
                "mobile": (attrs.get("mobile") or [""])[0],
                "title": (attrs.get("title") or [""])[0],
                "department": (attrs.get("department") or [""])[0],
                "kind": _classify(object_classes),
            }
        )
    return results


def unlock_account(conn: Connection, dn: str) -> None:
    """Clears lockoutTime — the documented way to unlock an AD account
    over LDAP (there is no dedicated "unlock" verb)."""
    ok = conn.modify(dn, {"lockoutTime": [(MODIFY_REPLACE, [0])]})
    if not ok:
        raise LdapError(f"Unlock failed: {conn.result.get('description')}")


def reset_password(conn: Connection, dn: str, new_password: str, *, force_change_at_logon: bool = True) -> None:
    """AD requires this over an already-encrypted (LDAPS) connection; a
    plaintext LDAP connection is rejected by AD itself for password ops,
    independent of anything this app does."""
    encoded = f'"{new_password}"'.encode("utf-16-le")
    ok = conn.modify(dn, {"unicodePwd": [(MODIFY_REPLACE, [encoded])]})
    if not ok:
        raise LdapError(f"Password reset failed: {conn.result.get('description')}")
    if force_change_at_logon:
        # pwdLastSet=0 forces a change at next logon.
        conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])]})


def set_enabled(conn: Connection, dn: str, current_uac: int, *, enabled: bool) -> None:
    new_uac = current_uac & ~UAC_ACCOUNTDISABLE if enabled else current_uac | UAC_ACCOUNTDISABLE
    ok = conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [new_uac])]})
    if not ok:
        raise LdapError(f"Enable/disable failed: {conn.result.get('description')}")


def list_ous(conn: Connection, base_dn: str) -> list[dict]:
    """Every organizationalUnit under base_dn — backs the Create User OU
    picker, same tree an admin would browse in Active Directory Users and
    Computers. `display` is a root->leaf breadcrumb built from the DN's
    OU= components (parse_dn handles escaped commas inside an OU name
    correctly, unlike a naive str.split(",")).
    """
    conn.search(
        search_base=base_dn,
        search_filter="(objectClass=organizationalUnit)",
        search_scope=SUBTREE,
        attributes=["ou"],
    )
    results = []
    for entry in conn.entries:
        dn = entry.entry_dn
        ou_parts = [value for attr, value, _ in parse_dn(dn) if attr.upper() == "OU"]
        results.append({"dn": dn, "display": " > ".join(reversed(ou_parts)) or dn})
    results.sort(key=lambda r: r["display"].lower())
    return results


def create_user(conn: Connection, dn: str, attributes: dict[str, str | list[str]]) -> None:
    """Creates a new AD user object, disabled — AD requires a valid
    password before an account can meaningfully be enabled, so this never
    creates an enabled, passwordless object. Caller (see
    app/routers/ad_accounts.py's create-user route) must follow up with
    reset_password() then set_enabled(enabled=True); if either of those
    fails, the object is deliberately left behind disabled rather than
    silently deleted, so nothing is lost and it's visible for follow-up.

    NOT yet live-verified against SAA.SC AD (see module docstring) —
    beyond the write-property delegation already confirmed for existing
    objects, this additionally needs a **Create User objects** (child-
    object creation) delegation on whichever OUs users will be created in,
    which is a distinct ACE from anything granted during the original
    svc-adminconsole provisioning. Confirm that grant exists before the
    first real use.
    """
    object_class = ["top", "person", "organizationalPerson", "user"]
    create_attrs: dict[str, str | int | list[str]] = {
        "userAccountControl": UAC_NORMAL_ACCOUNT | UAC_ACCOUNTDISABLE,
        **attributes,
    }
    ok = conn.add(dn, object_class=object_class, attributes=create_attrs)
    if not ok:
        raise LdapError(f"User creation failed: {conn.result.get('description')} — {conn.result.get('message')}")


def escape_dn_value(value: str) -> str:
    """Minimal RFC 4514 DN-value escaping for building a new user's RDN
    (CN=...) from a free-text display name — same escape-what-matters
    convention as _escape()/_escape_wildcard() above, not a full RFC 4514
    parser."""
    value = value.strip()
    special = ',+"\\<>;='
    escaped = "".join(f"\\{ch}" if ch in special else ch for ch in value)
    if escaped.startswith("#") or escaped.startswith(" "):
        escaped = "\\" + escaped
    if escaped.endswith(" ") and not escaped.endswith("\\ "):
        escaped = escaped[:-1] + "\\ "
    return escaped


# Attributes this app is allowed to touch via edit_attributes(). Deliberately
# excludes group membership (member/memberOf) and anything AdminSDHolder-
# protected — those stay a manual/ticketed process per the spec.
EDITABLE_ATTRIBUTES = {"givenName", "sn", "displayName", "title", "department", "telephoneNumber", "mobile", "manager"}


def edit_attributes(conn: Connection, dn: str, changes: dict[str, str]) -> None:
    disallowed = set(changes) - EDITABLE_ATTRIBUTES
    if disallowed:
        raise LdapError(f"Not permitted to edit: {', '.join(sorted(disallowed))}")
    ok = conn.modify(dn, {attr: [(MODIFY_REPLACE, [value])] for attr, value in changes.items()})
    if not ok:
        raise LdapError(f"Attribute edit failed: {conn.result.get('description')}")


def delete_object(conn: Connection, dn: str) -> None:
    """Deletes an AD object outright. Currently only wired up for computer
    accounts (see ad_accounts.py's delete-computer route, which classifies
    the target via _classify() before ever calling this, so a user account
    can't reach this path). No soft-delete here — if the AD Recycle Bin
    isn't enabled on this forest, this is unrecoverable, so the caller is
    responsible for getting operator confirmation first (see the "are you
    sure" modal in ad/search.html)."""
    ok = conn.delete(dn)
    if not ok:
        raise LdapError(f"Delete failed: {conn.result.get('description')}")


# groupType values AD/ADUC uses for the 6 standard scope x type
# combinations (MS-ADTS 2.2.11) — negative values are security groups
# (the high bit, ADS_GROUP_TYPE_SECURITY_ENABLED, set on a signed int32),
# positive are distribution-only.
GROUP_TYPES: dict[str, int] = {
    "domainlocal_security": -2147483644,
    "domainlocal_distribution": 4,
    "global_security": -2147483646,
    "global_distribution": 2,
    "universal_security": -2147483640,
    "universal_distribution": 8,
}

# Real security/distribution groups in this forest run from a few members
# to (for built-ins like "Domain Users") every account in the domain —
# resolving every member's display info for a group that large would be
# slow and mostly useless in a UI. Caps what group_detail shows/resolves;
# the group's own `member` attribute is untouched, this only limits what
# one page load renders.
MEMBER_DISPLAY_LIMIT = 1000


def search_groups(conn: Connection, base_dn: str, query: str, *, limit: int = 50) -> list[dict]:
    """Name/username search across group objects — cn and sAMAccountName,
    substring-wildcarded by default, same convention as search_accounts()."""
    pattern = query if "*" in query else f"*{query}*"
    escaped = _escape_wildcard(pattern)
    filt = f"(&(objectClass=group)(|(cn={escaped})(sAMAccountName={escaped})))"
    conn.search(
        search_base=base_dn,
        search_filter=filt,
        search_scope=SUBTREE,
        attributes=["cn", "sAMAccountName", "description", "member", "groupType"],
        size_limit=limit,
    )
    results = []
    for entry in conn.entries:
        attrs = entry.entry_attributes_as_dict
        results.append(
            {
                "dn": entry.entry_dn,
                "sam": (attrs.get("sAMAccountName") or [""])[0],
                "name": (attrs.get("cn") or [""])[0],
                "description": (attrs.get("description") or [""])[0],
                "member_count": len(attrs.get("member", [])),
            }
        )
    return results


def get_group(conn: Connection, base_dn: str, sam: str) -> dict | None:
    """Single group lookup by sAMAccountName — like find_user() but scoped
    to group objects and with the fields group_detail actually needs."""
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectClass=group)(sAMAccountName={_escape(sam)}))",
        search_scope=SUBTREE,
        attributes=["cn", "sAMAccountName", "description", "member", "groupType"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    attrs = entry.entry_attributes_as_dict
    return {
        "dn": entry.entry_dn,
        "sam": (attrs.get("sAMAccountName") or [""])[0],
        "name": (attrs.get("cn") or [""])[0],
        "description": (attrs.get("description") or [""])[0],
        "member_dns": attrs.get("member", []),
    }


def resolve_members(conn: Connection, base_dn: str, member_dns: list[str]) -> tuple[list[dict], int]:
    """Resolves a group's raw member DNs to display info in a single
    batched search (one OR filter of distinguishedName equality) rather
    than one round trip per member. Returns (resolved, total_count) —
    total_count is len(member_dns) even when the display list itself is
    capped at MEMBER_DISPLAY_LIMIT, so the caller can show "showing first
    N of M" when a group is bigger than what's rendered."""
    total = len(member_dns)
    shown = member_dns[:MEMBER_DISPLAY_LIMIT]
    if not shown:
        return [], total
    filt = "(|" + "".join(f"(distinguishedName={_escape(dn)})" for dn in shown) + ")"
    conn.search(
        search_base=base_dn,
        search_filter=filt,
        search_scope=SUBTREE,
        attributes=["sAMAccountName", "displayName", "objectClass"],
    )
    by_dn = {}
    for entry in conn.entries:
        attrs = entry.entry_attributes_as_dict
        object_classes = [c.lower() for c in attrs.get("objectClass", [])]
        by_dn[entry.entry_dn] = {
            "dn": entry.entry_dn,
            "sam": (attrs.get("sAMAccountName") or [""])[0],
            "display_name": (attrs.get("displayName") or [""])[0],
            "kind": _classify(object_classes),
        }
    # Preserve the group's own member order; fall back to a bare DN entry
    # for anything that didn't resolve (e.g. a foreign-domain SID) rather
    # than silently dropping it.
    resolved = [by_dn.get(dn, {"dn": dn, "sam": dn, "display_name": "", "kind": "other"}) for dn in shown]
    return resolved, total


def resolve_groups_by_dn(conn: Connection, base_dn: str, group_dns: list[str]) -> list[dict]:
    """Resolves a list of group DNs (as found in a user/computer's
    `memberOf`) to display info — the reverse direction of
    resolve_members(). Same one-shot batched-OR-filter shape; no display
    cap here since memberOf lists are realistically small (an account
    being in hundreds of groups is not a case this needs to optimize for
    the way a group having thousands of members is).

    Deliberately does NOT include the account's *primary* group (almost
    always "Domain Users") — that's tracked via primaryGroupID (a RID
    that has to be combined with the domain SID to resolve), a separate
    mechanism from the memberOf back-link this reads, and out of scope
    for what was asked."""
    if not group_dns:
        return []
    filt = "(|" + "".join(f"(distinguishedName={_escape(dn)})" for dn in group_dns) + ")"
    conn.search(
        search_base=base_dn,
        search_filter=filt,
        search_scope=SUBTREE,
        attributes=["cn", "sAMAccountName", "description"],
    )
    by_dn = {}
    for entry in conn.entries:
        attrs = entry.entry_attributes_as_dict
        by_dn[entry.entry_dn] = {
            "dn": entry.entry_dn,
            "sam": (attrs.get("sAMAccountName") or [""])[0],
            "name": (attrs.get("cn") or [""])[0],
            "description": (attrs.get("description") or [""])[0],
        }
    resolved = [by_dn.get(dn, {"dn": dn, "sam": dn, "name": dn, "description": ""}) for dn in group_dns]
    resolved.sort(key=lambda g: g["name"].lower())
    return resolved


def add_group_member(conn: Connection, group_dn: str, member_dn: str) -> None:
    ok = conn.modify(group_dn, {"member": [(MODIFY_ADD, [member_dn])]})
    if not ok:
        raise LdapError(f"Add member failed: {conn.result.get('description')}")


def remove_group_member(conn: Connection, group_dn: str, member_dn: str) -> None:
    ok = conn.modify(group_dn, {"member": [(MODIFY_DELETE, [member_dn])]})
    if not ok:
        raise LdapError(f"Remove member failed: {conn.result.get('description')}")


def create_group(conn: Connection, dn: str, attributes: dict[str, str | int]) -> None:
    """Creates a new AD group object. Caller (ad_accounts.py's create-group
    route) is responsible for computing groupType from GROUP_TYPES."""
    ok = conn.add(dn, object_class=["top", "group"], attributes=attributes)
    if not ok:
        raise LdapError(f"Group creation failed: {conn.result.get('description')} — {conn.result.get('message')}")


def _escape(value: str) -> str:
    """Minimal RFC 4515 filter escaping for exact-match lookups (unlock/
    reset/enable-disable/attribute-edit/LAPS all resolve one already-known
    sAMAccountName this way) — "*" IS escaped here since these calls must
    never accidentally wildcard-match the wrong account."""
    return (
        value.replace("\\", "\\5c")
        .replace("*", "\\2a")
        .replace("(", "\\28")
        .replace(")", "\\29")
        .replace("\x00", "\\00")
    )


def _escape_wildcard(value: str) -> str:
    """Same RFC 4515 escaping as _escape(), EXCEPT "*" is left alone —
    used only by search_accounts(), where "*" is a deliberate, intended
    wildcard, not user input to neutralize. Parens/backslash/null are
    still escaped so a search box can't be used for filter injection
    (e.g. typing `)(uid=*))(|(uid=` to widen or break out of the filter)."""
    return value.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("\x00", "\\00")
