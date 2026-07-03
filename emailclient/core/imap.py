"""
IMAP helpers using imapclient.
Dovecot master-user login: "targetuser*mailadmin" / IMAP_MASTER_PASS
Self-signed cert on Mail LXC — SSL verification disabled.
"""
import ssl
import email
import email.header
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from imapclient import IMAPClient
from core.config import settings

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _creds_for(mailbox_user: str) -> tuple[str, str]:
    return (
        f"{mailbox_user}*{settings.IMAP_MASTER_USER}",
        settings.IMAP_MASTER_PASS,
    )


@contextmanager
def imap_for(mailbox_user: str):
    username, password = _creds_for(mailbox_user)
    client = IMAPClient(
        settings.IMAP_HOST,
        port=settings.IMAP_PORT,
        ssl=True,
        ssl_context=_ssl_ctx,
    )
    try:
        client.login(username, password)
        yield client
    finally:
        try:
            client.logout()
        except Exception:
            pass


# ── DTOs ──────────────────────────────────────────────────────────────────────

@dataclass
class MessageSummary:
    uid: int
    subject: str
    from_name: str
    from_addr: str
    date: Optional[datetime]
    seen: bool
    size: int
    msg_type: str  # fault | normal | other


@dataclass
class MessageDetail:
    uid: int
    subject: str
    from_name: str
    from_addr: str
    to_addr: str
    date: Optional[datetime]
    seen: bool
    body_text: str
    body_html: str
    msg_type: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _classify(subject: str) -> str:
    s = (subject or "").lower()
    if "fault" in s:
        return "fault"
    if "normal ac" in s or "recovery" in s:
        return "normal"
    return "other"


def _addr(addr_list) -> tuple[str, str]:
    if not addr_list:
        return ("", "")
    a = addr_list[0]
    mailbox = (a.mailbox or b"").decode(errors="replace")
    host    = (a.host    or b"").decode(errors="replace")
    name    = (a.name    or b"").decode(errors="replace") or mailbox
    return (name, f"{mailbox}@{host}")


def _decode(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        parts = email.header.decode_header(raw.decode(errors="replace"))
        decoded, enc = parts[0]
        if isinstance(decoded, bytes):
            return decoded.decode(enc or "utf-8", errors="replace")
        return decoded
    return str(raw)


# ── Public API ────────────────────────────────────────────────────────────────

def list_messages(
    mailbox_user: str,
    *,
    unread_only: bool = False,
    search_q: str = "",
    msg_type: str = "",
    limit: int = 150,
) -> list[MessageSummary]:
    with imap_for(mailbox_user) as client:
        client.select_folder("INBOX", readonly=True)

        criteria: list = []
        if unread_only:
            criteria.append("UNSEEN")
        if search_q:
            criteria += ["OR", "SUBJECT", search_q, "BODY", search_q]
        if not criteria:
            criteria = ["ALL"]

        uids = client.search(criteria)
        if not uids:
            return []

        uids = uids[-limit:]
        data = client.fetch(uids, ["FLAGS", "ENVELOPE", "RFC822.SIZE"])

        results = []
        for uid, msg_data in data.items():
            env   = msg_data.get(b"ENVELOPE")
            if not env:
                continue
            flags = msg_data.get(b"FLAGS", ())
            seen  = b"\\Seen" in flags
            size  = msg_data.get(b"RFC822.SIZE", 0)
            subj  = _decode(env.subject)
            from_name, from_addr = _addr(env.from_)
            classified = _classify(subj)

            if msg_type and classified != msg_type:
                continue

            results.append(MessageSummary(
                uid=uid,
                subject=subj or "(no subject)",
                from_name=from_name,
                from_addr=from_addr,
                date=env.date,
                seen=seen,
                size=size,
                msg_type=classified,
            ))

        results.sort(key=lambda m: (m.date or datetime.min), reverse=True)
        return results


def get_message(mailbox_user: str, uid: int) -> Optional[MessageDetail]:
    with imap_for(mailbox_user) as client:
        client.select_folder("INBOX")
        data = client.fetch([uid], ["FLAGS", "ENVELOPE", "RFC822"])
        if uid not in data:
            return None

        msg_data = data[uid]
        env = msg_data.get(b"ENVELOPE")
        raw = msg_data.get(b"RFC822", b"")

        client.add_flags([uid], [b"\\Seen"])

        parsed = email.message_from_bytes(raw)
        body_text, body_html = "", ""

        if parsed.is_multipart():
            for part in parsed.walk():
                ct = part.get_content_type()
                if ct == "text/plain" and not body_text:
                    body_text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                elif ct == "text/html" and not body_html:
                    body_html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
        else:
            payload = parsed.get_payload(decode=True)
            if payload:
                body_text = payload.decode(
                    parsed.get_content_charset() or "utf-8", errors="replace"
                )

        subj = _decode(env.subject if env else None) or "(no subject)"
        from_name, from_addr = _addr(env.from_ if env else None)
        _, to_addr = _addr(env.to if env else None)

        return MessageDetail(
            uid=uid,
            subject=subj,
            from_name=from_name,
            from_addr=from_addr,
            to_addr=to_addr,
            date=env.date if env else None,
            seen=True,
            body_text=body_text,
            body_html=body_html,
            msg_type=_classify(subj),
        )


def get_stats(mailbox_user: str) -> dict:
    with imap_for(mailbox_user) as client:
        s = client.folder_status("INBOX", ["MESSAGES", "UNSEEN"])
        return {
            "total":  s.get(b"MESSAGES", 0),
            "unread": s.get(b"UNSEEN", 0),
        }


def mark_unseen(mailbox_user: str, uid: int) -> None:
    with imap_for(mailbox_user) as client:
        client.select_folder("INBOX")
        client.remove_flags([uid], [b"\\Seen"])


def delete_message(mailbox_user: str, uid: int) -> None:
    with imap_for(mailbox_user) as client:
        client.select_folder("INBOX")
        client.delete_messages([uid])
        client.expunge()
