from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    chats = relationship("Chat", back_populates="user")


class Chat(Base):
    __tablename__ = 'chats'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    modified_at = Column(DateTime, default=func.now(), onupdate=func.now())
    user_id = Column(UUID(as_uuid=True), ForeignKey(
        'users.id', ondelete='CASCADE'))
    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat")


class Message(Base):
    __tablename__ = 'messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    role = Column(String(50), nullable=False)
    avatar = Column(String(255), nullable=False)
    audio_url = Column(String(255))
    created_at = Column(DateTime, default=func.now())
    chat_id = Column(UUID(as_uuid=True), ForeignKey(
        'chats.id', ondelete='CASCADE'))
    chat = relationship("Chat", back_populates="messages")


class ImageMetadata(Base):
    __tablename__ = 'image_metadata'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    content_type = Column(String(50))
    uploaded_at = Column(DateTime, default=func.now())
    size_bytes = Column(BigInteger)
    user_id = Column(UUID(as_uuid=True), ForeignKey(
        'users.id', ondelete='CASCADE'))

    user = relationship("User", back_populates="images")


User.images = relationship(
    "ImageMetadata", order_by=ImageMetadata.id, back_populates="user")
