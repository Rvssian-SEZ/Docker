"""
Authentik user sync — pulls all users from the Authentik API and upserts
them into the local DB. Runs on a schedule and can be triggered manually.

Requires AUTHENTIK_API_TOKEN in .env (create a token in Authentik under
Admin > Directory > Tokens & App passwords).
"""

import asyncio
import logging
import os
from datetime import datetime

import httpx

from core.database import SessionLocal
from models.user import User

logger = logging.getLogger(__name__)

# In-memory sync state — survives the process lifetime
_state = {
    "last_sync": None,       # datetime
    "last_count": 0,         # users synced
    "last_error": None,      # last error message if any
    "in_progress": False,
}


def get_sync_state() -> dict:
    return _state.copy()


async def sync_users_from_authentik() -> dict:
    """
    Fetch all users from the Authentik API and upsert into local DB.
    Handles pagination automatically.
    """
    from core.config import settings

    if not settings.AUTHENTIK_API_TOKEN:
        raise ValueError("AUTHENTIK_API_TOKEN is not set — cannot sync users")

    if _state["in_progress"]:
        return {"status": "already_running"}

    _state["in_progress"] = True
    _state["last_error"] = None

    ca_cert = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or True

    try:
        users_data = []
        page = 1
        page_size = 100

        async with httpx.AsyncClient(timeout=30, verify=ca_cert) as client:
            while True:
                url = (
                    f"{settings.AUTHENTIK_BASE_URL}/api/v3/core/users/"
                    f"?page_size={page_size}&page={page}"
                )
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.AUTHENTIK_API_TOKEN}"},
                )
                response.raise_for_status()
                data = response.json()
                users_data.extend(data.get("results", []))

                pagination = data.get("pagination", {})
                if not pagination.get("next"):
                    break
                page += 1

        # Upsert into DB
        db = SessionLocal()
        try:
            count = 0
            for u in users_data:
                # Use Authentik UUID as sub — matches what OIDC sends
                sub = u.get("uuid") or str(u.get("pk"))
                if not sub:
                    continue

                # Try matching by sub first, then by username
                user = db.query(User).filter(User.sub == sub).first()
                if not user:
                    user = db.query(User).filter(User.username == u["username"]).first()
                    if user:
                        user.sub = sub  # backfill sub for existing users

                if not user:
                    user = User(sub=sub)
                    db.add(user)

                user.username = u.get("username", sub)
                user.email = u.get("email", "")
                user.full_name = u.get("name", "")
                user.is_active = u.get("is_active", True)

                # Groups
                groups = [g["name"] for g in u.get("groups_obj", [])]
                user.groups = ",".join(groups)

                # Extended attributes (populated from LDAP mappings in Authentik)
                attrs = u.get("attributes") or {}
                if attrs.get("phone") and not user.phone:
                    user.phone = attrs["phone"]
                if attrs.get("department") and not user.department:
                    user.department = attrs["department"]
                if attrs.get("title") and not user.title:
                    user.title = attrs["title"]

                count += 1

            db.commit()
            _state["last_sync"] = datetime.utcnow()
            _state["last_count"] = count
            logger.info(f"Authentik sync complete: {count} users")
            return {"status": "ok", "synced": count, "at": _state["last_sync"].isoformat()}

        finally:
            db.close()

    except Exception as e:
        _state["last_error"] = str(e)
        logger.error(f"Authentik sync failed: {e}")
        raise
    finally:
        _state["in_progress"] = False


async def sync_loop(interval_seconds: int = 3600):
    """Background loop — syncs on startup then every interval_seconds."""
    # Initial sync after a short delay to let the app finish starting
    await asyncio.sleep(10)
    while True:
        try:
            await sync_users_from_authentik()
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}")
        await asyncio.sleep(interval_seconds)
