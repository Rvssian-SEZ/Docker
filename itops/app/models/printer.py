import enum
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class PrinterStatus(str, enum.Enum):
    active = "active"
    offline = "offline"
    maintenance = "maintenance"
    retired = "retired"


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
    purchase_price = Column(Numeric(10, 2), nullable=True)

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
    def total_repair_cost(self):
        return sum(r.cost or 0 for r in self.repairs)

    @property
    def tco(self):
        purchase = float(self.purchase_price or 0)
        return purchase + float(self.total_repair_cost)

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
    cost = Column(Numeric(10, 2), nullable=True)
    document_ref = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    printer = relationship("Printer", back_populates="repairs")


class PrinterAttachment(Base):
    __tablename__ = "printer_attachments"

    id = Column(Integer, primary_key=True, index=True)
    printer_id = Column(Integer, ForeignKey("printers.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)           # stored on disk (UUID-prefixed)
    original_filename = Column(String, nullable=False)  # original upload name
    file_size = Column(Integer, nullable=True)          # bytes
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
