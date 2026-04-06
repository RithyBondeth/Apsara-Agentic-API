import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String, nullable=False)
    agent_config = Column(JSONB, nullable=True) # Store specialized agent instructions and configurations

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("UserModel", back_populates="projects")
    files = relationship("FileModel", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("ConversationModel", back_populates="project", cascade="all, delete-orphan")


class FileModel(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    path = Column(String, nullable=False)
    content = Column(Text)
    version = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("ProjectModel", back_populates="files")
    revisions = relationship("FileRevisionModel", back_populates="file", cascade="all, delete-orphan")


class FileRevisionModel(Base):
    __tablename__ = "file_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), index=True, nullable=False)
    
    version_number = Column(Integer, nullable=False)
    content = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("FileModel", back_populates="revisions")