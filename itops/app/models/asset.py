import enum
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class AssetStatus(str, enum.Enum):
    available = "available"
    assigned = "assigned"
    maintenance = "maintenance"
    retired = "retired"
    lost = "lost"


class AssetCategory(str, enum.Enum):
    laptop = "Laptop"
    desktop = "Desktop"
    monitor = "Monitor"
    phone = "Phone"
    tablet = "Tablet"
    printer = "Printer"
    networking = "Networking"
    server = "Server"
    peripheral = "Peripheral"
    other = "Other"


class ITAsset(Base):
    __tablename__ = "it_assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)          # e.g. "Dell XPS 15"
    asset_tag = Column(String, unique=True, index=True)         # e.g. "AST-0042"
    category = Column(Enum(AssetCategory), default=AssetCategory.other)
    manufacturer = Column(String, default="")
    model = Column(String, default="")
    serial_number = Column(String, default="")
    status = Column(Enum(AssetStatus), default=AssetStatus.available, nullable=False)

    # Assignment — nullable: unassigned when status=available
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    purchase_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    purchase_price = Column(String, default="")   # string to avoid currency complexity
    supplier = Column(String, default="")
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assigned_user = relationship("User", back_populates="it_assets")

    def __repr__(self):
        return f"<ITAsset {self.asset_tag}: {self.name}>"

    @property
    def status_badge(self) -> str:
        """Bootstrap badge class for the asset status."""
        return {
            AssetStatus.available: "success",
            AssetStatus.assigned: "primary",
            AssetStatus.maintenance: "warning",
            AssetStatus.retired: "secondary",
            AssetStatus.lost: "danger",
        }.get(self.status, "secondary")
