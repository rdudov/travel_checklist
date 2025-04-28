import os
import logging
import json
import aiohttp
import requests
import httpx
import re
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import openai
import time

load_dotenv()
logger = logging.getLogger(__name__)

# Create a directory for LLM logs if it doesn't exist
os.makedirs("llm_logs", exist_ok=True)

class LLMClient:
    """Client for interacting with OpenAI API for checklist generation"""
    
    def __init__(self, api_key: str = None, model: str = None):
        # Get API key from environment or parameter
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-3.5-turbo"
        
        # Set up the API client if we have a key
        if self.api_key:
            openai.api_key = self.api_key
            logger.info(f"Initialized LLM client with model: {self.model}")
        else:
            logger.warning("No OpenAI API key provided")
        
    def _log_to_file(self, prefix: str, content: Dict):
        """Log request or response to a file for debugging"""
        try:
            timestamp = int(time.time())
            filename = f"llm_logs/{prefix}_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            logger.debug(f"Logged {prefix} to {filename}")
        except Exception as e:
            logger.error(f"Error logging {prefix} to file: {str(e)}")
    
    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30)
    )
    async def _make_openai_request(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> Dict:
        """Make a request to the OpenAI API with retry logic"""
        if not self.api_key:
            return {"error": "OpenAI API key not provided"}
        
        try:
            # Log the request
            request_data = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature
            }
            self._log_to_file("request", request_data)
            
            # Make the API request
            response = await openai.ChatCompletion.acreate(
                model=self.model,
                messages=messages,
                temperature=temperature
            )
            
            # Log the response
            self._log_to_file("response", response)
            
            return response
        except openai.error.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {str(e)}")
            return {"error": f"Rate limit exceeded: {str(e)}"}
        except openai.error.InvalidRequestError as e:
            logger.error(f"Invalid request to OpenAI: {str(e)}")
            return {"error": f"Invalid request: {str(e)}"}
        except openai.error.APIError as e:
            logger.error(f"OpenAI API error: {str(e)}")
            return {"error": f"API error: {str(e)}"}
        except (openai.error.Timeout, httpx.TimeoutException) as e:
            logger.error(f"Request to OpenAI timed out: {str(e)}")
            return {"error": f"Request timed out: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI request: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}
    
    def _format_weather_for_prompt(self, weather_info: Dict) -> str:
        """Format weather information for inclusion in the prompt"""
        if not weather_info or "location" not in weather_info:
            return "Информация о погоде недоступна."
        
        try:
            location = weather_info.get("location", "")
            daily = weather_info.get("daily", [])
            
            if not daily:
                return "Данные о погоде отсутствуют."
            
            weather_text = f"Прогноз погоды для {location}:\n"
            
            for day in daily[:5]:  # Only include first 5 days
                date = day.get("date", "")
                temp_min = day.get("temp_min", "")
                temp_max = day.get("temp_max", "")
                description = day.get("description", "")
                
                weather_text += f"- {date}: {temp_min}°C до {temp_max}°C, {description}\n"
            
            return weather_text
        except Exception as e:
            logger.error(f"Error formatting weather info: {str(e)}", 
                        extra={"component": "LLMClient", "error_type": "weather_format_error", "error": str(e)})
            return "Ошибка при обработке информации о погоде."
    
    def _extract_json_from_text(self, text: str) -> Dict:
        """Extract JSON object from text response"""
        # Try to find JSON object using regex pattern
        json_pattern = r'```json\n([\s\S]*?)\n```'
        matches = re.findall(json_pattern, text)
        
        if matches:
            try:
                return json.loads(matches[0])
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON from match: {str(e)}", 
                           extra={"component": "LLMClient", "error_type": "json_parse_error", "error": str(e)})
                logger.debug(f"Failed JSON match content: {matches[0][:100]}...")
        
        # If no matches with markdown formatting, try to find any JSON-like structure
        try:
            # Try to find any JSON object pattern
            json_pattern = r'\{[\s\S]*?\}'
            matches = re.findall(json_pattern, text)
            
            if matches:
                # Try each match until a valid JSON is found
                for match in matches:
                    try:
                        # Check if this is a complete JSON object, not a fragment
                        if match.count('{') == match.count('}'):
                            parsed = json.loads(match)
                            # If it has 'categories' it's likely our desired JSON
                            if 'categories' in parsed:
                                return parsed
                    except:
                        continue
        except Exception as e:
            logger.error(f"Error finding JSON pattern: {str(e)}", 
                       extra={"component": "LLMClient", "error_type": "json_extraction_error", "error": str(e)})
        
        logger.error("Failed to extract valid JSON from response", 
                   extra={"component": "LLMClient", "error_type": "json_extraction_failed"})
        return {"error": "Failed to extract valid JSON from response"}
    
    async def generate_checklist(self, 
                             destination: str,
                             purpose: str,
                             category: str = None,
                             duration: int = 0,
                             start_date: str = "",
                             weather_info: Dict = None,
                             previous_lists: List[Dict] = None) -> Dict[str, Any]:
        """
        Generate a travel checklist using OpenAI API
        
        Args:
            destination: Place of travel
            purpose: Purpose of travel as entered by the user (original text)
            category: Classified purpose category (optional)
            duration: Duration in days
            start_date: Start date (optional)
            weather_info: Weather forecast information (optional)
            previous_lists: User's previous checklists for personalization (optional)
            
        Returns:
            Dictionary with categories and items
        """
        logger.info(f"Generating checklist with LLM for {destination}, purpose: {purpose}, category: {category}, duration: {duration}", 
                  extra={"user_interaction": True, "component": "LLMClient", "destination": destination, 
                         "purpose": purpose, "category": category, "duration": duration, 
                         "has_weather_info": bool(weather_info), 
                         "has_previous_lists": bool(previous_lists and len(previous_lists) > 0)})
        
        if not self.api_key:
            logger.error("Cannot generate checklist: OpenAI API key not provided", 
                       extra={"user_interaction": True, "component": "LLMClient", "error_type": "missing_api_key"})
            return {"error": "OpenAI API key not provided"}
        
        # Format weather information for prompt
        weather_text = self._format_weather_for_prompt(weather_info) if weather_info else "Информация о погоде недоступна."
        
        # Format previous lists for personalization
        personalization_text = ""
        if previous_lists and len(previous_lists) > 0:
            if category:
                personalization_text = f"Предыдущие списки пользователя для категории '{category}':\n"
            else:
                personalization_text = "Предыдущие списки пользователя для персонализации:\n"
                
            for i, prev_list in enumerate(previous_lists):
                personalization_text += f"Список {i+1}:\n"
                personalization_text += f"- Направление: {prev_list.get('destination', 'Неизвестно')}\n"
                personalization_text += f"- Цель: {prev_list.get('purpose', 'Неизвестно')}\n"
                personalization_text += f"- Длительность: {prev_list.get('duration', 0)} дней\n"
                
                if 'items' in prev_list:
                    personalization_text += "- Элементы по категориям:\n"
                    for category, items in prev_list['items'].items():
                        personalization_text += f"  - {category}: {', '.join(items)}\n"
                personalization_text += "\n"
        else:
            personalization_text = "Предыдущие списки пользователя отсутствуют."
        
        # Log the generated text for debugging
        logger.debug(f"Generated weather text for prompt: '{weather_text[:100]}...'", 
                   extra={"component": "LLMClient"})
        logger.debug(f"Generated personalization text for prompt: '{personalization_text[:100]}...'", 
                   extra={"component": "LLMClient"})
        
        # Format the purpose text with category if available
        formatted_purpose = purpose
        if category:
            formatted_purpose = f"{purpose} (категория: {category})"
        
        # Create message list for OpenAI chat API
        messages = [
            {
                "role": "system",
                "content": """Ты - помощник для создания чек-листов для путешествий. 
                Создай подробный чек-лист для путешествия на основе информации о направлении, 
                цели поездки, длительности и погоде. Организуй предметы по логическим категориям.
                
                ВАЖНО: Твой ответ должен быть в формате JSON и содержать только категории и предметы.
                Используй только русский язык для всех элементов.
                
                Формат ответа (пример):
                ```json
                {
                  "categories": {
                    "Документы": ["Паспорт", "Билеты", "Страховка"],
                    "Одежда": ["Футболки", "Джинсы", "Куртка"],
                    "Электроника": ["Телефон", "Зарядное устройство"],
                    "Гигиена": ["Зубная щетка", "Шампунь"]
                  }
                }
                ```
                
                Не добавляй никакого текста до или после JSON.
                """
            },
            {
                "role": "user",
                "content": f"""Создай чек-лист для путешествия со следующими параметрами:

Направление: {destination}
Цель поездки: {formatted_purpose}
Длительность: {duration} дней
{f'Дата начала: {start_date}' if start_date else ''}

Информация о погоде:
{weather_text}

{personalization_text}

Пожалуйста, создай детальный чек-лист с учетом этих данных, разделив предметы по логическим категориям.
Учти цель поездки, длительность и погодные условия.
Если у пользователя есть предыдущие списки, используй их для персонализации.
"""
            }
        ]
        
        # Log the message content (excluding system prompt for brevity)
        logger.debug("Sending user prompt to OpenAI API", 
                   extra={"component": "LLMClient", "prompt_length": len(messages[1]["content"])})
        
        # Make the API request
        try:
            logger.info("Making OpenAI API request", 
                      extra={"user_interaction": True, "component": "LLMClient", "request_start": True})
            
            response = await self._make_openai_request(messages)
            
            if "error" in response:
                logger.error(f"Error in OpenAI request: {response['error']}", 
                           extra={"user_interaction": True, "component": "LLMClient", 
                                  "error_type": "api_error", "error": response['error']})
                return response
            
            logger.info("Successfully received response from OpenAI API", 
                      extra={"user_interaction": True, "component": "LLMClient", "request_complete": True})
            
            # Extract the content from the response
            if "choices" in response and len(response["choices"]) > 0:
                content = response["choices"][0]["message"]["content"]
                logger.debug(f"Received raw response from OpenAI (first 200 chars): {content[:200]}...", 
                           extra={"component": "LLMClient"})
                
                # Extract JSON from the response
                logger.debug("Attempting to extract JSON from response", 
                           extra={"component": "LLMClient"})
                result = self._extract_json_from_text(content)
                
                if "error" in result:
                    logger.error(f"Error extracting JSON from response: {result['error']}", 
                               extra={"user_interaction": True, "component": "LLMClient", 
                                      "error_type": "json_extraction_error", "error": result['error']})
                    # Log the first 500 characters of the content for debugging
                    logger.debug(f"Failed response content (first 500 chars): {content[:500]}...", 
                               extra={"component": "LLMClient"})
                    return result
                
                # Check if categories exist and are not empty
                if "categories" not in result or not result["categories"]:
                    logger.error("OpenAI response didn't contain categories or they were empty", 
                               extra={"user_interaction": True, "component": "LLMClient", 
                                      "error_type": "missing_categories"})
                    return {"error": "Response did not contain valid categories"}
                
                # Count total items
                total_items = sum(len(items) for items in result["categories"].values())
                logger.info(f"Successfully generated checklist with {len(result['categories'])} categories and {total_items} items", 
                          extra={"user_interaction": True, "component": "LLMClient", 
                                 "category_count": len(result["categories"]), 
                                 "item_count": total_items})
                
                return result
            else:
                logger.error("OpenAI response didn't contain any choices", 
                           extra={"user_interaction": True, "component": "LLMClient", 
                                  "error_type": "missing_choices", "response_keys": list(response.keys())})
                return {"error": "Response did not contain any text"}
                
        except Exception as e:
            logger.error(f"Unexpected error generating checklist: {str(e)}", 
                       extra={"user_interaction": True, "component": "LLMClient", 
                              "error_type": "unexpected_error", "error": str(e)})
            import traceback
            logger.debug(f"Detailed error traceback: {traceback.format_exc()}", 
                       extra={"component": "LLMClient"})
            return {"error": f"Unexpected error: {str(e)}"}
    
    async def classify_trip_purpose(self, 
                                user_input: str, 
                                base_purposes: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Classify user-entered trip purpose using LLM
        
        Args:
            user_input: User-entered trip purpose
            base_purposes: List of base trip purposes from database
            
        Returns:
            Dictionary with classified purpose and whether it's a new category
        """
        logger.info(f"Classifying trip purpose: '{user_input}'", 
                  extra={"user_interaction": True, "component": "LLMClient", "user_input": user_input})
        
        if not self.api_key:
            logger.error("Cannot classify trip purpose: OpenAI API key not provided", 
                       extra={"user_interaction": True, "component": "LLMClient", "error_type": "missing_api_key"})
            return {"error": "OpenAI API key not provided"}
        
        # Format base purposes for prompt
        base_purposes_text = "\n".join([f"- {p['name']}: {p['description']}" for p in base_purposes])
        
        # Create message list for OpenAI chat API
        messages = [
            {
                "role": "system",
                "content": """Ты - помощник для классификации целей путешествий.
                Твоя задача - отнести введенную пользователем цель поездки к одной из базовых категорий.
                Если цель не подходит ни к одной из базовых категорий, предложи новую категорию.
                
                ВАЖНО: Твой ответ должен быть в формате JSON и содержать только необходимую информацию.
                Используй только русский язык для названий и описаний.
                
                Формат ответа (пример):
                ```json
                {
                  "matched_category": "beach",  
                  "is_new_category": false,
                  "new_category_name": null,
                  "new_category_description": null
                }
                ```
                
                или, если нужно создать новую категорию:
                
                ```json
                {
                  "matched_category": null,
                  "is_new_category": true,
                  "new_category_name": "diving",
                  "new_category_description": "Дайвинг и подводное плавание"
                }
                ```
                
                Не добавляй никакого текста до или после JSON.
                """
            },
            {
                "role": "user",
                "content": f"""Классифицируй следующую цель путешествия:

Цель поездки (введено пользователем): {user_input}

Базовые категории целей:
{base_purposes_text}

Пожалуйста, определи, к какой базовой категории относится эта цель.
Если цель не подходит ни к одной из базовых категорий, предложи новую категорию (используй краткое название на английском и описание на русском).
"""
            }
        ]
        
        # Make the API request
        try:
            logger.info("Making OpenAI API request for trip purpose classification", 
                      extra={"user_interaction": True, "component": "LLMClient", "request_start": True})
            
            response = await self._make_openai_request(messages)
            
            if "error" in response:
                logger.error(f"Error in OpenAI request: {response['error']}", 
                           extra={"user_interaction": True, "component": "LLMClient", 
                                  "error_type": "api_error", "error": response['error']})
                return response
            
            logger.info("Successfully received response from OpenAI API", 
                      extra={"user_interaction": True, "component": "LLMClient", "request_complete": True})
            
            # Extract the content from the response
            if "choices" in response and len(response["choices"]) > 0:
                content = response["choices"][0]["message"]["content"]
                logger.debug(f"Received raw response from OpenAI (first 200 chars): {content[:200]}...", 
                           extra={"component": "LLMClient"})
                
                # Extract JSON from the response
                logger.debug("Attempting to extract JSON from response", 
                           extra={"component": "LLMClient"})
                result = self._extract_json_from_text(content)
                
                if "error" in result:
                    logger.error(f"Error extracting JSON from response: {result['error']}", 
                               extra={"user_interaction": True, "component": "LLMClient", 
                                      "error_type": "json_extraction_error", "error": result['error']})
                    # Fallback to a default category if JSON extraction fails
                    return {
                        "matched_category": "other",
                        "is_new_category": False,
                        "new_category_name": None,
                        "new_category_description": None
                    }
                
                # Check if result has required fields
                if "matched_category" not in result and "is_new_category" not in result:
                    logger.error("OpenAI response didn't contain required fields", 
                               extra={"user_interaction": True, "component": "LLMClient", 
                                      "error_type": "missing_fields"})
                    # Fallback to a default category
                    return {
                        "matched_category": "other",
                        "is_new_category": False,
                        "new_category_name": None,
                        "new_category_description": None
                    }
                
                logger.info(f"Successfully classified trip purpose", 
                          extra={"user_interaction": True, "component": "LLMClient", 
                                 "is_new_category": result.get("is_new_category", False),
                                 "matched_category": result.get("matched_category", "other")})
                
                return result
            else:
                logger.error("OpenAI response didn't contain any choices", 
                           extra={"user_interaction": True, "component": "LLMClient", 
                                  "error_type": "missing_choices", "response_keys": list(response.keys())})
                return {
                    "matched_category": "other",
                    "is_new_category": False,
                    "new_category_name": None,
                    "new_category_description": None
                }
                
        except Exception as e:
            logger.error(f"Unexpected error classifying trip purpose: {str(e)}", 
                       extra={"user_interaction": True, "component": "LLMClient", 
                              "error_type": "unexpected_error", "error": str(e)})
            import traceback
            logger.debug(f"Detailed error traceback: {traceback.format_exc()}", 
                       extra={"component": "LLMClient"})
            return {
                "matched_category": "other", 
                "is_new_category": False,
                "new_category_name": None,
                "new_category_description": None
            } 