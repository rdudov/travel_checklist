from typing import List, Dict, Any
from .weather import WeatherService

class ChecklistGenerator:
    """Service for generating checklists based on various parameters"""
    
    def __init__(self):
        self.weather_service = WeatherService()
        
    async def generate_travel_checklist(self, destination: str, duration: int, purpose: str) -> Dict[str, Any]:
        """Generate a travel checklist based on destination, duration and purpose"""
        # Get weather forecast
        try:
            forecast = await self.weather_service.get_weather_forecast(destination)
            weather_items = self.weather_service.get_packing_suggestions(forecast)
        except Exception as e:
            weather_items = self._get_basic_travel_items()
        
        # Get purpose-specific items
        purpose_items = self._get_purpose_specific_items(purpose)
        
        # Get duration-specific items
        duration_items = self._get_duration_specific_items(duration)
        
        # Combine all items and categorize them
        all_items = set(weather_items + purpose_items + duration_items)
        
        return {
            "destination": destination,
            "duration": duration,
            "purpose": purpose,
            "categories": self._categorize_items(all_items)
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
            "hiking": [
                "Треккинговая обувь",
                "Рюкзак",
                "Фляжка для воды",
                "Компас",
                "Карта местности",
                "Походная аптечка",
                "Фонарик"
            ],
            "city": [
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