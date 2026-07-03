import enum
from datetime import datetime, date

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class ContractType(str, enum.Enum):
    saas = "saas"
    support = "support"
    vendor = "vendor"


class BillingCycle(str, enum.Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    annual = "annual"
    one_time = "one_time"


class ContractStatus(str, enum.Enum):
    active = "active"
    expiring_soon = "expiring_soon"
    expired = "expired"
    cancelled = "cancelled"


CONTRACT_TYPE_LABELS = {
    ContractType.saas: "SaaS / Software",
    ContractType.support: "Support Contract",
    ContractType.vendor: "Vendor Service",
}

BILLING_CYCLE_LABELS = {
    BillingCycle.monthly: "Monthly",
    BillingCycle.quarterly: "Quarterly",
    BillingCycle.annual: "Annual",
    BillingCycle.one_time: "One-time",
}


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    contract_type = Column(Enum(ContractType), nullable=False)
    status = Column(Enum(ContractStatus), default=ContractStatus.active, nullable=False)

    vendor_name = Column(String, default="")
    vendor_contact_name = Column(String, default="")
    vendor_contact_email = Column(String, default="")
    vendor_contact_phone = Column(String, default="")

    cost = Column(String, default="")
    billing_cycle = Column(Enum(BillingCycle), nullable=True)

    start_date = Column(Date, nullable=True)
    renewal_date = Column(Date, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", foreign_keys=[owner_id])

    @property
    def type_label(self):
        return CONTRACT_TYPE_LABELS.get(self.contract_type, self.contract_type)

    @property
    def cycle_label(self):
        return BILLING_CYCLE_LABELS.get(self.billing_cycle, "") if self.billing_cycle else ""

    @property
    def days_until_renewal(self):
        if not self.renewal_date:
            return None
        return (self.renewal_date - date.today()).days

    @property
    def computed_status(self):
        if self.status == ContractStatus.cancelled:
            return ContractStatus.cancelled
        if not self.renewal_date:
            return ContractStatus.active
        days = self.days_until_renewal
        if days < 0:
            return ContractStatus.expired
        if days <= 30:
            return ContractStatus.expiring_soon
        return ContractStatus.active

    @property
    def status_badge(self):
        return {
            ContractStatus.active: "success",
            ContractStatus.expiring_soon: "warning",
            ContractStatus.expired: "danger",
            ContractStatus.cancelled: "secondary",
        }.get(self.computed_status, "secondary")
