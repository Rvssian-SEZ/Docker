"""app/core/smtp_oauth2.py -- client-credentials token fetch (with
in-memory caching/proactive refresh) and the XOAUTH2 SASL exchange
error-decoding. The token endpoint and the SMTP connection are both
mocked throughout -- no real Microsoft tenant is reachable from this
test environment (see CLAUDE.md: this feature is built and unit-
tested, but awaiting live tenant verification).
"""

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.smtp_oauth2 import (
    _TOKEN_CACHE,
    OAuth2TokenError,
    XOAuth2Error,
    _decode_xoauth2_error,
    get_access_token,
    xoauth2_authenticate,
)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


def _mock_http_client(monkeypatch, status_code=200, json_data=None, text="", raise_transport_error=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if raise_transport_error is not None:
        post = AsyncMock(side_effect=raise_transport_error)
    else:
        post = AsyncMock(return_value=resp)
        if json_data is not None:
            resp.json = MagicMock(return_value=json_data)
        else:
            resp.json = MagicMock(side_effect=ValueError("not json"))

    client = AsyncMock()
    client.post = post
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("app.core.smtp_oauth2.httpx.AsyncClient", MagicMock(return_value=ctx))
    return post


# ---- get_access_token ----

async def test_fetches_and_returns_token(monkeypatch):
    post = _mock_http_client(monkeypatch, json_data={"access_token": "tok-123", "expires_in": 3600})
    token = await get_access_token("tenant-a", "client-a", "secret-a")
    assert token == "tok-123"
    assert post.call_count == 1
    kwargs = post.call_args.kwargs
    assert kwargs["data"]["grant_type"] == "client_credentials"
    assert kwargs["data"]["scope"] == "https://outlook.office365.com/.default"
    assert kwargs["data"]["client_id"] == "client-a"
    assert kwargs["data"]["client_secret"] == "secret-a"


async def test_token_url_includes_tenant_id(monkeypatch):
    post = _mock_http_client(monkeypatch, json_data={"access_token": "tok", "expires_in": 3600})
    await get_access_token("my-tenant-id", "client-a", "secret-a")
    called_url = post.call_args.args[0]
    assert called_url == "https://login.microsoftonline.com/my-tenant-id/oauth2/v2.0/token"


async def test_cached_token_is_reused_without_a_second_call(monkeypatch):
    post = _mock_http_client(monkeypatch, json_data={"access_token": "tok-cached", "expires_in": 3600})
    first = await get_access_token("t", "c", "s")
    second = await get_access_token("t", "c", "s")
    assert first == second == "tok-cached"
    assert post.call_count == 1


async def test_expired_token_triggers_refresh(monkeypatch):
    post = _mock_http_client(monkeypatch, json_data={"access_token": "tok-1", "expires_in": 3600})
    await get_access_token("t", "c", "s")
    assert post.call_count == 1

    # Manually age the cached entry past the safety margin.
    key = ("t", "c", "s")
    token, _ = _TOKEN_CACHE[key]
    _TOKEN_CACHE[key] = (token, time.monotonic() - 1)

    post2 = _mock_http_client(monkeypatch, json_data={"access_token": "tok-2", "expires_in": 3600})
    refreshed = await get_access_token("t", "c", "s")
    assert refreshed == "tok-2"
    assert post2.call_count == 1


async def test_different_credentials_do_not_share_a_cache_entry(monkeypatch):
    post = _mock_http_client(monkeypatch, json_data={"access_token": "tok-x", "expires_in": 3600})
    await get_access_token("tenant-1", "client-1", "secret-1")
    await get_access_token("tenant-2", "client-1", "secret-1")
    assert post.call_count == 2


async def test_non_200_response_raises_with_error_description(monkeypatch):
    _mock_http_client(
        monkeypatch, status_code=401,
        json_data={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret."},
    )
    with pytest.raises(OAuth2TokenError, match="Invalid client secret"):
        await get_access_token("t", "c", "wrong-secret")


async def test_non_200_response_with_non_json_body_still_raises(monkeypatch):
    _mock_http_client(monkeypatch, status_code=500, text="internal server error")
    with pytest.raises(OAuth2TokenError, match="500"):
        await get_access_token("t", "c", "s")


async def test_response_with_no_access_token_raises(monkeypatch):
    _mock_http_client(monkeypatch, json_data={"expires_in": 3600})
    with pytest.raises(OAuth2TokenError, match="no access_token"):
        await get_access_token("t", "c", "s")


async def test_transport_error_raises_oauth2_token_error(monkeypatch):
    import httpx
    _mock_http_client(monkeypatch, raise_transport_error=httpx.ConnectError("connection refused"))
    with pytest.raises(OAuth2TokenError, match="Could not reach"):
        await get_access_token("t", "c", "s")


# ---- _decode_xoauth2_error ----

def test_decode_valid_base64_json_error():
    payload = json.dumps({"status": "400", "schemes": "bearer mac", "scope": "https://outlook.office365.com/.default"})
    encoded = base64.b64encode(payload.encode()).decode()
    result = _decode_xoauth2_error(encoded)
    assert "status=400" in result
    assert "schemes=bearer mac" in result


def test_decode_valid_base64_non_json_falls_back_to_decoded_text():
    encoded = base64.b64encode(b"plain text error, not json").decode()
    assert _decode_xoauth2_error(encoded) == "plain text error, not json"


def test_decode_invalid_base64_falls_back_to_raw_message():
    raw = "not valid base64!!! ***"
    assert _decode_xoauth2_error(raw) == raw


def test_decode_empty_json_object_falls_back_to_decoded_text():
    encoded = base64.b64encode(b"{}").decode()
    assert _decode_xoauth2_error(encoded) == "{}"


# ---- xoauth2_authenticate ----

def _mock_smtp(response_code, response_message):
    smtp = AsyncMock()
    smtp.execute_command = AsyncMock(return_value=MagicMock(code=response_code, message=response_message))
    return smtp


async def test_authenticate_succeeds_on_235(monkeypatch):
    smtp = _mock_smtp(235, "2.7.0 Authentication successful")
    await xoauth2_authenticate(smtp, "svc@example.com", "tok-abc")
    args = smtp.execute_command.call_args.args
    assert args[0] == b"AUTH"
    assert args[1] == b"XOAUTH2"
    decoded = base64.b64decode(args[2]).decode()
    assert decoded == "user=svc@example.com\x01auth=Bearer tok-abc\x01\x01"


async def test_authenticate_raises_with_decoded_error_on_334_continuation(monkeypatch):
    error_payload = json.dumps({"status": "400", "schemes": "bearer mac"})
    encoded_error = base64.b64encode(error_payload.encode()).decode()
    smtp = AsyncMock()
    smtp.execute_command = AsyncMock(
        side_effect=[MagicMock(code=334, message=encoded_error), MagicMock(code=535, message="")]
    )
    with pytest.raises(XOAuth2Error, match="status=400"):
        await xoauth2_authenticate(smtp, "svc@example.com", "tok-abc")
    assert smtp.execute_command.call_count == 2  # AUTH XOAUTH2, then the empty close-out


async def test_authenticate_raises_with_decoded_error_on_direct_535(monkeypatch):
    error_payload = json.dumps({"status": "535", "schemes": "bearer"})
    encoded_error = base64.b64encode(error_payload.encode()).decode()
    smtp = _mock_smtp(535, encoded_error)
    with pytest.raises(XOAuth2Error, match="status=535"):
        await xoauth2_authenticate(smtp, "svc@example.com", "tok-abc")


async def test_authenticate_close_out_failure_does_not_mask_the_real_error(monkeypatch):
    """The best-effort empty-response close-out after a 334 must never
    swallow the actual auth failure -- if IT also raises, the original
    XOAuth2Error still surfaces."""
    error_payload = json.dumps({"status": "400"})
    encoded_error = base64.b64encode(error_payload.encode()).decode()
    smtp = AsyncMock()
    smtp.execute_command = AsyncMock(
        side_effect=[MagicMock(code=334, message=encoded_error), ConnectionError("disconnected")]
    )
    with pytest.raises(XOAuth2Error, match="status=400"):
        await xoauth2_authenticate(smtp, "svc@example.com", "tok-abc")
