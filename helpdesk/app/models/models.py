"""
SQLAlchemy models for the Helpdesk.

Shared tables (users, it_assets) already exist in the itops DB.
We reference them with extend_existing=True — SQLAlchemy will not
recreate them; alembic only manages the hd_* tables.
"""

from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, String, Text,
)
from sqlalchemy.orm import relationship

from core.database import Base


# ─────────────────────────────────────────────────────────────────────────────
#  Shared tables from itops (already exist — read-only from helpdesk's PoV)
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True)
    full_name = Column(String)
    phone = Column(String, nullable=True)
    department = Column(String, nullable=True)
    title = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    groups = Column(String, default="")   # comma-separated Authentik groups
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Helpdesk relationships
    submitted_tickets = relationship(
        "Ticket", foreign_keys="Ticket.created_by_id", back_populates="created_by"
    )
    assigned_tickets = relationship(
        "Ticket", foreign_keys="Ticket.assigned_to_id", back_populates="assigned_to"
    )
    ticket_updates = relationship("TicketUpdate", back_populates="author")


class ITAsset(Base):
    __tablename__ = "it_assets"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    asset_tag = Column(String, nullable=True)
    category = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    manufacturer = Column(String, nullable=True)
    model = Column(String, nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True)

    tickets = relationship("Ticket", back_populates="asset")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpdesk tables — managed by Alembic
# ─────────────────────────────────────────────────────────────────────────────

TICKET_STATUS = ("open", "in_progress", "pending", "resolved", "closed")
TICKET_PRIORITY = ("low", "medium", "high", "critical")
TICKET_CATEGORIES = (
    "Hardware", "Software", "Network", "Access / Permissions",
    "Email / Calendar", "Printing", "Account", "Other"
)


class Ticket(Base):
    __tablename__ = "hd_tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    status = Column(
        Enum(*TICKET_STATUS, name="hd_ticket_status"),
        nullable=False,
        default="open",
        index=True,
    )
    priority = Column(
        Enum(*TICKET_PRIORITY, name="hd_ticket_priority"),
        nullable=False,
        default="medium",
        index=True,
    )
    category = Column(String(100), nullable=True, index=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    asset_id = Column(Integer, ForeignKey("it_assets.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id], back_populates="submitted_tickets")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id], back_populates="assigned_tickets")
    asset = relationship("ITAsset", back_populates="tickets")
    updates = relationship(
        "TicketUpdate", back_populates="ticket",
        order_by="TicketUpdate.created_at",
        cascade="all, delete-orphan",
    )

    @property
    def is_overdue(self) -> bool:
        if self.sla_due_at and self.status not in ("resolved", "closed"):
            return datetime.utcnow() > self.sla_due_at
        return False

    @property
    def resolution_hours(self) -> float | None:
        if self.closed_at:
            delta = self.closed_at - self.created_at
            return round(delta.total_seconds() / 3600, 2)
        return None

    @property
    def status_badge(self) -> str:
        return {
            "open": "danger",
            "in_progress": "warning",
            "pending": "secondary",
            "resolved": "success",
            "closed": "dark",
        }.get(self.status, "secondary")

    @property
    def priority_badge(self) -> str:
        return {
            "low": "secondary",
            "medium": "info",
            "high": "warning",
            "critical": "danger",
        }.get(self.priority, "secondary")


class TicketUpdate(Base):
    __tablename__ = "hd_ticket_updates"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("hd_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ticket = relationship("Ticket", back_populates="updates")
    author = relationship("User", back_populates="ticket_updates")
