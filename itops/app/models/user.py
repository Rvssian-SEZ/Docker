from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    sub = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True)
    full_name = Column(String, default="")
    phone = Column(String, default="")
    department = Column(String, default="")
    title = Column(String, default="")
    location = Column(String, default="")
    groups = Column(String, default="")
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    it_assets = relationship("ITAsset", back_populates="assigned_user", lazy="select")
    lendings = relationship(
        "LendingRecord",
        back_populates="user",
        foreign_keys="LendingRecord.user_id",
        lazy="select",
    )

    def __repr__(self):
        return f"<User {self.username}>"

    @property
    def display_name(self):
        return self.full_name or self.username
