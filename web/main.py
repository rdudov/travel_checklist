from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from models.base import SessionLocal
from models.checklist import Checklist

app = FastAPI(title="Travel Checklist Web Interface")

# Setup templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Mount static files
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

@app.get("/checklist/{checklist_id}", response_class=HTMLResponse)
async def view_checklist(request: Request, checklist_id: int):
    """Display a checklist"""
    db = SessionLocal()
    try:
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
        
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
        
        return templates.TemplateResponse(
            "checklist.html",
            {
                "request": request,
                "title": checklist.title,
                "destination": checklist.metadata.get("destination", "Не указано"),
                "duration": checklist.metadata.get("duration", "Не указано"),
                "purpose": checklist.metadata.get("purpose", "Не указано"),
                "weather": checklist.metadata.get("weather", None),
                "categories": categories,
                "total_items": total_items,
                "share_url": share_url
            }
        )
    finally:
        db.close()

@app.get("/share/{checklist_id}")
async def share_checklist(checklist_id: int):
    """Get a shareable version of the checklist"""
    db = SessionLocal()
    try:
        checklist = db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
        
        # Create a new checklist based on the shared one
        return {
            "title": checklist.title,
            "type": checklist.type,
            "metadata": checklist.metadata,
            "items": [
                {
                    "title": item.title,
                    "category": item.category,
                    "description": item.description
                }
                for item in checklist.items
            ]
        }
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 