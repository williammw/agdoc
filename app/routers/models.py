from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)


class ImageMetadata(Base):
    __tablename__ = 'image_metadata'
    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    content_type = Column(String(50))
    uploaded_at = Column(DateTime, default=func.now())
    size_bytes = Column(BigInteger)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))

    user = relationship("User", back_populates="images")


User.images = relationship(
    "ImageMetadata", order_by=ImageMetadata.id, back_populates="user")
