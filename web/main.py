from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
import sys

from models.base import SessionLocal
from models.checklist import Checklist

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

@app.get("/checklist/{checklist_id}", response_class=HTMLResponse)
async def view_checklist(request: Request, checklist_id: int):
    """Display a checklist"""
    logger.info(f"Request for checklist ID: {checklist_id}")
    db = SessionLocal()
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
        
        return templates.TemplateResponse(
            "checklist.html",
            {
                "request": request,
                "title": checklist.title,
                "destination": trip_metadata.get("destination", "Не указано"),
                "duration": trip_metadata.get("duration", "Не указано"),
                "purpose": trip_metadata.get("trip_type", "Не указано"),
                "weather": trip_metadata.get("weather", None),
                "categories": categories,
                "total_items": total_items,
                "share_url": share_url
            }
        )
    except Exception as e:
        logger.error(f"Error rendering checklist ID {checklist_id}: {str(e)}")
        raise
    finally:
        db.close()

@app.get("/share/{checklist_id}")
async def share_checklist(checklist_id: int):
    """Get a shareable version of the checklist"""
    logger.info(f"Request to share checklist ID: {checklist_id}")
    db = SessionLocal()
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
    finally:
        db.close()

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