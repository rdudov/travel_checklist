import logging
from datetime import datetime
from typing import Dict, Any
import re
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# Import states from constants.py
from constants import WAITING_DESTINATION, WAITING_TRIP_TYPE, WAITING_DURATION, WAITING_START_DATE

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

        # Get weather info for the destination
        try:
            logger.info("Fetching weather info", extra={
                "user_interaction": True,
                "user_id": user.id,
                "destination": destination
            })
            
            weather_info = await self.weather_service.get_weather_forecast(destination)
            context.user_data['weather_info'] = weather_info
            
            logger.info("Weather info received", extra={
                "user_interaction": True,
                "user_id": user.id,
                "destination": destination,
                "temperature": weather_info['forecast'][0]['avg_temp']
            })
            
            # Форматируем подробный прогноз погоды на несколько дней
            forecast_days = min(5, len(weather_info['forecast']))  # Показываем до 5 дней прогноза
            weather_message = f"🌍 Прогноз погоды в {destination}:\n\n"
            
            for i in range(forecast_days):
                day_forecast = weather_info['forecast'][i]
                date = day_forecast.get('date', f"День {i+1}")
                weather_message += (
                    f"📅 {date}:\n"
                    f"  🌡 Температура: {day_forecast['avg_temp']}°C\n"
                    f"  ☁️ Погода: {', '.join(day_forecast['descriptions'])}\n"
                )
                # Если доступна информация о ветре, добавляем ее
                if 'wind_speed' in day_forecast:
                    weather_message += f"  💨 Ветер: {day_forecast['wind_speed']} м/с\n"
                # Если доступна информация об осадках, добавляем ее
                if 'precipitation' in day_forecast:
                    weather_message += f"  🌧 Осадки: {day_forecast['precipitation']} мм\n"
                weather_message += "\n"
            
            # Отправляем подробный прогноз погоды
            await update.message.reply_text(weather_message)
            
            # Отправляем вопрос о цели поездки
            message = (
                f"Отлично! Я нашел информацию о погоде в {destination}.\n\n"
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
            
        except Exception as e:
            logger.error("Error getting weather info", extra={
                "user_interaction": True,
                "user_id": user.id,
                "destination": destination,
                "error": str(e)
            })
            await update.message.reply_text(
                "😔 Извините, не удалось получить информацию о погоде. "
                "Пожалуйста, проверьте название города и попробуйте снова."
            )

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
        
        # Вместо замены сообщения о погоде, отправим новое сообщение с вопросом о длительности
        message = (
            f"Вы выбрали: {trip_type}\n\n"
            "На сколько дней планируется поездка? Введите число:"
        )
        await query.message.reply_text(text=message)
        return WAITING_DURATION

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
            required_data = ['destination', 'trip_type', 'weather_info']
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
            
            # Ask for trip start date
            message = (
                "Когда планируете поездку? Укажите дату начала в формате ДД.ММ.ГГГГ\n"
                "Например: 25.06.2025"
            )
            await update.message.reply_text(message)
            return WAITING_START_DATE
            
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
            
            # Generate checklist based on collected information
            logger.info("Generating checklist", extra={
                "user_interaction": True,
                "user_id": user.id,
                "destination": context.user_data['destination'],
                "trip_type": context.user_data['trip_type'],
                "duration": context.user_data['duration'],
                "start_date": date_text
            })
            
            checklist = await self.checklist_generator.generate_travel_checklist(
                destination=context.user_data['destination'],
                purpose=context.user_data['trip_type'],
                duration=context.user_data['duration'],
            )
            
            # Save checklist to database
            user = self.session.query(User).filter_by(
                telegram_id=update.effective_user.id
            ).first()
            
            if not user:
                user = User(
                    telegram_id=update.effective_user.id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    last_name=update.effective_user.last_name
                )
                self.session.add(user)
                self.session.commit()
            
            # Create a better title with date, time, purpose and duration
            creation_time = datetime.now().strftime("%H:%M")
            trip_purpose = context.user_data['trip_type']
            trip_title = f"{context.user_data['destination']} с {date_text} ({trip_purpose} {context.user_data['duration']} дней)"
            
            db_checklist = Checklist(
                title=trip_title,
                type='travel',
                trip_metadata={
                    'destination': context.user_data['destination'],
                    'trip_type': context.user_data['trip_type'],
                    'duration': context.user_data['duration'],
                    'start_date': date_text,
                    'weather': context.user_data.get('weather_info', {})
                },
                owner_id=user.id
            )
            self.session.add(db_checklist)
            self.session.commit()
            
            logger.info("Checklist saved", extra={
                "user_interaction": True,
                "user_id": user.id,
                "checklist_id": db_checklist.id
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
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            
            # Clear user data and end conversation
            logger.info("Checklist creation completed", extra={
                "user_interaction": True,
                "user_id": user.id,
                "checklist_id": db_checklist.id
            })
            context.user_data.clear()
            return ConversationHandler.END
            
        except Exception as e:
            logger.error("Error creating checklist", extra={
                "user_interaction": True,
                "user_id": user.id,
                "error": str(e)
            })
            await update.message.reply_text(
                "😔 Произошла ошибка при создании списка. Пожалуйста, попробуйте снова."
            )
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
        
        keyboard = [
            [InlineKeyboardButton("📝 Редактировать", callback_data=f"edit_{checklist_id}")],
            [InlineKeyboardButton("📤 Поделиться", callback_data=f"share_{checklist_id}")],
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
        
        # Placeholder for full edit functionality
        message = (
            "🔧 Функция редактирования списка находится в разработке.\n\n"
            "Скоро вы сможете добавлять, удалять и изменять элементы списка!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к списку", callback_data=f"view_{checklist_id}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
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