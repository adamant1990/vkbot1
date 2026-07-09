from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func
import enum

class Base(DeclarativeBase):
    pass

# Enum для статусов
class TripStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"

class BookingStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    cancelled = "cancelled"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vk_id = Column(Integer, unique=True, index=True, nullable=False)
    first_name = Column(String(50))
    last_name = Column(String(50))
    age = Column(Integer)
    gender = Column(String(10))
    phone = Column(String(20), nullable=True)
    rating = Column(Float, default=None, nullable=True)
    rating_count = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)

    trips = relationship("Trip", back_populates="driver")
    bookings = relationship("Booking", back_populates="passenger")
    subscriptions = relationship("Subscription", back_populates="user")

class Trip(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, autoincrement=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_from = Column(String(100), nullable=False)
    route_to = Column(String(100), nullable=False)
    departure_time = Column(DateTime(timezone=True), nullable=False)
    seats_total = Column(Integer, default=1)
    seats_available = Column(Integer, default=1)
    price = Column(Integer, default=0)
    comment = Column(Text, nullable=True)
    distance = Column(Float, nullable=True)
    status = Column(Enum(TripStatus), default=TripStatus.active)
    publish_on_wall = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    driver = relationship("User", back_populates="trips")
    bookings = relationship("Booking", back_populates="trip")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    passenger_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    rating_given = Column(Boolean, default=False)

    trip = relationship("Trip", back_populates="bookings")
    passenger = relationship("User", back_populates="bookings")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_from = Column(String(100), nullable=False)
    route_to = Column(String(100), nullable=False)
    date = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscriptions")

class Rating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), unique=True, nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    value = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PendingRating(Base):
    """Ожидающие оценки для отправки пользователям"""
    __tablename__ = "pending_ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user_vk_id = Column(Integer, nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    target_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(String(100), nullable=False)
