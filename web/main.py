from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
import sys
from typing import Optional

from models.base import SessionLocal
from models.checklist import Checklist, ChecklistItem, User
from sqlalchemy.orm import Session

app = FastAPI(title="Travel Checklist Web Interface")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("web_server.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("web_server")

# Setup templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Mount static files
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/checklist/{checklist_id}", response_class=HTMLResponse)
async def view_checklist(request: Request, checklist_id: int, db: Session = Depends(get_db)):
    """Display a checklist"""
    logger.info(f"Request for checklist ID: {checklist_id}")
    
    try:
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            logger.warning(f"Checklist ID {checklist_id} not found")
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        logger.info(f"Found checklist: {checklist.title}")
        
        # Get all items grouped by category
        categories = {}
        for item in checklist.items:
            if item.category not in categories:
                categories[item.category] = []
            categories[item.category].append(item.title)
        
        # Sort items in each category
        for category in categories:
            categories[category].sort()
        
        # Calculate total items
        total_items = sum(len(items) for items in categories.values())
        
        # Generate share URL
        share_url = f"/share/{checklist_id}"
        
        # Access trip_metadata instead of metadata and handle the case when it's None
        trip_metadata = checklist.trip_metadata or {}
        
        # Format weather information in a user-friendly way
        weather_info = ""
        if 'aggregated_weather' in trip_metadata and trip_metadata['aggregated_weather']:
            weather = trip_metadata['aggregated_weather']
            
            # Day temperature range
            if weather.get('day_temp_range'):
                weather_info += f"Днем: от {weather['day_temp_range'][0]}°C до {weather['day_temp_range'][1]}°C. "
                
            # Night temperature range
            if weather.get('night_temp_range'):
                weather_info += f"Ночью: от {weather['night_temp_range'][0]}°C до {weather['night_temp_range'][1]}°C. "
                
            # Weather description
            if weather.get('descriptions'):
                weather_info += f"Погода: {', '.join(weather['descriptions'])}. "
                
            # Wind information
            if weather.get('avg_wind'):
                weather_info += f"Ветер: в среднем {weather['avg_wind']} м/с"
                if weather.get('max_wind'):
                    weather_info += f", максимум до {weather['max_wind']} м/с. "
                else:
                    weather_info += ". "
                
            # Precipitation information
            if weather.get('avg_precip'):
                weather_info += f"Осадки: в среднем {weather['avg_precip']} мм/день"
                if weather.get('total_precip'):
                    weather_info += f", всего до {weather['total_precip']} мм за период."
                else:
                    weather_info += "."
        elif 'weather' in trip_metadata and trip_metadata['weather']:
            # Use raw weather data if aggregated is not available
            weather_info = "Подробная информация о погоде доступна в боте."
        
        return templates.TemplateResponse(
            "checklist.html",
            {
                "request": request,
                "title": checklist.title,
                "destination": trip_metadata.get("destination", "Не указано"),
                "duration": trip_metadata.get("duration", "Не указано"),
                "purpose": trip_metadata.get("original_purpose", trip_metadata.get("trip_type", "Не указано")),
                "purpose_category": trip_metadata.get("trip_type", "Не указано"),
                "weather": weather_info,
                "categories": categories,
                "total_items": total_items,
                "share_url": share_url
            }
        )
    except Exception as e:
        logger.error(f"Error rendering checklist ID {checklist_id}: {str(e)}")
        raise

@app.get("/edit/{checklist_id}", response_class=HTMLResponse)
async def edit_checklist(request: Request, checklist_id: int, 
                        notification: Optional[str] = None,
                        notification_type: Optional[str] = None,
                        db: Session = Depends(get_db)):
    """Edit a checklist"""
    logger.info(f"Request to edit checklist ID: {checklist_id}")
    
    try:
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            logger.warning(f"Checklist ID {checklist_id} not found")
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        logger.info(f"Editing checklist: {checklist.title}")
        
        # Get all items grouped by category
        categories = {}
        for item in sorted(checklist.items, key=lambda x: x.order or 0):
            category = item.category or "Прочее"
            if category not in categories:
                categories[category] = []
            categories[category].append(item)
        
        # Access trip_metadata
        trip_metadata = checklist.trip_metadata or {}
        
        # Format weather information in a user-friendly way
        weather_info = ""
        if 'aggregated_weather' in trip_metadata and trip_metadata['aggregated_weather']:
            weather = trip_metadata['aggregated_weather']
            
            # Simplify weather information for edit view
            if weather.get('day_temp_range'):
                weather_info += f"Днем: от {weather['day_temp_range'][0]}°C до {weather['day_temp_range'][1]}°C. "
                
            if weather.get('descriptions'):
                weather_info += f"Погода: {', '.join(weather['descriptions'])}."
        
        return templates.TemplateResponse(
            "edit_checklist.html",
            {
                "request": request,
                "title": checklist.title,
                "checklist_id": checklist_id,
                "destination": trip_metadata.get("destination", "Не указано"),
                "duration": trip_metadata.get("duration", "Не указано"),
                "purpose": trip_metadata.get("original_purpose", trip_metadata.get("trip_type", "Не указано")),
                "purpose_category": trip_metadata.get("trip_type", "Не указано"),
                "weather": weather_info,
                "categories": categories,
                "notification": notification,
                "notification_type": notification_type
            }
        )
    except Exception as e:
        logger.error(f"Error editing checklist ID {checklist_id}: {str(e)}")
        raise

@app.post("/edit/{checklist_id}/add-item")
async def add_item(checklist_id: int, 
                  item_name: str = Form(...), 
                  category: str = Form(...),
                  db: Session = Depends(get_db)):
    """Add an item to a checklist"""
    logger.info(f"Adding item to checklist ID {checklist_id}: {item_name} in category {category}")
    
    try:
        # Get the checklist
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        # Get the current max order in the category
        max_order = db.query(ChecklistItem).filter_by(
            checklist_id=checklist_id,
            category=category
        ).count()
        
        # Create the new item
        new_item = ChecklistItem(
            title=item_name,
            category=category,
            checklist_id=checklist_id,
            order=max_order + 1
        )
        db.add(new_item)
        db.commit()
        
        logger.info(f"Added item {new_item.id} to checklist {checklist_id}")
        
        # Redirect back to the edit page with success message
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Элемент добавлен успешно&notification_type=success",
            status_code=303  # POST redirect
        )
    except Exception as e:
        logger.error(f"Error adding item to checklist {checklist_id}: {str(e)}")
        db.rollback()
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Ошибка при добавлении элемента&notification_type=error",
            status_code=303
        )

@app.post("/edit/{checklist_id}/delete-item")
async def delete_item(checklist_id: int, 
                     item_id: int = Form(...),
                     db: Session = Depends(get_db)):
    """Delete an item from a checklist"""
    logger.info(f"Deleting item {item_id} from checklist {checklist_id}")
    
    try:
        # Get the item
        item = db.query(ChecklistItem).filter_by(id=item_id, checklist_id=checklist_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Store item info for logging
        item_title = item.title
        category = item.category
        
        # Delete the item
        db.delete(item)
        db.commit()
        
        logger.info(f"Deleted item {item_id} ({item_title}) from checklist {checklist_id}")
        
        # Redirect back to the edit page with success message
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Элемент удален успешно&notification_type=success",
            status_code=303  # POST redirect
        )
    except Exception as e:
        logger.error(f"Error deleting item {item_id} from checklist {checklist_id}: {str(e)}")
        db.rollback()
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Ошибка при удалении элемента&notification_type=error",
            status_code=303
        )

@app.post("/edit/{checklist_id}/add-category")
async def add_category(checklist_id: int, 
                      category_name: str = Form(...),
                      db: Session = Depends(get_db)):
    """Add a new category to a checklist"""
    logger.info(f"Adding category {category_name} to checklist {checklist_id}")
    
    try:
        # Get the checklist
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        # Check if category already exists (case insensitive)
        existing_categories = set(item.category.lower() for item in checklist.items if item.category)
        if category_name.lower() in existing_categories:
            return RedirectResponse(
                url=f"/edit/{checklist_id}?notification=Категория уже существует&notification_type=error",
                status_code=303
            )
        
        # Create a dummy item in the new category to establish it
        # (Categories only exist through items in our model)
        dummy_item = ChecklistItem(
            title="✨ Новый элемент",
            category=category_name,
            checklist_id=checklist_id,
            order=1
        )
        db.add(dummy_item)
        db.commit()
        
        logger.info(f"Added category {category_name} to checklist {checklist_id}")
        
        # Redirect back to the edit page with success message
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Категория добавлена успешно&notification_type=success",
            status_code=303  # POST redirect
        )
    except Exception as e:
        logger.error(f"Error adding category to checklist {checklist_id}: {str(e)}")
        db.rollback()
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Ошибка при добавлении категории&notification_type=error",
            status_code=303
        )

@app.post("/edit/{checklist_id}/delete-category")
async def delete_category(checklist_id: int, 
                         category_name: str = Form(...),
                         db: Session = Depends(get_db)):
    """Delete a category and all its items from a checklist"""
    logger.info(f"Deleting category {category_name} from checklist {checklist_id}")
    
    try:
        # Get all items in the category
        items = db.query(ChecklistItem).filter_by(
            checklist_id=checklist_id,
            category=category_name
        ).all()
        
        if not items:
            return RedirectResponse(
                url=f"/edit/{checklist_id}?notification=Категория не найдена&notification_type=error",
                status_code=303
            )
        
        # Delete all items in the category
        for item in items:
            db.delete(item)
        
        db.commit()
        
        logger.info(f"Deleted category {category_name} with {len(items)} items from checklist {checklist_id}")
        
        # Redirect back to the edit page with success message
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Категория удалена успешно&notification_type=success",
            status_code=303  # POST redirect
        )
    except Exception as e:
        logger.error(f"Error deleting category from checklist {checklist_id}: {str(e)}")
        db.rollback()
        return RedirectResponse(
            url=f"/edit/{checklist_id}?notification=Ошибка при удалении категории&notification_type=error",
            status_code=303
        )

@app.get("/share/{checklist_id}")
async def share_checklist(checklist_id: int, db: Session = Depends(get_db)):
    """Get a shareable version of the checklist"""
    logger.info(f"Request to share checklist ID: {checklist_id}")
    
    try:
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            logger.warning(f"Checklist ID {checklist_id} not found for sharing")
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        # Create a new checklist based on the shared one
        return {
            "title": checklist.title,
            "type": checklist.type,
            "metadata": checklist.trip_metadata,
            "items": [
                {
                    "title": item.title,
                    "category": item.category,
                    "description": item.description
                }
                for item in checklist.items
            ]
        }
    except Exception as e:
        logger.error(f"Error sharing checklist ID {checklist_id}: {str(e)}")
        raise

@app.on_event("startup")
async def startup_event():
    """Log when the server starts"""
    logger.info("Web server started")

@app.on_event("shutdown")
async def shutdown_event():
    """Log when the server shuts down"""
    logger.info("Web server shutting down")

if __name__ == "__main__":
    import uvicorn
    
    # Also configure uvicorn logging
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = logger.handlers
    
    uvicorn.run(app, host="0.0.0.0", port=8000) 