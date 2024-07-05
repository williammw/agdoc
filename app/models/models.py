# models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class ImageType(enum.Enum):
    AVATAR = "avatar"
    POST = "post"
    OTHER = "other"


Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(String(28), primary_key=True)
    username = Column(String(255), unique=True)
    email = Column(String(255), unique=True, nullable=False)
    auth_provider = Column(String(50), nullable=False, default='firebase')
    created_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    full_name = Column(String(255))
    bio = Column(Text)
    avatar_url = Column(String(255))

    chats = relationship("Chat", back_populates="user")
    images = relationship("ImageMetadata", back_populates="user")


class Chat(Base):
    __tablename__ = 'chats'
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    modified_at = Column(DateTime, default=func.now(), onupdate=func.now())
    user_id = Column(String(28), ForeignKey('users.id', ondelete='CASCADE'))

    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat")


class Message(Base):
    __tablename__ = 'messages'
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=func.gen_random_uuid())
    chat_id = Column(UUID(as_uuid=True), ForeignKey(
        'chats.id', ondelete='CASCADE'))
    user_id = Column(String(28), ForeignKey('users.id', ondelete='CASCADE'))
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())

    chat = relationship("Chat", back_populates="messages")
    user = relationship("User")


class ImageMetadata(Base):
    __tablename__ = 'image_metadata'
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=func.gen_random_uuid())
    filename = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    content_type = Column(String(50))
    uploaded_at = Column(DateTime, default=func.now())
    size_bytes = Column(BigInteger)
    user_id = Column(String(28), ForeignKey('users.id', ondelete='CASCADE'))

    user = relationship("User", back_populates="images")
