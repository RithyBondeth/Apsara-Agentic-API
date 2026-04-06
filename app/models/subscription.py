import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, DECIMAL
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class SubscriptionPlanModel(Base):
    __tablename__ = "subscription_plans"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    price_usd = Column(DECIMAL(10, 2), default=0)
    token_limit = Column(Integer, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    #Relationships
    subscriptions = relationship("UserSubscriptionModel", back_populates="plan", cascade="all, delete-orphan")

class UserSubscriptionModel(Base):
    __tablename__ = "user_subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="CASCADE"), index=True, nullable=False)

    status = Column(String, default="active", nullable=False)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)

    #Relationships
    user = relationship("UserModel", back_populates="subscriptions")
    plan = relationship("SubscriptionPlanModel", back_populates="subscriptions")

