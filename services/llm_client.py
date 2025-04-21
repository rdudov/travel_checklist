import os
import logging
import json
import aiohttp
import requests
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class LLMClient:
    """Client for interacting with OpenAI API"""
    
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.api_base = "https://api.openai.com/v1/chat/completions"
        
        if not self.api_key:
            logger.warning("OpenAI API key not set. LLM features will not work.")
    
    async def generate_checklist(self, 
                                destination: str, 
                                purpose: str, 
                                duration: int, 
                                start_date: str,
                                weather_info: Dict,
                                previous_lists: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Generate a travel checklist using LLM
        
        Args:
            destination: Place of travel
            purpose: Purpose of travel (business, beach, active, etc.)
            duration: Duration in days
            start_date: Start date in DD.MM.YYYY format
            weather_info: Weather forecast information
            previous_lists: Previous user checklists for personalization
            
        Returns:
            Dictionary with categories and items
        """
        if not self.api_key:
            logger.error("Cannot generate checklist with LLM: API key not set")
            return {"error": "OpenAI API key not configured"}
        
        # Format weather information for the prompt
        weather_text = self._format_weather_info(weather_info)
        
        # Format previous lists for personalization
        previous_lists_text = ""
        if previous_lists and len(previous_lists) > 0:
            previous_lists_text = "Пользователь ранее создавал следующие списки для поездок:\n\n"
            for i, prev_list in enumerate(previous_lists, 1):
                prev_list_text = f"Список {i}:\n"
                prev_list_text += f"- Место: {prev_list.get('destination', 'Неизвестно')}\n"
                prev_list_text += f"- Цель: {prev_list.get('purpose', 'Неизвестно')}\n"
                prev_list_text += f"- Длительность: {prev_list.get('duration', 0)} дней\n"
                
                if 'items' in prev_list and prev_list['items']:
                    prev_list_text += "- Элементы:\n"
                    for category, items in prev_list['items'].items():
                        prev_list_text += f"  * {category}: {', '.join(items)}\n"
                
                previous_lists_text += prev_list_text + "\n"
        
        # Create a prompt for the LLM
        prompt = f"""
        Создай подробный список вещей для путешествия со следующими параметрами:
        
        Место назначения: {destination}
        Цель поездки: {purpose}
        Длительность: {duration} дней
        Дата начала: {start_date}
        
        Погода на период поездки:
        {weather_text}
        
        {previous_lists_text}
        
        Нужно создать практичный и полный список вещей, разбитый по категориям. 
        Включи базовые предметы, а также специфичные для данной поездки с учетом погоды, цели и длительности.
        Если у пользователя были предыдущие поездки, учти его индивидуальные предпочтения.
        
        Верни ответ строго в формате JSON:
        {{
            "categories": {{
                "Категория1": ["Предмет1", "Предмет2", ...],
                "Категория2": ["Предмет1", "Предмет2", ...],
                ...
            }}
        }}
        """
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "Ты - умный помощник для путешествий, который создает подробные списки вещей"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1500
                }
                
                async with session.post(self.api_base, headers=headers, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Error from OpenAI API: {response.status} - {await response.text()}")
                        return {"error": f"OpenAI API error: {response.status}"}
                    
                    response_json = await response.json()
                    response_text = response_json["choices"][0]["message"]["content"]
                    
                    # Parse the JSON from the response
                    try:
                        # The response might have markdown code blocks or other text around the JSON
                        # Try to extract and parse the JSON part
                        json_text = self._extract_json(response_text)
                        result = json.loads(json_text)
                        
                        # Make sure the response has the expected structure
                        if "categories" not in result:
                            return {"categories": {"Общие": ["Паспорт", "Деньги", "Телефон"]}}
                        
                        return result
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse LLM response as JSON: {e}")
                        logger.error(f"Raw response: {response_text}")
                        return {"categories": {"Общие": ["Паспорт", "Деньги", "Телефон"]}}
        
        except Exception as e:
            logger.error(f"Error generating checklist with LLM: {str(e)}")
            return {"categories": {"Общие": ["Паспорт", "Деньги", "Телефон"]}}
    
    def _format_weather_info(self, weather_info: Dict) -> str:
        """Format weather information for the prompt"""
        if not weather_info:
            return "Информация о погоде недоступна."
        
        weather_text = ""
        
        if 'aggregated_weather' in weather_info:
            agg_weather = weather_info['aggregated_weather']
            
            if 'day_temp_range' in agg_weather and agg_weather['day_temp_range']:
                weather_text += f"Температура днем: от {agg_weather['day_temp_range'][0]}°C до {agg_weather['day_temp_range'][1]}°C\n"
                
            if 'night_temp_range' in agg_weather and agg_weather['night_temp_range']:
                weather_text += f"Температура ночью: от {agg_weather['night_temp_range'][0]}°C до {agg_weather['night_temp_range'][1]}°C\n"
                
            if 'descriptions' in agg_weather:
                weather_text += f"Погодные условия: {', '.join(agg_weather['descriptions'])}\n"
                
            if 'avg_wind' in agg_weather:
                weather_text += f"Ветер: в среднем {agg_weather['avg_wind']} м/с"
                if 'max_wind' in agg_weather:
                    weather_text += f", до {agg_weather['max_wind']} м/с"
                weather_text += "\n"
                
            if 'avg_precip' in agg_weather:
                weather_text += f"Осадки: в среднем {agg_weather['avg_precip']} мм/день"
                if 'total_precip' in agg_weather:
                    weather_text += f", всего до {agg_weather['total_precip']} мм за период"
                weather_text += "\n"
                
        elif 'forecast' in weather_info:
            weather_text += "Прогноз по дням:\n"
            for i, day in enumerate(weather_info['forecast']):
                weather_text += f"День {i+1}: "
                if 'day_temp' in day:
                    weather_text += f"Температура днем: {day['day_temp']}°C, "
                if 'night_temp' in day:
                    weather_text += f"Температура ночью: {day['night_temp']}°C, "
                if 'descriptions' in day:
                    weather_text += f"Условия: {', '.join(day['descriptions'])}"
                weather_text += "\n"
        
        return weather_text
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from text that might contain markdown code blocks or other text"""
        # Try to find JSON within code blocks
        if "```json" in text:
            parts = text.split("```json")
            if len(parts) > 1:
                json_part = parts[1].split("```")[0].strip()
                return json_part
        
        # Try to find JSON within code blocks without language specifier
        if "```" in text:
            parts = text.split("```")
            if len(parts) > 1:
                json_part = parts[1].strip()
                return json_part
        
        # Try to find JSON objects
        if "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            return text[start:end]
        
        # Return the whole text if we couldn't extract JSON
        return text 