import os
from datetime import datetime, timedelta
import aiohttp
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Создаем директорию для логов погоды, если ее нет
os.makedirs("weather_logs", exist_ok=True)

class WeatherService:
    """Service for getting weather information"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENWEATHER_API_KEY')
        self.base_url = "http://api.openweathermap.org/data/2.5"
    
    def _log_to_file(self, prefix: str, content: Dict):
        """Log request or response to a file for debugging"""
        try:
            timestamp = int(datetime.now().timestamp())
            filename = f"weather_logs/{prefix}_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            logger.debug(f"Logged weather {prefix} to {filename}")
        except Exception as e:
            logger.error(f"Error logging weather {prefix} to file: {str(e)}")
        
    async def get_weather_forecast(self, city: str, days: int = 7) -> Dict[str, Any]:
        """Get weather forecast for specified city"""
        logger.info(f"Getting weather forecast for {city} for {days} days")
        
        try:
            async with aiohttp.ClientSession() as session:
                # First, get city coordinates
                geo_url = f"http://api.openweathermap.org/geo/1.0/direct"
                params = {
                    "q": city,
                    "limit": 1,
                    "appid": self.api_key
                }
                
                # Логируем запрос
                self._log_to_file("geo_request", {"url": geo_url, "params": params})
                
                async with session.get(geo_url, params=params) as response:
                    # Логируем ответ
                    geo_response_text = await response.text()
                    self._log_to_file("geo_response", {"status": response.status, "body": json.loads(geo_response_text) if geo_response_text else {}})
                    
                    if response.status != 200:
                        logger.error(f"Failed to get city coordinates: Status {response.status} - {geo_response_text}")
                        raise Exception(f"Failed to get city coordinates: {geo_response_text}")
                    
                    locations = json.loads(geo_response_text)
                    if not locations:
                        logger.error(f"City not found: {city}")
                        raise Exception(f"City not found: {city}")
                    
                    location = locations[0]
                    lat, lon = location['lat'], location['lon']
                    logger.info(f"Found coordinates for {city}: lat={lat}, lon={lon}")
                
                # Now get weather forecast
                forecast_url = f"{self.base_url}/forecast"
                params = {
                    "lat": lat,
                    "lon": lon,
                    "appid": self.api_key,
                    "units": "metric"
                }
                
                # Логируем запрос
                self._log_to_file("forecast_request", {"url": forecast_url, "params": params})
                
                async with session.get(forecast_url, params=params) as response:
                    # Логируем ответ
                    forecast_response_text = await response.text()
                    self._log_to_file("forecast_response", {"status": response.status, "body": json.loads(forecast_response_text) if forecast_response_text else {}})
                    
                    if response.status != 200:
                        logger.error(f"Failed to get weather forecast: Status {response.status} - {forecast_response_text}")
                        raise Exception(f"Failed to get weather forecast: {forecast_response_text}")
                    
                    data = json.loads(forecast_response_text)
                    processed_data = self._process_forecast(data, days)
                    
                    # Логируем обработанные данные
                    self._log_to_file("processed_forecast", processed_data)
                    
                    return processed_data
        except Exception as e:
            logger.error(f"Error getting weather forecast: {str(e)}")
            # Возвращаем пустую структуру, чтобы избежать ошибок
            return {
                "city": city,
                "country": "",
                "daily": []  # Пустой список прогнозов
            }
    
    def _process_forecast(self, data: Dict[str, Any], days: int) -> Dict[str, Any]:
        """Process weather forecast data"""
        processed = {
            "city": data['city']['name'],
            "country": data['city']['country'],
            "location": f"{data['city']['name']}, {data['city']['country']}",
            "daily": []  # Изменено с 'forecast' на 'daily'
        }
        
        # Group forecast by day
        day_forecasts: Dict[str, List[Dict]] = {}
        for item in data['list']:
            dt = datetime.fromtimestamp(item['dt'])
            date_key = dt.date().isoformat()
            date_formatted = dt.strftime("%d.%m.%Y")  # Добавляем отформатированную дату
            
            if date_key not in day_forecasts:
                day_forecasts[date_key] = {
                    "date": date_formatted,  # Добавляем отформатированную дату
                    "forecasts": [],
                    "date_iso": date_key
                }
            
            day_forecasts[date_key]["forecasts"].append({
                "temp": item['main']['temp'],
                "feels_like": item['main']['feels_like'],
                "humidity": item['main']['humidity'],
                "description": item['weather'][0]['description'],
                "wind_speed": item['wind']['speed'],
                "precipitation": item.get('rain', {}).get('3h', 0) + item.get('snow', {}).get('3h', 0)  # Добавляем осадки
            })
        
        # Calculate daily averages
        for date_key, day_data in sorted(day_forecasts.items())[:days or 1]:  # Если days = 0, берем хотя бы 1 день
            forecasts = day_data["forecasts"]
            
            # Рассчитываем минимальную и максимальную температуру
            temps = [f['temp'] for f in forecasts]
            temp_min = min(temps)
            temp_max = max(temps)
            
            # Среднее ощущаемой температуры
            avg_feels_like = sum(f['feels_like'] for f in forecasts) / len(forecasts)
            
            # Средняя влажность
            avg_humidity = sum(f['humidity'] for f in forecasts) / len(forecasts)
            
            # Максимальная скорость ветра
            wind_speeds = [f['wind_speed'] for f in forecasts]
            max_wind = max(wind_speeds) if wind_speeds else 0
            
            # Осадки
            precipitation = sum(f.get('precipitation', 0) for f in forecasts)
            
            processed['daily'].append({
                "date": day_data["date"],  # Используем отформатированную дату
                "date_iso": date_key,
                "temp_min": round(temp_min, 1),
                "temp_max": round(temp_max, 1),
                "feels_like": round(avg_feels_like, 1),
                "humidity": round(avg_humidity, 1),
                "wind_speed": round(max_wind, 1),
                "precipitation": round(precipitation, 1),
                "description": ", ".join(set(f['description'] for f in forecasts))
            })
        
        return processed
    
    def get_packing_suggestions(self, forecast: Dict[str, Any]) -> List[str]:
        """Get packing suggestions based on weather forecast"""
        suggestions = set()
        
        # Проверяем наличие данных
        forecast_data = forecast.get('daily') or forecast.get('forecast', [])
        if not forecast_data:
            logger.warning("No forecast data for packing suggestions")
            return ["Документы", "Зарядные устройства", "Туалетные принадлежности", "Аптечка"]
        
        try:
            # Analyze temperature ranges
            if any('temp_min' in day for day in forecast_data):
                min_temp = min(day.get('temp_min', 999) for day in forecast_data)
                max_temp = max(day.get('temp_max', -999) for day in forecast_data)
            else:
                # Если нет данных о температуре
                min_temp = 15
                max_temp = 25
                logger.warning("No temperature data in forecast, using defaults")
            
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
            has_rain = False
            for day in forecast_data:
                desc = day.get('description', '').lower()
                if 'rain' in desc or 'дождь' in desc:
                    has_rain = True
                    break
                
                if day.get('precipitation', 0) > 0.5:
                    has_rain = True
                    break
            
            if has_rain:
                suggestions.update([
                    "Зонт",
                    "Дождевик",
                    "Водонепроницаемая обувь"
                ])
            
            return sorted(list(suggestions))
        except Exception as e:
            logger.error(f"Error generating packing suggestions: {str(e)}")
            return ["Документы", "Зарядные устройства", "Туалетные принадлежности", "Аптечка"] 