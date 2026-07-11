import enum
from datetime import datetime, date

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
    name = Column(String, nullable=False, index=True)
    asset_tag = Column(String, unique=True, index=True)
    category = Column(Enum(AssetCategory), default=AssetCategory.other)
    manufacturer = Column(String, default="")
    model = Column(String, default="")
    serial_number = Column(String, default="")
    status = Column(Enum(AssetStatus), default=AssetStatus.available, nullable=False)

    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    purchase_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    purchase_price = Column(String, default="")
    supplier = Column(String, default="")
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assigned_user = relationship("User", back_populates="it_assets")
    inventory_deployments = relationship(
        "InventoryDeployment",
        back_populates="asset",
        lazy="select",
    )

    def __repr__(self):
        return f"<ITAsset {self.asset_tag}: {self.name}>"

    @property
    def status_badge(self):
        return {
            AssetStatus.available: "success",
            AssetStatus.assigned: "primary",
            AssetStatus.maintenance: "warning",
            AssetStatus.retired: "secondary",
            AssetStatus.lost: "danger",
        }.get(self.status, "secondary")

    @property
    def age_display(self):
        """Human-readable age from purchase_date."""
        ref = self.purchase_date or (self.created_at.date() if self.created_at else None)
        if not ref:
            return None
        today = date.today()
        months = (today.year - ref.year) * 12 + (today.month - ref.month)
        if months < 1:
            return "< 1m"
        if months < 12:
            return f"{months}m"
        years, rem = divmod(months, 12)
        return f"{years}y {rem}m" if rem else f"{years}y"

    @property
    def active_inventory(self):
        """Returns currently deployed (not returned) inventory items."""
        return [d for d in self.inventory_deployments if d.returned_at is None]
