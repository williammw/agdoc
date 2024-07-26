# models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text, Enum, CheckConstraint
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

    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    auth_provider = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    full_name = Column(String)
    bio = Column(String)
    avatar_url = Column(String)
    phone_number = Column(String)
    dob = Column(String)
    status = Column(String, default='available')
    cover_image = Column(String)

    __table_args__ = (
        CheckConstraint(
            status.in_(['available', 'busy', 'at_restaurant',
                       'cooking', 'food_coma']),
            name='check_status'
        ),
    )


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
