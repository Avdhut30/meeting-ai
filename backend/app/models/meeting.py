from sqlalchemy import JSON, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.core.db import Base

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="created")  # created/uploaded/processed
    original_filename = Column(String(255), nullable=True)
    audio_path = Column(String(500), nullable=True)
    mime_type = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    transcript_segments = Column(JSON, nullable=True)
    key_points = Column(JSON, nullable=True)
    decisions = Column(JSON, nullable=True)
    action_items = Column(JSON, nullable=True)
    risks = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_task_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    tasks = relationship("Task", cascade="all, delete-orphan", passive_deletes=True, back_populates="meeting")
