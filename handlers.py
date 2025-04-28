import logging
from datetime import datetime
from typing import Dict, Any
import re
import os
import statistics

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# Import states from constants.py
from constants import WAITING_DESTINATION, WAITING_START_DATE, WAITING_DURATION, WAITING_TRIP_TYPE, WAITING_NEW_ITEM_NAME

from models.checklist import User, Checklist, ChecklistItem
from services.weather import WeatherService
from services.checklist_generator import ChecklistGenerator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class ChecklistHandlers:
    def __init__(self, session: Session, llm_client=None):
        """Initialize handlers with database session."""
        self.session = session
        self.checklist_generator = ChecklistGenerator()
        self.weather_service = WeatherService()
        self.llm_client = llm_client or self.checklist_generator.llm_client

    async def handle_destination(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle destination input for new trip checklist."""
        user = update.effective_user
        destination = update.message.text
        
        logger.info("User interaction", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "action": "destination_input",
            "destination": destination
        })
        
        # Clear any previous data to avoid state conflicts
        context.user_data.clear()
        context.user_data['destination'] = destination

        # Теперь спрашиваем о дате начала поездки
        message = (
            f"🌍 Отлично! Вы собираетесь в {destination}.\n\n"
            "Когда планируете поездку? Укажите дату начала в формате ДД.ММ.ГГГГ\n"
            "Например: 25.06.2025"
        )
        await update.message.reply_text(message)
        return WAITING_START_DATE

    async def handle_start_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle trip start date input."""
        user = update.effective_user
        date_text = update.message.text
        
        try:
            # Validate date format (DD.MM.YYYY)
            if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_text):
                await update.message.reply_text(
                    "Пожалуйста, введите дату в формате ДД.ММ.ГГГГ (например: 25.06.2025)"
                )
                return WAITING_START_DATE
                
            # Parse date
            try:
                start_date = datetime.strptime(date_text, "%d.%m.%Y")
                
                # Check if date is in the future
                if start_date < datetime.now():
                    await update.message.reply_text(
                        "Дата начала поездки должна быть в будущем. Пожалуйста, введите корректную дату."
                    )
                    return WAITING_START_DATE
                    
            except ValueError:
                await update.message.reply_text(
                    "Введена некорректная дата. Пожалуйста, проверьте правильность и попробуйте снова."
                )
                return WAITING_START_DATE
            
            logger.info("User interaction", extra={
                "user_interaction": True,
                "user_id": user.id,
                "username": user.username,
                "action": "start_date_input",
                "start_date": date_text
            })
            
            # Save start date to context
            context.user_data['start_date'] = date_text
            context.user_data['start_date_obj'] = start_date
            
            # Спрашиваем о длительности
            message = "На сколько дней планируется поездка? Введите число:"
            await update.message.reply_text(message)
            return WAITING_DURATION
            
        except Exception as e:
            logger.error("Error processing start date", extra={
                "user_interaction": True,
                "user_id": user.id,
                "error": str(e)
            })
            await update.message.reply_text(
                "😔 Произошла ошибка при обработке даты. Пожалуйста, попробуйте снова."
            )
            return WAITING_START_DATE

    async def handle_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle trip duration input."""
        user = update.effective_user
        
        logger.info("User interaction", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "action": "duration_input",
            "input": update.message.text
        })
        
        try:
            # Parse duration as integer
            duration = int(update.message.text.strip())
            
            if duration <= 0:
                raise ValueError("Duration must be positive")
                
            context.user_data['duration'] = duration
            
            # Get weather info for this destination
            try:
                # Отправим сообщение о том, что запрашиваем погоду
                await update.message.reply_text(
                    f"🔄 Получаю информацию о погоде для {context.user_data['destination']}...\n"
                    f"Это может занять несколько секунд."
                )
                
                # Генерируем прогноз погоды
                weather_info = await self.weather_service.get_weather_forecast(
                    context.user_data['destination']
                )
                
                # Сохраним погоду в данных пользователя
                context.user_data['weather_info'] = weather_info
                
                # Создадим агрегированное описание погоды
                weather_description = []
                temp_min = []
                temp_max = []
                wind_speeds = []
                precipitation_amounts = []
                
                for day_forecast in weather_info.get('daily', []):
                    # Добавим общее описание погоды
                    if 'description' in day_forecast:
                        weather_description.append(day_forecast['description'])
                    
                    # Соберём температуры
                    if 'temp_min' in day_forecast:
                        temp_min.append(day_forecast['temp_min'])
                    if 'temp_max' in day_forecast:
                        temp_max.append(day_forecast['temp_max'])
                    
                    # Соберём скорость ветра
                    if 'wind_speed' in day_forecast:
                        wind_speeds.append(day_forecast['wind_speed'])
                    
                    # Соберём данные об осадках
                    if 'precipitation' in day_forecast:
                        precipitation_amounts.append(day_forecast['precipitation'])
                
                # Формируем погодное сообщение
                weather_message = f"📊 Погода в {context.user_data['destination']} на {min(duration, len(weather_info.get('daily', [])))} дней:\n\n"
                
                # Если есть прогноз хотя бы на один день, добавим его
                if weather_info.get('daily', []):
                    weather_message += f"• Погода: {', '.join(set(weather_description[:3]))}...\n"
                    
                    if temp_min and temp_max:
                        avg_min = sum(temp_min) / len(temp_min)
                        avg_max = sum(temp_max) / len(temp_max)
                        weather_message += f"• Температура: от {avg_min:.1f}°C до {avg_max:.1f}°C\n"
                    
                    if wind_speeds:
                        max_wind = max(wind_speeds)
                        weather_message += f"• Ветер: до {max_wind} м/с\n"
                    
                    if precipitation_amounts:
                        total_precip = sum(precipitation_amounts)
                        weather_message += f"• Осадки: {total_precip:.1f} мм"
                else:
                    weather_message += "К сожалению, не удалось получить подробный прогноз погоды."
                
                # Сохраним агрегированные данные о погоде
                context.user_data['aggregated_weather'] = {
                    'descriptions': list(set(weather_description)),
                    'avg_temp_min': sum(temp_min)/len(temp_min) if temp_min else None,
                    'avg_temp_max': sum(temp_max)/len(temp_max) if temp_max else None,
                    'max_wind': max(wind_speeds) if wind_speeds else None,
                    'avg_precip': round(total_precip/len(precipitation_amounts), 1) if precipitation_amounts else None,
                    'total_precip': round(total_precip, 1) if precipitation_amounts else None
                }
                
                # Отправляем агрегированный прогноз погоды
                await update.message.reply_text(weather_message)
                
                # Отправляем вопрос о цели поездки
                await update.message.reply_text(
                    "Какова цель вашей поездки? Опишите её своими словами.\n\n"
                    "Например: отдохнуть на пляже, посетить деловую конференцию, "
                    "осмотреть достопримечательности, поход в горы и т.д."
                )
                return WAITING_TRIP_TYPE
                
            except Exception as e:
                logger.error("Error getting weather info", extra={
                    "user_interaction": True,
                    "user_id": user.id,
                    "destination": context.user_data['destination'],
                    "error": str(e)
                })
                await update.message.reply_text(
                    "⚠️ Не удалось получить информацию о погоде. Но мы все равно продолжим.\n\n"
                    "Какова цель вашей поездки? Опишите её своими словами.\n\n"
                    "Например: отдохнуть на пляже, посетить деловую конференцию, "
                    "осмотреть достопримечательности, поход в горы и т.д."
                )
                return WAITING_TRIP_TYPE
            
        except ValueError:
            logger.warning("Invalid duration input", extra={
                "user_interaction": True,
                "user_id": user.id,
                "input": update.message.text
            })
            await update.message.reply_text(
                "Пожалуйста, введите корректное число дней (больше 0)."
            )
            return WAITING_DURATION
        except Exception as e:
            logger.error("Error processing duration", extra={
                "user_interaction": True,
                "user_id": user.id,
                "error": str(e)
            })
            await update.message.reply_text(
                "😔 Произошла ошибка при обработке данных. Пожалуйста, попробуйте снова."
            )
            context.user_data.clear()
            return ConversationHandler.END

    async def handle_trip_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle trip type input."""
        user = update.effective_user
        
        # Now handling text input instead of callback query
        user_input = update.message.text.strip()
        
        logger.info("User interaction", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "action": "trip_type_input",
            "user_input": user_input
        })
        
        # Store the original user input
        context.user_data['original_trip_purpose'] = user_input
        
        # Send message about processing
        progress_message = await update.message.reply_text(
            "🔄 Обрабатываю информацию о целях поездки...\n"
            "Это может занять несколько секунд."
        )
        
        # Get all base trip purposes from database
        from models.checklist import TripPurpose
        
        # Get all base trip purposes
        base_purposes = []
        try:
            base_purposes = self.session.query(TripPurpose).all()
            logger.info(f"Found {len(base_purposes)} base trip purposes in database")
            
            # If no base purposes in database, initialize them
            if not base_purposes:
                logger.info("No base trip purposes found in database, initializing them")
                from init_base_trip_purposes import init_trip_purposes
                init_trip_purposes()
                base_purposes = self.session.query(TripPurpose).all()
                logger.info(f"Initialized {len(base_purposes)} base trip purposes")
            
            # Convert to dict format for LLM
            base_purposes_for_llm = [
                {"name": p.name, "description": p.description} 
                for p in base_purposes
            ]
            
            # Classify the user input using LLM
            classification_result = await self.llm_client.classify_trip_purpose(
                user_input, 
                base_purposes_for_llm
            )
            
            # Handle new category if needed
            if classification_result.get("is_new_category", False) and classification_result.get("new_category_name"):
                new_name = classification_result["new_category_name"]
                new_description = classification_result["new_category_description"] or new_name
                
                # Check if this category already exists (just in case)
                existing = self.session.query(TripPurpose).filter_by(name=new_name).first()
                if not existing:
                    # Add the new category to the database
                    new_purpose = TripPurpose(
                        name=new_name,
                        description=new_description,
                        is_base=False  # Not a base category
                    )
                    self.session.add(new_purpose)
                    self.session.commit()
                    logger.info(f"Added new trip purpose category: {new_name} - {new_description}")
                    
                # Use the new category
                trip_type = new_name
            else:
                # Use the matched category
                trip_type = classification_result.get("matched_category", "other")
            
            # Store the classified trip type
            context.user_data['trip_type'] = trip_type
            
            # Generate checklist based on collected information
            logger.info("Generating checklist", extra={
                "user_interaction": True,
                "user_id": user.id,
                "destination": context.user_data['destination'],
                "trip_type": context.user_data['trip_type'],
                "original_purpose": context.user_data['original_trip_purpose'],
                "duration": context.user_data['duration'],
                "start_date": context.user_data['start_date']
            })
            
            # Отправим сообщение о том, что генерируем список
            await progress_message.edit_text(
                "🔄 Генерирую список вещей для вашей поездки...\n"
                "Это может занять несколько секунд."
            )
            
            # Получаем пользователя из базы данных или создаем нового
            from models.checklist import User
            user_db = self.session.query(User).filter_by(
                telegram_id=update.effective_user.id
            ).first()
            
            if not user_db:
                user_db = User(
                    telegram_id=update.effective_user.id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    last_name=update.effective_user.last_name
                )
                self.session.add(user_db)
                self.session.commit()
            
            # Generate checklist with LLM
            checklist = await self.checklist_generator.generate_travel_checklist(
                destination=context.user_data['destination'],
                purpose=context.user_data['original_trip_purpose'],  # Pass original purpose
                category=context.user_data['trip_type'],  # Pass classified category
                duration=context.user_data['duration'],
                start_date=context.user_data['start_date'],
                weather_info=context.user_data.get('weather_info', {}),
                user_id=user_db.id  # Pass user ID for fetching previous lists
            )
            
            # Create a better title with date, time, purpose and duration
            creation_time = datetime.now().strftime("%H:%M")
            trip_purpose = context.user_data['original_trip_purpose']  # Show original purpose in title
            trip_title = f"{context.user_data['destination']} с {context.user_data['start_date']} ({trip_purpose} {context.user_data['duration']} дней)"
            
            from models.checklist import Checklist, ChecklistItem
            db_checklist = Checklist(
                title=trip_title,
                type='travel',
                trip_metadata={
                    'destination': context.user_data['destination'],
                    'trip_type': context.user_data['trip_type'],  # Classified type
                    'original_purpose': context.user_data['original_trip_purpose'],  # Original input
                    'duration': context.user_data['duration'],
                    'start_date': context.user_data['start_date'],
                    'weather': context.user_data.get('weather_info', {}),
                    'aggregated_weather': context.user_data.get('aggregated_weather', {})
                },
                owner_id=user_db.id
            )
            self.session.add(db_checklist)
            self.session.commit()
            
            logger.info("Checklist saved", extra={
                "user_interaction": True,
                "user_id": user_db.id,
                "checklist_id": db_checklist.id,
                "generation_method": checklist.get("generated_by", "unknown")
            })
            
            # Convert categories from the generator to our item format
            items = []
            for category, category_items in checklist['categories'].items():
                for item in category_items:
                    items.append({
                        'title': item,
                        'category': category
                    })
            
            # Add all items to the database
            for item in items:
                checklist_item = ChecklistItem(
                    title=item['title'],
                    description=item.get('description'),
                    category=item.get('category'),
                    checklist_id=db_checklist.id,
                    order=item.get('order', 0)
                )
                self.session.add(checklist_item)
            self.session.commit()
            
            # Для публичного доступа требуется внешний URL
            checklist_id = db_checklist.id
            
            # Проверяем, доступен ли публичный URL через ngrok
            public_url = os.environ.get('PUBLIC_WEB_URL')
            
            if public_url:
                # Если есть публичный URL, используем его для кнопки
                web_url = f"{public_url}/checklist/{checklist_id}"
                
                # Добавляем кнопку для открытия веб-версии
                web_button = [InlineKeyboardButton("🌐 Открыть в браузере", url=web_url)]
                
                # Текст сообщения с публичной ссылкой
                web_message = f"🌐 Веб-версия списка доступна по ссылке: {web_url}"
            else:
                # Если публичного URL нет, показываем инструкции по локальному доступу
                web_button = []  # Нет кнопки для локального URL
                
                # Инструкции по локальному доступу
                web_message = (
                    f"Для доступа к веб-версии: http://localhost:8000/checklist/{checklist_id}"
                )
            
            # Create result message
            result_text = (
                f"✅ Готово! Создан чек-лист для поездки в {context.user_data['destination']}.\n\n"
                f"📋 Всего элементов: {len(items)}\n"
                f"📁 Категорий: {len(checklist['categories'])}\n\n"
                f"{web_message}"
            )
            
            # Send message with inline keyboard for web view and voice
            keyboard = []
            if web_button:
                keyboard.append(web_button)
            
            keyboard.append([InlineKeyboardButton("📝 Мои списки", callback_data="my_lists")])
            keyboard.append([InlineKeyboardButton("➕ Новый список", callback_data="new_trip")])
            keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(result_text, reply_markup=reply_markup)
            
            # Clear user data
            context.user_data.clear()
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error("Error processing trip type input", extra={
                "user_interaction": True,
                "user_id": user.id,
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            
            # In case of error, use a default category
            context.user_data['trip_type'] = "other"
            context.user_data['original_trip_purpose'] = user_input
            
            await update.message.reply_text(
                "⚠️ Произошла ошибка при обработке цели поездки. Используем категорию 'Другое'.\n"
                "Продолжаем создание чек-листа..."
            )
            
            # For brevity, let's send a generic error message and restart the conversation
            await update.message.reply_text(
                "😔 Произошла ошибка при обработке данных. Пожалуйста, попробуйте снова."
            )
            context.user_data.clear()
            return ConversationHandler.END

    async def show_user_lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show all checklists for the user."""
        user = update.effective_user
        query = update.callback_query
        
        try:
            # Get user's checklists from database
            user_obj = self.session.query(User).filter(User.telegram_id == user.id).first()
            if not user_obj:
                user_obj = User(telegram_id=user.id, username=user.username)
                self.session.add(user_obj)
                self.session.commit()
            
            checklists = self.session.query(Checklist).filter(Checklist.owner_id == user_obj.id).all()
            
            if not checklists:
                message = (
                    "У вас пока нет сохраненных списков для путешествий.\n\n"
                    "Создайте новый список с помощью команды /newtrip"
                )
                keyboard = [[InlineKeyboardButton("🌍 Создать новый список", callback_data="new_trip")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if query:
                    await query.edit_message_text(text=message, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(message, reply_markup=reply_markup)
                return
            
            message = "📋 Ваши списки для путешествий:\n\n"
            keyboard = []
            
            for checklist in checklists:
                # Get destination from trip_metadata
                destination = "Неизвестное место"
                if checklist.trip_metadata and 'destination' in checklist.trip_metadata:
                    destination = checklist.trip_metadata['destination']
                
                # Format date if available
                date_str = ""
                if checklist.trip_metadata and 'start_date' in checklist.trip_metadata:
                    try:
                        start_date = datetime.strptime(checklist.trip_metadata['start_date'], "%d.%m.%Y")
                        date_str = f" ({start_date.strftime('%d.%m.%Y')})"
                    except (ValueError, TypeError):
                        pass
                
                # Add checklist to message and keyboard
                message += f"• {destination}{date_str}\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 {destination}{date_str}",
                        callback_data=f"view_{checklist.id}"
                    )
                ])
            
            # Add navigation buttons
            keyboard.append([InlineKeyboardButton("🌍 Создать новый список", callback_data="new_trip")])
            keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(text=message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message, reply_markup=reply_markup)
                
        except Exception as e:
            logger.error(f"Error showing user lists: {str(e)}", exc_info=True)
            error_message = (
                "Произошла ошибка при обработке запроса. "
                "Пожалуйста, попробуйте снова или используйте /start для возврата в главное меню."
            )
            if query:
                await query.edit_message_text(text=error_message)
            else:
                await update.message.reply_text(error_message)

    async def view_checklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checklist_id: int) -> None:
        """View a specific checklist."""
        user = update.effective_user
        query = update.callback_query
        
        # Get checklist from database
        checklist = self.session.query(Checklist).filter(Checklist.id == checklist_id).first()
        
        if not checklist:
            message = "❌ Список не найден."
            keyboard = [[InlineKeyboardButton("🔙 Назад к спискам", callback_data="my_lists")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(text=message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message, reply_markup=reply_markup)
            return
        
        # Get destination from trip_metadata
        destination = "Неизвестное место"
        if checklist.trip_metadata and 'destination' in checklist.trip_metadata:
            destination = checklist.trip_metadata['destination']
        
        # Format checklist information
        message = f"🌍 Список для путешествия в {destination}\n\n"
        
        # Get start date from trip_metadata
        if checklist.trip_metadata and 'start_date' in checklist.trip_metadata:
            message += f"📅 Дата начала: {checklist.trip_metadata['start_date']}\n"
        
        # Get duration from trip_metadata
        if checklist.trip_metadata and 'duration' in checklist.trip_metadata:
            message += f"⏱ Длительность: {checklist.trip_metadata['duration']} дней\n"
        
        # Get trip type from trip_metadata
        if checklist.trip_metadata and 'trip_type' in checklist.trip_metadata:
            message += f"🎯 Цель поездки: {checklist.trip_metadata['trip_type']}\n"
        
        # Добавляем информацию о погоде, если она есть
        if checklist.trip_metadata and 'aggregated_weather' in checklist.trip_metadata:
            weather = checklist.trip_metadata['aggregated_weather']
            message += "🌦 **Прогноз погоды:**\n"
            
            if weather.get('day_temp_range'):
                message += f"🌡 Днем: от {weather['day_temp_range'][0]}°C до {weather['day_temp_range'][1]}°C\n"
                
            if weather.get('night_temp_range'):
                message += f"🌙 Ночью: от {weather['night_temp_range'][0]}°C до {weather['night_temp_range'][1]}°C\n"
                
            if weather.get('descriptions'):
                message += f"☁️ Погода: {', '.join(weather['descriptions'])}\n"
                
            if weather.get('avg_wind'):
                message += f"💨 Ветер: в среднем {weather['avg_wind']} м/с"
                if weather.get('max_wind'):
                    message += f", максимум до {weather['max_wind']} м/с"
                message += "\n"
                
            if weather.get('avg_precip'):
                message += f"🌧 Осадки: в среднем {weather['avg_precip']} мм/день"
                if weather.get('total_precip'):
                    message += f", всего до {weather['total_precip']} мм за период"
                message += "\n"
        
        message += "\n📋 Список вещей:\n\n"
        
        # Group items by category
        items_by_category = {}
        for item in checklist.items:
            category = item.category or "Прочее"
            if category not in items_by_category:
                items_by_category[category] = []
            items_by_category[category].append(item)
        
        # Add items to message
        for category, items in items_by_category.items():
            message += f"📁 {category}:\n"
            for item in items:
                status = "✅" if item.is_completed else "•"
                message += f"{status} {item.title}\n"
            message += "\n"
        
        # Проверяем, доступен ли публичный URL через ngrok
        public_url = os.environ.get('PUBLIC_WEB_URL')
        
        if public_url:
            # Если есть публичный URL, используем его для кнопки
            web_url = f"{public_url}/checklist/{checklist_id}"
            
            # Добавляем кнопку для открытия веб-версии
            web_button = [InlineKeyboardButton("🌐 Открыть в браузере", url=web_url)]
            
            # Текст сообщения с публичной ссылкой
            web_message = f"🌐 Веб-версия списка доступна по ссылке: {web_url}"
            
            # Добавляем информацию о веб-интерфейсе
            message += f"{web_message}\n"
        else:
            # Если публичного URL нет, показываем инструкции по локальному доступу
            web_button = []  # Нет кнопки для локального URL
            
            # Инструкции по локальному доступу
            web_message = (
                f"Для доступа к веб-версии: http://localhost:8000/checklist/{checklist_id}"
            )
            
            # Добавляем информацию о веб-интерфейсе
            message += f"{web_message}\n"
        
        keyboard = [
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{checklist_id}")],
            [InlineKeyboardButton("📤 Поделиться", callback_data=f"share_{checklist_id}")],
            [InlineKeyboardButton("🔙 Назад к спискам", callback_data="my_lists")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(text=message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
    
    async def edit_checklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checklist_id: int) -> None:
        """Edit a specific checklist."""
        query = update.callback_query
        user = update.effective_user
        
        logger.info("User editing checklist", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id
        })
        
        # Get the checklist
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await query.message.reply_text("Список не найден или был удален.")
            return
        
        # Проверяем, что пользователь владеет этим списком
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await query.message.reply_text("У вас нет доступа к этому списку.")
            return
        
        # Группируем элементы по категориям
        items_by_category = {}
        for item in checklist.items:
            category = item.category or "Прочее"
            if category not in items_by_category:
                items_by_category[category] = []
            items_by_category[category].append(item)
        
        message = f"📝 Редактирование списка: {checklist.title}\n\n"
        message += "Выберите действие:"
        
        # Опции редактирования
        keyboard = []
        
        # Добавляем кнопки для добавления элементов
        keyboard.append([InlineKeyboardButton("➕ Добавить элемент", callback_data=f"add_item_{checklist_id}")])
        
        # Добавляем публичную ссылку если доступна
        public_url = os.environ.get('PUBLIC_WEB_URL')
        if public_url:
            web_url = f"{public_url}/edit/{checklist_id}"
            keyboard.append([InlineKeyboardButton("🌐 Редактировать в браузере", url=web_url)])
            message += f"\n\n🌐 Для более удобного редактирования используйте веб-интерфейс: {web_url}"
        
        # Добавляем кнопки для удаления элементов по категориям
        for category, items in items_by_category.items():
            # Добавляем заголовок категории и список элементов
            keyboard.append([InlineKeyboardButton(f"📂 {category} ({len(items)})", callback_data=f"category_{checklist_id}_{category}")])
        
        # Добавляем кнопку возврата и главного меню
        keyboard.append([InlineKeyboardButton("🔙 Назад к списку", callback_data=f"view_{checklist_id}")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)
    
    async def handle_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle category selection for item editing."""
        query = update.callback_query
        user = update.effective_user
        
        # Extract checklist_id and category from callback data
        _, checklist_id, category = query.data.split('_', 2)
        checklist_id = int(checklist_id)
        
        logger.info("User viewing category items", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id,
            "category": category
        })
        
        await query.answer()
        
        # Get the checklist and items in this category
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await query.message.reply_text("Список не найден или был удален.")
            return
        
        # Проверяем, что пользователь владеет этим списком
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await query.message.reply_text("У вас нет доступа к этому списку.")
            return
        
        # Get items in this category
        items = self.session.query(ChecklistItem).filter_by(
            checklist_id=checklist_id,
            category=category
        ).all()
        
        message = f"📂 Категория: {category}\n\n"
        message += "Выберите элемент для удаления:"
        
        keyboard = []
        
        # Add button for each item (for deletion)
        for item in items:
            keyboard.append([InlineKeyboardButton(
                f"❌ {item.title}", 
                callback_data=f"delete_item_{item.id}"
            )])
        
        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 Назад к редактированию", callback_data=f"edit_{checklist_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)
    
    async def handle_add_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle add item request."""
        query = update.callback_query
        user = update.effective_user
        
        # Extract checklist_id from callback data
        _, checklist_id = query.data.split('_', 1)
        checklist_id = int(checklist_id)
        
        logger.info("User adding item to checklist", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id
        })
        
        await query.answer()
        
        # Get the checklist
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await query.message.reply_text("Список не найден или был удален.")
            return
        
        # Проверяем, что пользователь владеет этим списком
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await query.message.reply_text("У вас нет доступа к этому списку.")
            return
        
        # Get categories
        categories = set()
        for item in checklist.items:
            categories.add(item.category or "Прочее")
        
        # Sort categories
        categories = sorted(list(categories))
        if "Прочее" in categories:
            # Move "Прочее" to the end
            categories.remove("Прочее")
            categories.append("Прочее")
        
        # Store in context
        context.user_data['add_item_to_checklist'] = checklist_id
        
        message = "Выберите категорию для нового элемента:"
        
        keyboard = []
        
        # Add button for each category
        for category in categories:
            keyboard.append([InlineKeyboardButton(
                f"📂 {category}", 
                callback_data=f"add_to_category_{checklist_id}_{category}"
            )])
        
        # Add button for new category
        keyboard.append([InlineKeyboardButton(
            "🆕 Новая категория", 
            callback_data=f"new_category_{checklist_id}"
        )])
        
        # Add back button
        keyboard.append([InlineKeyboardButton(
            "🔙 Отмена", 
            callback_data=f"edit_{checklist_id}"
        )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)
    
    async def handle_add_to_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle adding item to a specific category."""
        query = update.callback_query
        user = update.effective_user
        
        # Extract checklist_id and category from callback data
        _, checklist_id, category = query.data.split('_', 2)
        checklist_id = int(checklist_id)
        
        logger.info("User adding item to category", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id,
            "category": category
        })
        
        await query.answer()
        
        # Store in context
        context.user_data['add_item_to_checklist'] = checklist_id
        context.user_data['add_item_category'] = category
        
        message = f"📝 Введите название нового элемента для категории '{category}':"
        
        # Add back button
        keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data=f"edit_{checklist_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)
        
        # Set state for conversation handler
        return WAITING_NEW_ITEM_NAME
    
    async def handle_new_item_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle new item name input."""
        user = update.effective_user
        item_name = update.message.text.strip()
        
        # Get checklist_id and category from context
        checklist_id = context.user_data.get('add_item_to_checklist')
        category = context.user_data.get('add_item_category')
        
        if not checklist_id or not category:
            await update.message.reply_text("Произошла ошибка. Попробуйте начать добавление элемента заново.")
            return ConversationHandler.END
        
        logger.info("User entered new item name", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id,
            "category": category,
            "item_name": item_name
        })
        
        # Get the checklist
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await update.message.reply_text("Список не найден или был удален.")
            return ConversationHandler.END
        
        # Проверяем, что пользователь владеет этим списком
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await update.message.reply_text("У вас нет доступа к этому списку.")
            return ConversationHandler.END
        
        # Add new item
        max_order = self.session.query(ChecklistItem).filter_by(
            checklist_id=checklist_id,
            category=category
        ).count()
        
        new_item = ChecklistItem(
            title=item_name,
            category=category,
            checklist_id=checklist_id,
            order=max_order + 1
        )
        self.session.add(new_item)
        self.session.commit()
        
        logger.info("New item added", extra={
            "user_interaction": True,
            "user_id": user.id,
            "checklist_id": checklist_id,
            "item_id": new_item.id,
            "category": category
        })
        
        # Clear context
        context.user_data.pop('add_item_to_checklist', None)
        context.user_data.pop('add_item_category', None)
        
        message = f"✅ Элемент '{item_name}' добавлен в категорию '{category}'!"
        
        # Add buttons
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще", callback_data=f"add_item_{checklist_id}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data=f"view_{checklist_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
        
        return ConversationHandler.END
    
    async def handle_delete_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle deletion of an item."""
        query = update.callback_query
        user = update.effective_user
        
        # Extract item_id from callback data
        _, item_id = query.data.split('_', 1)
        item_id = int(item_id)
        
        logger.info("User deleting item", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "item_id": item_id
        })
        
        await query.answer()
        
        # Get the item and its checklist
        item = self.session.query(ChecklistItem).filter_by(id=item_id).first()
        
        if not item:
            await query.message.reply_text("Элемент не найден или был удален.")
            return
        
        checklist_id = item.checklist_id
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        # Verify ownership
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await query.message.reply_text("У вас нет доступа к этому списку.")
            return
        
        # Get item details for the message
        item_title = item.title
        category = item.category
        
        # Delete the item
        self.session.delete(item)
        self.session.commit()
        
        logger.info("Item deleted", extra={
            "user_interaction": True,
            "user_id": user.id,
            "checklist_id": checklist_id,
            "item_id": item_id,
            "category": category
        })
        
        message = f"✅ Элемент '{item_title}' удален из списка!"
        
        # Add buttons
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к категории", callback_data=f"category_{checklist_id}_{category}")],
            [InlineKeyboardButton("📝 Редактировать список", callback_data=f"edit_{checklist_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)

    async def share_checklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checklist_id: int) -> None:
        """Share a checklist with others."""
        query = update.callback_query
        user = update.effective_user
        
        logger.info("User sharing checklist", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id
        })
        
        # Get the checklist
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await query.message.reply_text("Список не найден или был удален.")
            return
        
        # Placeholder for share functionality
        message = (
            "🔄 Функция публикации списка находится в разработке.\n\n"
            "Скоро вы сможете делиться своими списками с друзьями или публиковать их в сообществе!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к списку", callback_data=f"view_{checklist_id}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup) 