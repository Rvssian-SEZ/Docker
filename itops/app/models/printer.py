import enum
import re
from datetime import datetime, date

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class PrinterStatus(str, enum.Enum):
    active = "active"
    offline = "offline"
    maintenance = "maintenance"
    retired = "retired"


def _parse_amount(value) -> float | None:
    """Extract a numeric value from free-text like '1000 SCR', '$500', '£200'."""
    if not value:
        return None
    match = re.search(r'[\d]+\.?\d*', str(value).replace(',', ''))
    if match:
        return float(match.group())
    return None


class Printer(Base):
    __tablename__ = "printers"

    id = Column(Integer, primary_key=True, index=True)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    serial_number = Column(String, default="")
    asset_tag = Column(String, nullable=True, unique=True, index=True)
    ip_address = Column(String, default="")
    location = Column(String, default="")
    department = Column(String, default="")
    status = Column(Enum(PrinterStatus), default=PrinterStatus.active, nullable=False)

    purchase_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    purchase_price = Column(String, default="")   # free text e.g. "1000 SCR" or "500 USD"

    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True, index=True)

    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = relationship("Contract", foreign_keys=[contract_id])
    repairs = relationship("PrinterRepair", back_populates="printer",
                           cascade="all, delete-orphan", lazy="select")
    attachments = relationship("PrinterAttachment", back_populates="printer",
                               cascade="all, delete-orphan", lazy="select")

    @property
    def total_repair_cost(self) -> float:
        return sum(
            _parse_amount(r.cost) or 0
            for r in self.repairs
            if r.cost
        )

    @property
    def tco(self) -> float:
        return (_parse_amount(self.purchase_price) or 0) + self.total_repair_cost

    @property
    def has_mixed_currencies(self) -> bool:
        """True if repair costs appear to use different currencies."""
        codes = set()
        for r in self.repairs:
            if r.cost:
                m = re.search(r'[A-Z]{2,3}|[$£₨€]', str(r.cost))
                if m:
                    codes.add(m.group())
        if self.purchase_price:
            m = re.search(r'[A-Z]{2,3}|[$£₨€]', str(self.purchase_price))
            if m:
                codes.add(m.group())
        return len(codes) > 1

    @property
    def status_badge(self):
        return {
            PrinterStatus.active: "success",
            PrinterStatus.offline: "danger",
            PrinterStatus.maintenance: "warning",
            PrinterStatus.retired: "secondary",
        }.get(self.status, "secondary")

    @property
    def warranty_expired(self):
        if not self.warranty_expiry:
            return None
        return self.warranty_expiry < date.today()


class PrinterRepair(Base):
    __tablename__ = "printer_repairs"

    id = Column(Integer, primary_key=True, index=True)
    printer_id = Column(Integer, ForeignKey("printers.id"), nullable=False, index=True)
    description = Column(String, nullable=False)
    repair_date = Column(Date, nullable=False, default=date.today)
    cost = Column(String, default="")   # free text e.g. "250 SCR"
    document_ref = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    printer = relationship("Printer", back_populates="repairs")


class PrinterAttachment(Base):
    __tablename__ = "printer_attachments"

    id = Column(Integer, primary_key=True, index=True)
    printer_id = Column(Integer, ForeignKey("printers.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, default="application/octet-stream")
    notes = Column(String, default="")
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    printer = relationship("Printer", back_populates="attachments")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    @property
    def is_pdf(self):
        return self.mime_type == "application/pdf" or self.original_filename.lower().endswith(".pdf")

    @property
    def file_size_display(self):
        if not self.file_size:
            return ""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        if self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        return f"{self.file_size / 1024 / 1024:.1f} MB"

    @property
    def icon(self):
        ext = self.original_filename.rsplit(".", 1)[-1].lower() if "." in self.original_filename else ""
        return {
            "pdf": "bi-file-earmark-pdf text-danger",
            "doc": "bi-file-earmark-word text-primary",
            "docx": "bi-file-earmark-word text-primary",
            "xls": "bi-file-earmark-excel text-success",
            "xlsx": "bi-file-earmark-excel text-success",
            "png": "bi-file-earmark-image text-info",
            "jpg": "bi-file-earmark-image text-info",
            "jpeg": "bi-file-earmark-image text-info",
        }.get(ext, "bi-file-earmark text-secondary")
