from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship

from .base import BaseModel, Base

class User(BaseModel):
    """User model"""
    __tablename__ = "users"

    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String)
    last_name = Column(String, nullable=True)
    
    checklists = relationship("Checklist", back_populates="owner")

class Checklist(BaseModel):
    """Checklist model"""
    __tablename__ = "checklists"

    title = Column(String, index=True)
    description = Column(String, nullable=True)
    type = Column(String, index=True)  # 'travel', 'shopping', 'repair', etc.
    is_template = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    metadata = Column(JSON, nullable=True)  # For travel: destination, weather, duration, etc.
    
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="checklists")
    items = relationship("ChecklistItem", back_populates="checklist")

class ChecklistItem(BaseModel):
    """Checklist item model"""
    __tablename__ = "checklist_items"

    title = Column(String)
    description = Column(String, nullable=True)
    is_completed = Column(Boolean, default=False)
    category = Column(String, nullable=True)
    order = Column(Integer)
    
    checklist_id = Column(Integer, ForeignKey("checklists.id"))
    checklist = relationship("Checklist", back_populates="items") 