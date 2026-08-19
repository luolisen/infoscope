from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class UserModelPreference(Base):
    __tablename__ = "user_model_preferences"
    __table_args__ = (
        CheckConstraint(
            "source_id IN ('deepseek_official', 'gpt_5_5', 'ai_ping')",
            name="ck_user_model_preferences_source",
        ),
        CheckConstraint(
            "(source_id = 'deepseek_official' AND model_id IN "
            "('deepseek-v4-flash', 'deepseek-v4-pro')) OR "
            "(source_id = 'gpt_5_5' AND model_id = 'gpt-5.5') OR "
            "(source_id = 'ai_ping' AND model_id IN "
            "('DeepSeek-V4-Flash-0731', 'DeepSeek-V4-Pro', 'Kimi-K3', 'Qwen3.8-Max'))",
            name="ck_user_model_preferences_source_model",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
