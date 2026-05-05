from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import enum

Base = declarative_base()

class PetStage(enum.Enum):
    EGG = "egg"
    BABY = "baby"
    TEEN = "teen"
    ADULT = "adult"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    teams = relationship("TeamMember", back_populates="user")
    actions = relationship("UserAction", back_populates="user")

class Team(Base):
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    pet_name = Column(String, default="Серунчик")
    pet_stage = Column(SQLEnum(PetStage), default=PetStage.EGG)
    pet_type = Column(String, default="rooster")
    progress = Column(Integer, default=0)  # 0-100%
    
    # Mechanics
    last_updated = Column(DateTime, default=datetime.utcnow)
    resuscitation_count = Column(Integer, default=0)
    is_dead = Column(Boolean, default=False)
    
    # Pet stats (0-100)
    hunger = Column(Integer, default=50)  # Higher is better (fed)
    energy = Column(Integer, default=50)
    mood = Column(Integer, default=50)
    
    members = relationship("TeamMember", back_populates="team")
    missions = relationship("Mission", back_populates="team")
    actions = relationship("UserAction", back_populates="team")

class TeamMember(Base):
    __tablename__ = "team_members"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    is_owner = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    # Action points logic
    action_points = Column(Integer, default=5)
    last_ap_reset = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="teams")
    team = relationship("Team", back_populates="members")

class Mission(Base):
    __tablename__ = "missions"
    
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    description = Column(String, nullable=False)
    target_count = Column(Integer, nullable=False)
    current_count = Column(Integer, default=0)
    action_type = Column(String, nullable=False)  # feed, play, rest
    date = Column(DateTime, default=datetime.utcnow)
    completed = Column(Boolean, default=False)
    
    team = relationship("Team", back_populates="missions")

class UserAction(Base):
    __tablename__ = "user_actions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    action_type = Column(String, nullable=False)  # feed, play, rest
    performed_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="actions")
    team = relationship("Team", back_populates="actions")

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./slowdown3.db")

# If using Postgres from Railway, we need to adjust connection args.
# Postgres doesn't need 'check_same_thread', SQLite does.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Handle the postgres:// to postgresql:// deprecation in SQLAlchemy
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
