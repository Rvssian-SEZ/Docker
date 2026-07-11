import enum
from datetime import datetime, date

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class InventoryCategory(str, enum.Enum):
    ram = "ram"
    ssd = "ssd"
    nvme = "nvme"
    hdd = "hdd"
    access_point = "access_point"
    network_switch = "network_switch"
    power_supply = "power_supply"
    server_parts = "server_parts"
    misc = "misc"


CATEGORY_LABELS = {
    "ram": "RAM",
    "ssd": "SSD",
    "nvme": "NVMe",
    "hdd": "HDD",
    "access_point": "Access Point",
    "network_switch": "Network Switch",
    "power_supply": "Power Supply",
    "server_parts": "Server Parts",
    "misc": "Misc",
}

CATEGORY_SHELF_LIFE = {
    "ram": 60,
    "ssd": 60,
    "nvme": 60,
    "hdd": 48,
    "access_point": 60,
    "network_switch": 84,
    "power_supply": 60,
    "server_parts": 84,
    "misc": None,
}


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    category = Column(Enum(InventoryCategory), nullable=False)
    opening_stock = Column(Integer, default=0, nullable=False)
    location = Column(String, default="")
    shelf_life_months = Column(Integer, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    receipts = relationship(
        "StockReceipt",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="select",
    )
    deployments = relationship(
        "InventoryDeployment",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category.value if self.category else "", "—")

    @property
    def total_quantity(self):
        received = sum(r.quantity for r in self.receipts)
        return (self.opening_stock or 0) + received

    @property
    def quantity_deployed(self):
        """Active deployments — not returned and not retired."""
        return sum(
            d.quantity for d in self.deployments
            if d.returned_at is None and not d.is_retired
        )

    @property
    def quantity_retired(self):
        """Permanently removed from stock."""
        return sum(d.quantity for d in self.deployments if d.is_retired)

    @property
    def quantity_available(self):
        return max(0, self.total_quantity - self.quantity_deployed - self.quantity_retired)

    @property
    def expiry_date(self):
        if not self.shelf_life_months or not self.created_at:
            return None
        from dateutil.relativedelta import relativedelta
        return self.created_at.date() + relativedelta(months=self.shelf_life_months)

    @property
    def is_expired(self):
        exp = self.expiry_date
        return exp is not None and exp < date.today()

    @property
    def days_until_expiry(self):
        exp = self.expiry_date
        if exp is None:
            return None
        return (exp - date.today()).days


class StockReceipt(Base):
    __tablename__ = "stock_receipts"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    received_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")

    item = relationship("InventoryItem", back_populates="receipts")
    received_by = relationship("User", foreign_keys=[received_by_id])


class InventoryDeployment(Base):
    __tablename__ = "inventory_deployments"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("it_assets.id"), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    deployed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deployed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    returned_at = Column(DateTime, nullable=True)
    is_retired = Column(Boolean, default=False, nullable=False)
    retired_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")

    item = relationship("InventoryItem", back_populates="deployments")
    asset = relationship("ITAsset", back_populates="inventory_deployments")
    deployed_by = relationship("User", foreign_keys=[deployed_by_id])

    @property
    def status(self):
        if self.is_retired:
            return "retired"
        if self.returned_at:
            return "returned"
        return "active"
