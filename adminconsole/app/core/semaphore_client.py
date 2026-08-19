"""Triggers the Semaphore playbook that reads a computer's Windows LAPS
password (SAA/playbooks/admin_read_laps_password.yml in the Semaphore
repo) — see that file's docstring and app/core/laps_pending.py for why
this exists instead of a direct WinRM/Kerberos call from this container:
Semaphore already has proven Kerberos/WinRM trust to the DCs, and adding
that whole stack here too would duplicate it and need its own broad
domain credential, working against the least-privilege point of
provisioning svc-adminconsole in the first place.

This module only triggers the run and polls Semaphore for pass/fail
status — it never reads the task's stdout for the password (there isn't
one there; see the playbook). The actual value arrives via the
/internal/laps-callback route, awaited separately by
app/core/laps_pending.py.

Semaphore credentials (semaphore.url/username/password) are configured
in Settings like everything else, using a dedicated Semaphore account
(adminconsole-svc, task_runner role on that one project — confirmed
scoped, not admin) rather than the shared Semaphore admin login.
"""

import asyncio
import logging

import httpx

from app.core.settings_store import SettingsStore

logger = logging.getLogger(__name__)


class SemaphoreError(Exception):
    """User-presentable Semaphore trigger/poll failure."""


async def trigger_laps_read(store: SettingsStore, *, target_computer: str, callback_url: str) -> None:
    """Fire-and-poll: starts the task and waits for it to leave the
    running state, raising on error/stop so the caller can surface a
    clear message. Does NOT return the password — see module docstring.
    """
    base_url = store.get("semaphore.url").rstrip("/")
    username = store.get("semaphore.username")
    password = store.get_secret("semaphore.password")
    project_id = store.get_int("semaphore.project_id")
    template_id = store.get_int("semaphore.laps_template_id")
    if not (base_url and username and password and project_id and template_id):
        raise SemaphoreError("Semaphore is not configured (Settings -> Automation).")

    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        login_resp = await client.post("/api/auth/login", json={"auth": username, "password": password})
        if login_resp.status_code != 204:
            raise SemaphoreError("Semaphore login failed — check semaphore.username/password in Settings.")

        task_resp = await client.post(
            f"/api/project/{project_id}/tasks",
            json={
                "template_id": template_id,
                "project_id": project_id,
                "environment": (
                    '{"target_computer": "%s", "callback_url": "%s"}' % (target_computer, callback_url)
                ),
            },
        )
        if task_resp.status_code != 201:
            raise SemaphoreError(f"Semaphore task creation failed: {task_resp.status_code}")
        task_id = task_resp.json()["id"]

        # Confirmed live (task #60): repo clone + WinRM/Kerberos setup +
        # the actual GKDS decrypt call can legitimately take well over
        # 20s — a real reveal timed out here even though the task itself
        # later showed "success", because the DC's callback POST arrived
        # after this had already given up and the app deleted the pending
        # slot (laps_pending's TTL). Both budgets now aligned around ~90s.
        for _ in range(90):
            await asyncio.sleep(1)
            status_resp = await client.get(f"/api/project/{project_id}/tasks/{task_id}")
            status = status_resp.json().get("status")
            if status == "success":
                return
            if status in ("error", "stopped"):
                raise SemaphoreError(f"LAPS read task failed (Semaphore task #{task_id}, status={status}).")
        raise SemaphoreError(f"LAPS read task timed out (Semaphore task #{task_id}).")


async def trigger_protected_unlock(store: SettingsStore, *, target_sam: str) -> None:
    """Fallback-only unlock for AdminSDHolder-protected (adminCount=1)
    accounts, called by app/routers/ad_accounts.py ONLY after the normal
    LDAPS unlock (svc-adminconsole's delegated grant) fails with
    insufficientAccessRights — see that module and CLAUDE_CONTEXT.md
    "Protected Users unlock" for why a standing per-object ACE isn't
    durable (SDProp wipes it). Uses the separate unlock_template_id
    (Ansible@SAA.SC, not svc-adminconsole) — no secret to hand back, just
    raises on failure/timeout."""
    base_url = store.get("semaphore.url").rstrip("/")
    username = store.get("semaphore.username")
    password = store.get_secret("semaphore.password")
    project_id = store.get_int("semaphore.project_id")
    template_id = store.get_int("semaphore.unlock_template_id")
    if not (base_url and username and password and project_id and template_id):
        raise SemaphoreError("Protected-account unlock fallback is not configured (Settings -> Automation).")

    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        login_resp = await client.post("/api/auth/login", json={"auth": username, "password": password})
        if login_resp.status_code != 204:
            raise SemaphoreError("Semaphore login failed — check semaphore.username/password in Settings.")

        task_resp = await client.post(
            f"/api/project/{project_id}/tasks",
            json={
                "template_id": template_id,
                "project_id": project_id,
                "environment": '{"target_sam": "%s"}' % target_sam,
            },
        )
        if task_resp.status_code != 201:
            raise SemaphoreError(f"Semaphore task creation failed: {task_resp.status_code}")
        task_id = task_resp.json()["id"]

        for _ in range(60):
            await asyncio.sleep(1)
            status_resp = await client.get(f"/api/project/{project_id}/tasks/{task_id}")
            status = status_resp.json().get("status")
            if status == "success":
                return
            if status in ("error", "stopped"):
                raise SemaphoreError(f"Protected-account unlock failed (Semaphore task #{task_id}, status={status}).")
        raise SemaphoreError(f"Protected-account unlock timed out (Semaphore task #{task_id}).")
