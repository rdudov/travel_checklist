from typing import List, Dict, Any, Optional
from .weather import WeatherService
from .llm_client import LLMClient
import logging
import os

logger = logging.getLogger(__name__)

class ChecklistGenerator:
    """Service for generating checklists based on various parameters"""
    
    def __init__(self):
        self.weather_service = WeatherService()
        self.llm_client = LLMClient()
        
    async def generate_travel_checklist(self, 
                                      destination: str, 
                                      purpose: str, 
                                      duration: int, 
                                      start_date: Optional[str] = None,
                                      weather_info: Optional[Dict] = None,
                                      user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate a travel checklist based on destination, duration, purpose and other factors
        
        Args:
            destination: Place of travel
            purpose: Purpose of travel (business, beach, active, etc.)
            duration: Duration in days
            start_date: Start date in DD.MM.YYYY format (optional)
            weather_info: Weather forecast information (optional, will be fetched if not provided)
            user_id: User ID for personalization based on previous lists (optional)
        
        Returns:
            Dictionary with checklist data
        """
        logger.info(f"Generating travel checklist for {destination}, purpose: {purpose}, duration: {duration} days")
        
        # Get weather forecast if not provided
        if not weather_info:
            try:
                logger.info(f"Fetching weather forecast for {destination}")
                weather_info = await self.weather_service.get_weather_forecast(destination)
                logger.info("Successfully fetched weather forecast")
            except Exception as e:
                logger.error(f"Error getting weather forecast: {str(e)}")
                weather_info = {}
        
        # Try to get previous user lists for personalization
        previous_lists = []
        if user_id:
            try:
                logger.info(f"Fetching previous checklists for user {user_id}")
                from models.checklist import User, Checklist
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
                
                # Create a temporary database session
                engine = create_engine(os.getenv('DATABASE_URL'))
                Session = sessionmaker(bind=engine)
                session = Session()
                
                # Get user's previous lists
                user = session.query(User).filter_by(telegram_id=user_id).first()
                if user:
                    # Get up to 3 most recent checklists for this user
                    checklists = session.query(Checklist).filter_by(owner_id=user.id).order_by(Checklist.created_at.desc()).limit(3).all()
                    logger.info(f"Found {len(checklists)} previous checklists for user")
                    
                    for checklist in checklists:
                        if checklist.trip_metadata:
                            # Convert database checklist to format needed for LLM
                            items_by_category = {}
                            for item in checklist.items:
                                category = item.category or "Прочее"
                                if category not in items_by_category:
                                    items_by_category[category] = []
                                items_by_category[category].append(item.title)
                            
                            previous_lists.append({
                                'destination': checklist.trip_metadata.get('destination', ''),
                                'purpose': checklist.trip_metadata.get('trip_type', ''),
                                'duration': checklist.trip_metadata.get('duration', 0),
                                'items': items_by_category
                            })
                
                session.close()
                logger.info(f"Processed {len(previous_lists)} previous checklists for personalization")
            except Exception as e:
                logger.error(f"Error getting previous user lists: {str(e)}")
        
        # Try to generate checklist with LLM first
        use_llm = True
        llm_error = None
        
        if not os.getenv("OPENAI_API_KEY"):
            logger.warning("OpenAI API key not set, skipping LLM generation")
            use_llm = False
        
        if use_llm:
            try:
                logger.info("Attempting to generate checklist with LLM")
                llm_result = await self.llm_client.generate_checklist(
                    destination=destination,
                    purpose=purpose,
                    duration=duration,
                    start_date=start_date or "",
                    weather_info=weather_info,
                    previous_lists=previous_lists
                )
                
                if "error" in llm_result:
                    llm_error = llm_result["error"]
                    logger.warning(f"LLM generation returned error: {llm_error}")
                    use_llm = False
                else:
                    logger.info("Successfully generated checklist with LLM")
                    return {
                        "destination": destination,
                        "duration": duration,
                        "purpose": purpose,
                        "categories": llm_result.get("categories", {}),
                        "generated_by": "llm"
                    }
            except Exception as e:
                llm_error = str(e)
                logger.error(f"Error generating checklist with LLM: {llm_error}")
                use_llm = False
        
        # Fallback to rule-based generation if LLM fails or is not available
        if not use_llm:
            logger.info(f"Falling back to rule-based checklist generation (reason: {llm_error or 'API key not set'})")
            
            # Get weather-based items
            try:
                logger.info("Getting weather-based packing suggestions")
                weather_items = []
                if weather_info:
                    weather_items = self.weather_service.get_packing_suggestions(weather_info)
                    logger.info(f"Got {len(weather_items)} weather-based items")
            except Exception as e:
                logger.error(f"Error getting weather suggestions: {str(e)}")
                weather_items = self._get_basic_travel_items()
                logger.info("Using basic travel items as fallback")
            
            # Get purpose-specific items
            purpose_items = self._get_purpose_specific_items(purpose)
            logger.info(f"Got {len(purpose_items)} purpose-specific items for '{purpose}'")
            
            # Get duration-specific items
            duration_items = self._get_duration_specific_items(duration)
            logger.info(f"Got {len(duration_items)} duration-specific items")
            
            # Combine all items and categorize them
            all_items = set(weather_items + purpose_items + duration_items)
            logger.info(f"Combined {len(all_items)} unique items")
            
            categories = self._categorize_items(all_items)
            logger.info(f"Categorized items into {len(categories)} categories")
            
            return {
                "destination": destination,
                "duration": duration,
                "purpose": purpose,
                "categories": categories,
                "generated_by": "rules",
                "llm_error": llm_error
            }
    
    def _get_basic_travel_items(self) -> List[str]:
        """Get basic travel items that are needed regardless of weather"""
        return [
            "Паспорт",
            "Деньги",
            "Банковские карты",
            "Телефон",
            "Зарядное устройство",
            "Наушники",
            "Зубная щетка и паста",
            "Расческа",
            "Дезодорант",
            "Нижнее белье",
            "Носки",
            "Пижама"
        ]
    
    def _get_purpose_specific_items(self, purpose: str) -> List[str]:
        """Get items specific to travel purpose"""
        purpose_items = {
            "business": [
                "Ноутбук",
                "Деловой костюм",
                "Визитки",
                "Блокнот и ручка",
                "Портфель/сумка для ноутбука"
            ],
            "beach": [
                "Купальник/плавки",
                "Пляжное полотенце",
                "Солнцезащитный крем",
                "Солнцезащитные очки",
                "Шлепанцы",
                "Пляжная сумка"
            ],
            "active": [
                "Треккинговая обувь",
                "Рюкзак",
                "Фляжка для воды",
                "Компас",
                "Карта местности",
                "Походная аптечка",
                "Фонарик"
            ],
            "other": [
                "Удобная обувь для прогулок",
                "Фотоаппарат",
                "Путеводитель",
                "Легкий рюкзак",
                "Зонт"
            ]
        }
        return purpose_items.get(purpose.lower(), [])
    
    def _get_duration_specific_items(self, duration: int) -> List[str]:
        """Get items specific to travel duration"""
        items = []
        
        if duration > 7:
            items.extend([
                "Средства для стирки",
                "Запасные очки/линзы",
                "Дополнительный комплект обуви"
            ])
        
        if duration > 14:
            items.extend([
                "Швейный набор",
                "Универсальное зарядное устройство",
                "Запасной телефон"
            ])
        
        return items
    
    def _categorize_items(self, items: set) -> Dict[str, List[str]]:
        """Categorize items into logical groups"""
        categories = {
            "Документы и деньги": [],
            "Одежда": [],
            "Электроника": [],
            "Гигиена": [],
            "Аксессуары": [],
            "Прочее": []
        }
        
        # Keywords for categorization
        categorization_rules = {
            "Документы и деньги": ["паспорт", "виза", "деньги", "карты", "документы"],
            "Одежда": ["куртка", "брюки", "носки", "белье", "обувь", "костюм", "шапка", "одежда"],
            "Электроника": ["телефон", "ноутбук", "зарядное", "наушники", "фотоаппарат"],
            "Гигиена": ["зубная", "расческа", "дезодорант", "шампунь", "полотенце", "гигиен"],
            "Аксессуары": ["очки", "зонт", "сумка", "рюкзак", "ремень"]
        }
        
        for item in items:
            item_lower = item.lower()
            categorized = False
            
            for category, keywords in categorization_rules.items():
                if any(keyword in item_lower for keyword in keywords):
                    categories[category].append(item)
                    categorized = True
                    break
            
            if not categorized:
                categories["Прочее"].append(item)
        
        # Sort items in each category
        for category in categories:
            categories[category].sort()
        
        # Remove empty categories
        return {k: v for k, v in categories.items() if v}
    
    def generate_shopping_list(self, recipe: str = None) -> List[str]:
        """Generate a shopping list, optionally based on a recipe"""
        # Basic implementation - to be expanded
        basic_items = [
            "Хлеб",
            "Молоко",
            "Яйца",
            "Фрукты",
            "Овощи"
        ]
        return basic_items
    
    def generate_repair_checklist(self, repair_type: str) -> List[str]:
        """Generate a repair checklist based on type"""
        # Basic implementation - to be expanded
        basic_tools = [
            "Отвертка",
            "Молоток",
            "Плоскогубцы",
            "Изолента",
            "Перчатки"
        ]
        return basic_tools 