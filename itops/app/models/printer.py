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

    # Relationships
    contract = relationship("Contract", foreign_keys=[contract_id])
    repairs = relationship("PrinterRepair", back_populates="printer",
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
    document_ref = Column(String, default="")   # invoice number, filename, reference
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    printer = relationship("Printer", back_populates="repairs")
