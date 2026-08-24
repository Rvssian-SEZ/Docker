"""Pure helpers for the Create User flow: logon-name candidate generation
and a memorable-but-random suggested password. No LDAP/DB access here —
callers (app/routers/ad_accounts.py) check candidate availability against
AD and persist whatever's actually chosen; keeping this module pure makes
the suggestion logic trivial to reason about independent of AD state.
"""

import re
from random import SystemRandom

_sysrand = SystemRandom()  # CSPRNG-backed, same security bar as the `secrets` module used elsewhere in this app

_NON_ALPHA = re.compile(r"[^a-z]")


def _normalize(name: str) -> str:
    """Lowercase, strip anything that isn't a-z (spaces, hyphens,
    apostrophes, accents) — this org's logon names are plain ASCII (see
    the asedgwick/alsedgwick/alesedgwick convention in CLAUDE_CONTEXT.md)."""
    return _NON_ALPHA.sub("", name.lower())


def suggest_logon_names(first_name: str, last_name: str, *, max_candidates: int = 5) -> list[str]:
    """Alexander Sedgwick -> ["asedgwick", "alsedgwick", "alesedgwick", ...]
    — first-initial+lastname, then first-two-letters+lastname, and so on.
    This is the org's standing convention (Alex, 2026-08-24) for picking
    the next candidate once the short form is already taken; the caller
    checks each candidate against AD in order and uses the first free one.
    """
    first = _normalize(first_name)
    last = _normalize(last_name)
    if not first or not last:
        return []
    candidates = []
    for n in range(1, min(len(first), max_candidates) + 1):
        candidate = f"{first[:n]}{last}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


# Common, easy-to-read/type 4-letter words — deliberately plain and
# non-offensive; picked for length only (see generate_password()'s 12-char
# arithmetic), not for any deeper wordlist-quality property.
_PASSWORD_WORDS = [
    "Blue", "Frog", "Wolf", "Star", "Moon", "Fire", "Gold", "Iron", "Leaf",
    "Rock", "Wind", "Rain", "Snow", "Lake", "Hill", "Tree", "Bird", "Bear",
    "Lion", "Fish", "Duck", "Corn", "Rice", "Cake", "Bell", "Book", "Lamp",
    "Ship", "Boat", "Door", "Gate", "Wall", "Roof", "Barn", "Farm", "Park",
    "Pond", "Cave", "Peak", "Reef", "Sand", "Palm", "Fern", "Mint", "Plum",
    "Pear", "Lime", "Kite", "Drum", "Flag", "Ring", "Rope", "Nest", "Wave",
]


def generate_password() -> str:
    """Word.Word.NN — exactly 12 characters (4+1+4+1+2): two distinct
    4-letter words plus a random 2-digit number, e.g. "Blue.Frog.73".
    Suggested in plaintext for the admin to hand to the new user directly
    at account creation; the create-user route never writes this value to
    the audit log, same as reset_password's new_password."""
    word1, word2 = _sysrand.sample(_PASSWORD_WORDS, 2)
    number = _sysrand.randrange(10, 100)
    return f"{word1}.{word2}.{number}"
