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
    def __init__(self, session: Session):
        self.session = session
        self.weather_service = WeatherService()
        self.checklist_generator = ChecklistGenerator()

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
        
        try:
            duration = int(update.message.text)
            if duration <= 0:
                raise ValueError("Duration must be positive")
                
            logger.info("User interaction", extra={
                "user_interaction": True,
                "user_id": user.id,
                "username": user.username,
                "action": "duration_input",
                "duration": duration
            })
                
            context.user_data['duration'] = duration
            
            # Check if we have all required data
            required_data = ['destination', 'start_date']
            missing_data = [key for key in required_data if key not in context.user_data]
            
            if missing_data:
                logger.error("Missing required data", extra={
                    "user_interaction": True,
                    "user_id": user.id,
                    "missing_data": missing_data,
                    "current_state": context.user_data.get('state')
                })
                await update.message.reply_text(
                    "😔 Произошла ошибка: отсутствуют необходимые данные. "
                    "Пожалуйста, начните создание списка заново с помощью команды /newtrip"
                )
                context.user_data.clear()
                return ConversationHandler.END
            
            # Теперь запрашиваем данные о погоде
            try:
                logger.info("Fetching weather info", extra={
                    "user_interaction": True,
                    "user_id": user.id,
                    "destination": context.user_data['destination']
                })
                
                weather_info = await self.weather_service.get_weather_forecast(context.user_data['destination'])
                context.user_data['weather_info'] = weather_info
                
                logger.info("Weather info received", extra={
                    "user_interaction": True,
                    "user_id": user.id,
                    "destination": context.user_data['destination']
                })
                
                # Агрегируем информацию о погоде
                forecast_days = min(duration, len(weather_info['forecast']))
                
                # Собираем статистику по температуре
                day_temps = []
                night_temps = []
                descriptions = set()
                wind_speeds = []
                precipitation_amounts = []
                
                for i in range(forecast_days):
                    day_forecast = weather_info['forecast'][i]
                    
                    # Получаем температуры
                    if 'day_temp' in day_forecast:
                        day_temps.append(day_forecast['day_temp'])
                    elif 'avg_temp' in day_forecast:
                        day_temps.append(day_forecast['avg_temp'])
                        
                    if 'night_temp' in day_forecast:
                        night_temps.append(day_forecast['night_temp'])
                    
                    # Собираем описания погоды
                    if 'descriptions' in day_forecast:
                        descriptions.update(day_forecast['descriptions'])
                    
                    # Ветер
                    if 'wind_speed' in day_forecast:
                        wind_speeds.append(day_forecast['wind_speed'])
                    
                    # Осадки
                    if 'precipitation' in day_forecast:
                        precipitation_amounts.append(day_forecast['precipitation'])
                
                # Формируем агрегированное сообщение о погоде
                weather_message = f"🌍 Прогноз погоды в {context.user_data['destination']} на период поездки:\n\n"
                
                # Температура днем
                if day_temps:
                    min_day_temp = min(day_temps)
                    max_day_temp = max(day_temps)
                    weather_message += f"🌡 Днем: от {min_day_temp}°C до {max_day_temp}°C\n"
                
                # Температура ночью
                if night_temps:
                    min_night_temp = min(night_temps)
                    max_night_temp = max(night_temps)
                    weather_message += f"🌙 Ночью: от {min_night_temp}°C до {max_night_temp}°C\n"
                
                # Описание погоды
                if descriptions:
                    weather_message += f"☁️ Погода: {', '.join(descriptions)}\n"
                
                # Ветер
                if wind_speeds:
                    avg_wind = round(statistics.mean(wind_speeds), 1)
                    max_wind = max(wind_speeds)
                    weather_message += f"💨 Ветер: в среднем {avg_wind} м/с, максимум до {max_wind} м/с\n"
                
                # Осадки
                if precipitation_amounts:
                    total_precip = sum(precipitation_amounts)
                    weather_message += f"🌧 Осадки: в среднем {round(total_precip/len(precipitation_amounts), 1)} мм/день, всего до {round(total_precip, 1)} мм за период\n"
                    
                # Сохраняем агрегированную информацию для отображения на веб-странице
                context.user_data['aggregated_weather'] = {
                    'day_temp_range': [min_day_temp, max_day_temp] if day_temps else None,
                    'night_temp_range': [min_night_temp, max_night_temp] if night_temps else None,
                    'descriptions': list(descriptions),
                    'avg_wind': avg_wind if wind_speeds else None,
                    'max_wind': max_wind if wind_speeds else None,
                    'avg_precip': round(total_precip/len(precipitation_amounts), 1) if precipitation_amounts else None,
                    'total_precip': round(total_precip, 1) if precipitation_amounts else None
                }
                
                # Отправляем агрегированный прогноз погоды
                await update.message.reply_text(weather_message)
                
                # Отправляем вопрос о цели поездки
                message = "Какова цель вашей поездки?"
                
                keyboard = [
                    [InlineKeyboardButton("🏖 Пляжный отдых", callback_data="trip_beach")],
                    [InlineKeyboardButton("🏃 Активный отдых", callback_data="trip_active")],
                    [InlineKeyboardButton("💼 Бизнес", callback_data="trip_business")],
                    [InlineKeyboardButton("🎯 Другое", callback_data="trip_other")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(message, reply_markup=reply_markup)
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
                    "Какова цель вашей поездки?"
                )
                
                keyboard = [
                    [InlineKeyboardButton("🏖 Пляжный отдых", callback_data="trip_beach")],
                    [InlineKeyboardButton("🏃 Активный отдых", callback_data="trip_active")],
                    [InlineKeyboardButton("💼 Бизнес", callback_data="trip_business")],
                    [InlineKeyboardButton("🎯 Другое", callback_data="trip_other")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(message, reply_markup=reply_markup)
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
        """Handle trip type selection."""
        query = update.callback_query
        user = update.effective_user
        
        logger.info("User interaction", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "action": "trip_type_selection",
            "trip_type": query.data
        })
        
        await query.answer()
        
        trip_type = query.data.replace('trip_', '')
        context.user_data['trip_type'] = trip_type
        
        # Generate checklist based on collected information
        logger.info("Generating checklist", extra={
            "user_interaction": True,
            "user_id": user.id,
            "destination": context.user_data['destination'],
            "trip_type": context.user_data['trip_type'],
            "duration": context.user_data['duration'],
            "start_date": context.user_data['start_date']
        })
        
        # Отправим сообщение о том, что генерируем список
        progress_message = await query.message.reply_text(
            "🔄 Генерирую список вещей для вашей поездки...\n"
            "Это может занять несколько секунд."
        )
        
        # Получаем пользователя из базы данных или создаем нового
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
        
        # Generate checklist with LLM (now passing user ID for personalization)
        checklist = await self.checklist_generator.generate_travel_checklist(
            destination=context.user_data['destination'],
            purpose=context.user_data['trip_type'],
            duration=context.user_data['duration'],
            start_date=context.user_data['start_date'],
            weather_info=context.user_data.get('weather_info', {}),
            user_id=user.id  # Pass user ID for personalization
        )
        
        # Create a better title with date, time, purpose and duration
        creation_time = datetime.now().strftime("%H:%M")
        trip_purpose = context.user_data['trip_type']
        trip_title = f"{context.user_data['destination']} с {context.user_data['start_date']} ({trip_purpose} {context.user_data['duration']} дней)"
        
        db_checklist = Checklist(
            title=trip_title,
            type='travel',
            trip_metadata={
                'destination': context.user_data['destination'],
                'trip_type': context.user_data['trip_type'],
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
                f"Для доступа к веб-версии: http://localhost:8000/checklist/{checklist_id}\n"
                f"Если веб-интерфейс недоступен, запустите сервер командой:\n"
                f"python -m web.main"
            )
        
        # Format and send the checklist
        message = (
            f"✅ Ваш список для поездки в {context.user_data['destination']} готов!\n\n"
            "📋 Вот что нужно взять с собой:\n\n"
        )
        
        for category, category_items in checklist['categories'].items():
            message += f"🔹 {category}:\n"
            for item in category_items:
                message += f"  • {item}\n"
            message += "\n"
        
        # Добавляем информацию о веб-интерфейсе
        message += f"{web_message}\n"
        
        keyboard = [
            [InlineKeyboardButton("📝 Редактировать", callback_data=f"edit_{db_checklist.id}")],
            [InlineKeyboardButton("📤 Поделиться", callback_data=f"share_{db_checklist.id}")],
            *([web_button] if web_button else []),  # Добавляем кнопку, только если она есть
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Удаляем сообщение о прогрессе и отправляем результат
        await progress_message.delete()
        await query.message.reply_text(message, reply_markup=reply_markup)
        
        # Clear user data and end conversation
        logger.info("Checklist creation completed", extra={
            "user_interaction": True,
            "user_id": user_db.id,
            "checklist_id": db_checklist.id
        })
        context.user_data.clear()
        return ConversationHandler.END

    async def show_user_lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show user's saved checklists."""
        query = update.callback_query
        user = update.effective_user
        
        # Clear any previous conversation state when viewing lists
        context.user_data.clear()
        
        logger.info("User viewing checklists", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username
        })
        
        await query.answer()
        
        user_db = self.session.query(User).filter_by(
            telegram_id=update.effective_user.id
        ).first()
        
        if not user_db or not user_db.checklists:
            message = "У вас пока нет сохраненных списков."
            keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message, reply_markup=reply_markup)
            return
        
        message = "📋 Ваши списки:\n\n"
        keyboard = []
        
        for checklist in user_db.checklists:
            message += f"• {checklist.title}\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 {checklist.title[:30]}...",
                    callback_data=f"view_{checklist.id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(text=message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error showing user lists: {str(e)}", extra={
                "user_interaction": True,
                "user_id": user.id
            })

    async def view_checklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE, checklist_id: int) -> None:
        """View a specific checklist."""
        query = update.callback_query
        user = update.effective_user
        
        logger.info("User viewing checklist", extra={
            "user_interaction": True,
            "user_id": user.id,
            "username": user.username,
            "checklist_id": checklist_id
        })
        
        # Get the checklist from database
        checklist = self.session.query(Checklist).filter_by(id=checklist_id).first()
        
        if not checklist:
            await query.message.reply_text("Список не найден или был удален.")
            return
        
        # Проверяем, что пользователь владеет этим списком, сравнивая telegram_id
        user_db = self.session.query(User).filter_by(telegram_id=user.id).first()
        if not user_db or checklist.owner_id != user_db.id:
            await query.message.reply_text("У вас нет доступа к этому списку.")
            return
        
        # Format and send the checklist items
        message = f"📋 {checklist.title}\n\n"
        
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
                
            message += "\n"
        
        # Group items by category
        items_by_category = {}
        for item in checklist.items:
            category = item.category or "Прочее"
            if category not in items_by_category:
                items_by_category[category] = []
            items_by_category[category].append(item)
        
        # Format items by category
        for category, items in items_by_category.items():
            message += f"🔹 {category}:\n"
            for item in items:
                message += f"  • {item.title}\n"
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
                f"Для доступа к веб-версии: http://localhost:8000/checklist/{checklist_id}\n"
                f"Если веб-интерфейс недоступен, запустите сервер командой:\n"
                f"python -m web.main"
            )
            
            # Добавляем информацию о веб-интерфейсе
            message += f"{web_message}\n"
        
        keyboard = [
            [InlineKeyboardButton("📝 Редактировать", callback_data=f"edit_{checklist_id}")],
            [InlineKeyboardButton("📤 Поделиться", callback_data=f"share_{checklist_id}")],
            *([web_button] if web_button else []),  # Добавляем кнопку, только если она есть
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(message, reply_markup=reply_markup)
    
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