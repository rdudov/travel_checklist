import os
from datetime import datetime, timedelta
import aiohttp
from typing import Dict, Any, List

class WeatherService:
    """Service for getting weather information"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENWEATHER_API_KEY')
        self.base_url = "http://api.openweathermap.org/data/2.5"
        
    async def get_weather_forecast(self, city: str, days: int = 7) -> Dict[str, Any]:
        """Get weather forecast for specified city"""
        async with aiohttp.ClientSession() as session:
            # First, get city coordinates
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct"
            params = {
                "q": city,
                "limit": 1,
                "appid": self.api_key
            }
            
            async with session.get(geo_url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"Failed to get city coordinates: {await response.text()}")
                
                locations = await response.json()
                if not locations:
                    raise Exception(f"City not found: {city}")
                
                location = locations[0]
                lat, lon = location['lat'], location['lon']
            
            # Now get weather forecast
            forecast_url = f"{self.base_url}/forecast"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric"
            }
            
            async with session.get(forecast_url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"Failed to get weather forecast: {await response.text()}")
                
                data = await response.json()
                return self._process_forecast(data, days)
    
    def _process_forecast(self, data: Dict[str, Any], days: int) -> Dict[str, Any]:
        """Process weather forecast data"""
        processed = {
            "city": data['city']['name'],
            "country": data['city']['country'],
            "forecast": []
        }
        
        # Group forecast by day
        day_forecasts: Dict[str, List[Dict]] = {}
        for item in data['list']:
            dt = datetime.fromtimestamp(item['dt'])
            date_key = dt.date().isoformat()
            
            if date_key not in day_forecasts:
                day_forecasts[date_key] = []
            
            day_forecasts[date_key].append({
                "temp": item['main']['temp'],
                "feels_like": item['main']['feels_like'],
                "humidity": item['main']['humidity'],
                "description": item['weather'][0]['description'],
                "wind_speed": item['wind']['speed']
            })
        
        # Calculate daily averages
        for date_key, forecasts in list(day_forecasts.items())[:days]:
            avg_temp = sum(f['temp'] for f in forecasts) / len(forecasts)
            avg_feels_like = sum(f['feels_like'] for f in forecasts) / len(forecasts)
            avg_humidity = sum(f['humidity'] for f in forecasts) / len(forecasts)
            
            processed['forecast'].append({
                "date": date_key,
                "avg_temp": round(avg_temp, 1),
                "avg_feels_like": round(avg_feels_like, 1),
                "avg_humidity": round(avg_humidity, 1),
                "descriptions": list(set(f['description'] for f in forecasts))
            })
        
        return processed
    
    def get_packing_suggestions(self, forecast: Dict[str, Any]) -> List[str]:
        """Get packing suggestions based on weather forecast"""
        suggestions = set()
        
        # Analyze temperature ranges
        min_temp = min(day['avg_temp'] for day in forecast['forecast'])
        max_temp = max(day['avg_temp'] for day in forecast['forecast'])
        
        # Basic items everyone needs
        suggestions.update([
            "Документы",
            "Зарядные устройства",
            "Туалетные принадлежности",
            "Аптечка"
        ])
        
        # Temperature based suggestions
        if min_temp < 10:
            suggestions.update([
                "Теплая куртка",
                "Шапка",
                "Перчатки",
                "Шарф",
                "Теплые носки"
            ])
        elif min_temp < 20:
            suggestions.update([
                "Легкая куртка или кардиган",
                "Длинные брюки",
                "Кофта или свитер"
            ])
        
        if max_temp > 25:
            suggestions.update([
                "Солнцезащитный крем",
                "Солнцезащитные очки",
                "Головной убор от солнца",
                "Легкая одежда",
                "Шорты",
                "Футболки"
            ])
        
        # Rain related items
        if any('rain' in desc.lower() for day in forecast['forecast'] for desc in day['descriptions']):
            suggestions.update([
                "Зонт",
                "Дождевик",
                "Водонепроницаемая обувь"
            ])
        
        return sorted(list(suggestions)) 