from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import create_engine
import datetime
import os

# Use DATABASE_URL from environment (Neon/Postgres), fallback to local SQLite for dev.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./personal_monitor.db")

# Render/Heroku sometimes provide "postgres://"; SQLAlchemy needs "postgresql://".
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine_args = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    health_records = relationship("HealthRecord", back_populates="owner", cascade="all, delete-orphan")
    sources = relationship("Source", back_populates="owner", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="owner", cascade="all, delete-orphan")


class HealthRecord(Base):
    __tablename__ = "health_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, default=datetime.date.today)
    height = Column(Float)  # cm
    weight = Column(Float)  # kg
    bp_systolic = Column(Integer, nullable=True)
    bp_diastolic = Column(Integer, nullable=True)

    owner = relationship("User", back_populates="health_records")


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)  # e.g. "Cash", "SBI"
    balance = Column(Float, default=0.0)

    owner = relationship("User", back_populates="sources")
    transactions = relationship("Transaction", back_populates="source", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    source_id = Column(Integer, ForeignKey("sources.id"))
    amount = Column(Float)
    type = Column(String)  # "income" or "expense"
    category = Column(String)  # e.g. "Lunch", "Salary"
    date = Column(DateTime, default=datetime.datetime.utcnow)
    description = Column(String, nullable=True)

    source = relationship("Source", back_populates="transactions")
    owner = relationship("User", back_populates="transactions")


def init_db():
    """Create tables if they don't exist (simple alternative to migrations for dev)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
