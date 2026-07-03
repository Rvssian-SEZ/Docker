import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from core.config import get_settings

settings = get_settings()
logger = logging.getLogger("helpdesk.email")


async def _send(to: list[str], subject: str, html_body: str, text_body: str = ""):
    """Core async send — called from background tasks."""
    if not to:
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_tls and not settings.smtp_starttls,
            start_tls=settings.smtp_starttls,
        )
        logger.info("Email sent to %s — %s", to, subject)
    except Exception as exc:
        logger.error("Email failed to %s: %s", to, exc)


# ─── Notification helpers ─────────────────────────────────────────────────────

def _base_url() -> str:
    return settings.app_base_url.rstrip("/")


def _ticket_url(ticket_id: int) -> str:
    return f"{_base_url()}/tickets/{ticket_id}"


async def notify_ticket_created(ticket, created_by, assigned_to=None, tech_emails: list[str] = None):
    recipients = []
    if assigned_to and assigned_to.email:
        recipients.append(assigned_to.email)
    if tech_emails:
        recipients.extend(tech_emails)
    if not recipients and settings.helpdesk_admin_email:
        recipients = [e.strip() for e in settings.helpdesk_admin_email.split(",") if e.strip()]

    if not recipients:
        return

    subject = f"[Helpdesk #{ticket.id}] New Ticket: {ticket.title}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2 style="color:#0d6efd">New Support Ticket #{ticket.id}</h2>
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:6px;font-weight:bold;width:30%">Title</td>
            <td style="padding:6px">{ticket.title}</td></tr>
        <tr style="background:#f8f9fa"><td style="padding:6px;font-weight:bold">Priority</td>
            <td style="padding:6px">{ticket.priority.upper()}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Category</td>
            <td style="padding:6px">{ticket.category or '—'}</td></tr>
        <tr style="background:#f8f9fa"><td style="padding:6px;font-weight:bold">Submitted by</td>
            <td style="padding:6px">{created_by.full_name} ({created_by.email})</td></tr>
      </table>
      <div style="margin-top:16px;padding:12px;background:#f8f9fa;border-left:4px solid #0d6efd">
        <strong>Description:</strong><br>{ticket.description}
      </div>
      <p style="margin-top:16px">
        <a href="{_ticket_url(ticket.id)}" style="background:#0d6efd;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">
          View Ticket
        </a>
      </p>
    </div>
    """
    await _send(recipients, subject, html)


async def notify_ticket_updated(ticket, update, author, ticket_owner_email: str = None, assigned_to=None):
    recipients = set()
    if ticket_owner_email:
        recipients.add(ticket_owner_email)
    if assigned_to and assigned_to.email:
        recipients.add(assigned_to.email)

    # Don't notify the person who made the update
    recipients.discard(author.email)
    if not recipients:
        return

    subject = f"[Helpdesk #{ticket.id}] Update: {ticket.title}"
    note_type = "Internal Note" if update.is_internal else "Reply"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2 style="color:#0d6efd">Ticket #{ticket.id} Updated</h2>
      <p><strong>{author.full_name}</strong> added a {note_type}:</p>
      <div style="margin:12px 0;padding:12px;background:#f8f9fa;border-left:4px solid #6c757d">
        {update.content}
      </div>
      <p><strong>Status:</strong> {ticket.status.replace('_', ' ').title()}</p>
      <p>
        <a href="{_ticket_url(ticket.id)}" style="background:#0d6efd;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">
          View Ticket
        </a>
      </p>
    </div>
    """
    await _send(list(recipients), subject, html)


async def notify_ticket_closed(ticket, closed_by, ticket_owner_email: str = None):
    recipients = []
    if ticket_owner_email:
        recipients.append(ticket_owner_email)

    subject = f"[Helpdesk #{ticket.id}] Resolved: {ticket.title}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2 style="color:#198754">Ticket #{ticket.id} Resolved ✓</h2>
      <p>Your ticket <strong>{ticket.title}</strong> has been marked as resolved by
         <strong>{closed_by.full_name}</strong>.</p>
      <p>If you feel the issue is not fully resolved, please reopen the ticket.</p>
      <p>
        <a href="{_ticket_url(ticket.id)}" style="background:#198754;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">
          View &amp; Reopen
        </a>
      </p>
    </div>
    """
    await _send(recipients, subject, html)


async def notify_status_changed(ticket, changed_by, old_status: str, assigned_to=None, ticket_owner_email=None):
    recipients = set()
    if ticket_owner_email:
        recipients.add(ticket_owner_email)
    if assigned_to and assigned_to.email:
        recipients.add(assigned_to.email)
    recipients.discard(changed_by.email)
    if not recipients:
        return

    subject = f"[Helpdesk #{ticket.id}] Status changed: {ticket.title}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2 style="color:#0d6efd">Ticket #{ticket.id} — Status Updated</h2>
      <p>Status changed from <strong>{old_status.replace('_', ' ').title()}</strong>
         → <strong>{ticket.status.replace('_', ' ').title()}</strong>
         by <strong>{changed_by.full_name}</strong>.</p>
      <p>
        <a href="{_ticket_url(ticket.id)}" style="background:#0d6efd;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">
          View Ticket
        </a>
      </p>
    </div>
    """
    await _send(list(recipients), subject, html)
