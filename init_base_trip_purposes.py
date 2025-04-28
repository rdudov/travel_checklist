import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.checklist import TripPurpose, Base

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_trip_purposes():
    """Initialize base trip purposes in the database"""
    
    # Connect to database
    logger.info("Connecting to database")
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Create tables if they don't exist
    Base.metadata.create_all(engine)
    
    # Define base trip purposes
    base_purposes = [
        {"name": "beach", "description": "Пляжный отдых"},
        {"name": "business", "description": "Бизнес-командировка"},
        {"name": "active", "description": "Активный отдых"}, 
        {"name": "sightseeing", "description": "Осмотр достопримечательностей"},
        {"name": "hiking", "description": "Пеший поход"},
        {"name": "cruise", "description": "Морская прогулка/круиз"},
        {"name": "cultural", "description": "Культурная поездка (музеи, выставки, концерты)"},
        {"name": "wellness", "description": "Оздоровительный отдых"},
        {"name": "education", "description": "Образовательная поездка"},
        {"name": "sports", "description": "Спортивное мероприятие"},
        {"name": "religious", "description": "Паломничество/религиозная поездка"},
        {"name": "family", "description": "Семейный отдых"},
        {"name": "medical", "description": "Медицинская поездка"},
        {"name": "other", "description": "Другое"}
    ]
    
    # Add purposes to database if they don't exist
    added_count = 0
    for purpose in base_purposes:
        exists = session.query(TripPurpose).filter_by(name=purpose["name"]).first()
        if not exists:
            session.add(TripPurpose(
                name=purpose["name"],
                description=purpose["description"],
                is_base=True
            ))
            added_count += 1
    
    # Commit changes
    if added_count > 0:
        session.commit()
        logger.info(f"Added {added_count} new trip purposes to database")
    else:
        logger.info("No new trip purposes added (all already exist)")
    
    session.close()
    
if __name__ == "__main__":
    init_trip_purposes() 