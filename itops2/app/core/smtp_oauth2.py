"""OAuth2 (XOAUTH2) SMTP authentication for Microsoft 365 -- a third
smtp.auth_mode alongside "basic" (see app/core/settings_store.py and
app/core/notifications.py). Client-credentials flow only: no user in
the loop, no refresh token, no token ever persisted anywhere but this
module's in-memory cache -- a restart means a fresh token fetch, which
is fine, it's one extra HTTP round-trip on the rare cold path.

aiosmtplib has no built-in XOAUTH2 mechanism (see its own
AUTH_METHODS -- PLAIN/LOGIN/CRAM-MD5 only), so the SASL exchange is
done by hand in xoauth2_authenticate() via aiosmtplib.SMTP's lower-level
execute_command(), the exact same primitive its own auth_plain()/
auth_login() are built on (verified against the installed aiosmtplib
package, not guessed).

No CA-verify pattern here (unlike httpx.AsyncClient(verify=...) calls
elsewhere against internal PKI, e.g. app/core/oidc.py) -- this talks to
Microsoft's public login.microsoftonline.com over the system trust
store, which is exactly what a public, internet-facing Microsoft
endpoint calls for.
"""

import base64
import json
import time

import httpx

_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_SCOPE = "https://outlook.office365.com/.default"
_EXPIRY_SAFETY_MARGIN_SECONDS = 60

# (tenant_id, client_id, client_secret) -> (access_token, monotonic expiry).
# Keyed on the credentials themselves, not just tenant/client -- if an
# admin edits any of the three in Settings, the cache key changes and a
# fresh token is fetched automatically. No need to hook into the
# settings-save path to invalidate a stale cache entry.
_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}


class OAuth2TokenError(Exception):
    """The token endpoint itself failed -- bad tenant/client/secret, or
    the request didn't reach Microsoft at all."""


class XOAuth2Error(Exception):
    """The SMTP server rejected the XOAUTH2 SASL exchange. The message
    is Microsoft's own decoded error where the server provided one, not
    just the raw SMTP response line."""


def _cache_key(tenant_id: str, client_id: str, client_secret: str) -> tuple[str, str, str]:
    return (tenant_id, client_id, client_secret)


async def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Client-credentials token for scope https://outlook.office365.com/.default.
    Serves a cached token when it has more than _EXPIRY_SAFETY_MARGIN_SECONDS
    left; refreshes proactively otherwise -- callers never need to
    reason about expiry themselves."""
    key = _cache_key(tenant_id, client_id, client_secret)
    cached = _TOKEN_CACHE.get(key)
    if cached is not None:
        token, expires_at = cached
        if time.monotonic() < expires_at - _EXPIRY_SAFETY_MARGIN_SECONDS:
            return token

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                _TOKEN_URL.format(tenant_id=tenant_id),
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": _SCOPE,
                },
            )
        except httpx.HTTPError as exc:
            raise OAuth2TokenError(f"Could not reach the token endpoint: {exc}") from exc

    if resp.status_code != 200:
        detail = resp.text
        try:
            detail = resp.json().get("error_description", resp.text)
        except ValueError:
            pass
        raise OAuth2TokenError(f"Token request failed ({resp.status_code}): {detail}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise OAuth2TokenError("Token endpoint returned a non-JSON response.") from exc

    token = payload.get("access_token")
    if not token:
        raise OAuth2TokenError("Token response had no access_token.")

    expires_in = payload.get("expires_in", 3600)
    _TOKEN_CACHE[key] = (token, time.monotonic() + expires_in)
    return token


def _decode_xoauth2_error(raw_message: str) -> str:
    """XOAUTH2 error responses carry a base64-encoded JSON payload (RFC-
    documented behavior, e.g. {"status":"400","schemes":"bearer mac",
    "scope":"..."}) -- Microsoft's real error is inside that, not in the
    SMTP response text around it. Falls back to the raw message whenever
    it isn't decodable as base64+JSON, so a caller always gets SOMETHING
    readable rather than a decode exception."""
    try:
        decoded = base64.b64decode(raw_message.strip()).decode("utf-8", errors="replace")
    except ValueError:
        return raw_message
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return decoded
    if isinstance(payload, dict) and payload:
        return "; ".join(f"{k}={v}" for k, v in payload.items())
    return decoded


async def xoauth2_authenticate(smtp, from_address: str, token: str) -> None:
    """Performs the manual SASL XOAUTH2 exchange over an already-
    connected, already-STARTTLS'd aiosmtplib.SMTP instance (`smtp`;
    left untyped to avoid importing aiosmtplib's private protocol types
    here -- callers pass a live aiosmtplib.SMTP). Raises XOAuth2Error
    with Microsoft's decoded error message on any non-success response.

    Per RFC 4954 + Microsoft/Google's documented XOAUTH2 behavior:
    success is a direct 235; failure is either a 334 continuation
    carrying the error payload (client must send an empty response to
    close out the exchange) or, on some servers, a 535 with the payload
    inline. Handled uniformly since we can't verify byte-for-byte
    against a real tenant in this environment (see CLAUDE.md)."""
    auth_string = f"user={from_address}\x01auth=Bearer {token}\x01\x01"
    encoded = base64.b64encode(auth_string.encode()).decode()
    response = await smtp.execute_command(b"AUTH", b"XOAUTH2", encoded.encode())

    if response.code == 235:
        return

    if response.code == 334:
        error_detail = _decode_xoauth2_error(response.message)
        try:
            # Close out the exchange per RFC -- best-effort, the caller
            # is about to raise and disconnect regardless.
            await smtp.execute_command(b"")
        except Exception:
            pass
        raise XOAuth2Error(f"XOAUTH2 authentication failed: {error_detail}")

    error_detail = _decode_xoauth2_error(response.message)
    raise XOAuth2Error(f"XOAUTH2 authentication failed ({response.code}): {error_detail}")
