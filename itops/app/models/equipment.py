import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class EquipmentStatus(str, enum.Enum):
    available = "available"
    on_loan = "on_loan"
    maintenance = "maintenance"
    retired = "retired"


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)     # e.g. "Epson EB-X51 Projector"
    category = Column(String, default="")                 # free-text: Projector, Camera, etc.
    serial_number = Column(String, default="")
    asset_tag = Column(String, unique=True, nullable=True, index=True)
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.available, nullable=False)
    location = Column(String, default="")                 # storage location when not on loan
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    lending_records = relationship("LendingRecord", back_populates="equipment", lazy="select")

    def __repr__(self):
        return f"<Equipment {self.id}: {self.name}>"

    @property
    def status_badge(self) -> str:
        return {
            EquipmentStatus.available: "success",
            EquipmentStatus.on_loan: "warning",
            EquipmentStatus.maintenance: "info",
            EquipmentStatus.retired: "secondary",
        }.get(self.status, "secondary")

    @property
    def active_loan(self):
        """Return the current open lending record, if any."""
        return next(
            (r for r in self.lending_records if r.returned_at is None),
            None,
        )


class LendingRecord(Base):
    __tablename__ = "lending_records"

    id = Column(Integer, primary_key=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    lent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    due_at = Column(DateTime, nullable=True)
    returned_at = Column(DateTime, nullable=True)          # NULL = still on loan

    lent_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # staff who processed it
    notes = Column(Text, default="")

    # Relationships
    equipment = relationship("Equipment", back_populates="lending_records")
    user = relationship("User", foreign_keys=[user_id], back_populates="lendings")
    lent_by = relationship("User", foreign_keys=[lent_by_id])

    def __repr__(self):
        return f"<LendingRecord eq={self.equipment_id} user={self.user_id}>"

    @property
    def is_returned(self) -> bool:
        return self.returned_at is not None

    @property
    def is_overdue(self) -> bool:
        if self.is_returned or self.due_at is None:
            return False
        return datetime.utcnow() > self.due_at
