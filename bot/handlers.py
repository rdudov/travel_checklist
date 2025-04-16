from datetime import datetime
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from models.checklist import User, Checklist, ChecklistItem
from services.weather import WeatherService
from services.checklist_generator import ChecklistGenerator
from sqlalchemy.orm import Session

class ChecklistHandlers:
    def __init__(self, session: Session):
        self.session = session
        self.weather_service = WeatherService()
        self.checklist_generator = ChecklistGenerator()

    async def handle_destination(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle destination input for new trip checklist."""
        destination = update.message.text
        context.user_data['destination'] = destination

        # Get weather info for the destination
        try:
            weather_info = await self.weather_service.get_weather(destination)
            context.user_data['weather_info'] = weather_info
            
            message = (
                f"🌍 Отлично! Я нашел информацию о погоде в {destination}:\n\n"
                f"🌡 Температура: {weather_info['temp']}°C\n"
                f"☁️ Погода: {weather_info['description']}\n\n"
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
            context.user_data['state'] = 'waiting_trip_type'
            
        except Exception as e:
            await update.message.reply_text(
                "😔 Извините, не удалось получить информацию о погоде. "
                "Пожалуйста, проверьте название города и попробуйте снова."
            )

    async def handle_trip_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle trip type selection."""
        query = update.callback_query
        await query.answer()
        
        trip_type = query.data.replace('trip_', '')
        context.user_data['trip_type'] = trip_type
        
        message = "На сколько дней планируется поездка? Введите число:"
        await query.edit_message_text(text=message)
        context.user_data['state'] = 'waiting_duration'

    async def handle_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle trip duration input."""
        try:
            duration = int(update.message.text)
            if duration <= 0:
                raise ValueError("Duration must be positive")
                
            context.user_data['duration'] = duration
            
            # Generate checklist based on collected information
            checklist = await self.checklist_generator.generate_travel_checklist(
                destination=context.user_data['destination'],
                trip_type=context.user_data['trip_type'],
                duration=duration,
                weather_info=context.user_data['weather_info']
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
            
            db_checklist = Checklist(
                title=f"Поездка в {context.user_data['destination']}",
                type='travel',
                metadata={
                    'destination': context.user_data['destination'],
                    'trip_type': context.user_data['trip_type'],
                    'duration': duration,
                    'weather_info': context.user_data['weather_info']
                },
                owner_id=user.id
            )
            self.session.add(db_checklist)
            self.session.commit()
            
            # Add checklist items
            for item in checklist['items']:
                checklist_item = ChecklistItem(
                    title=item['title'],
                    description=item.get('description'),
                    category=item.get('category'),
                    checklist_id=db_checklist.id,
                    order=item.get('order', 0)
                )
                self.session.add(checklist_item)
            self.session.commit()
            
            # Format and send the checklist
            message = (
                f"✅ Ваш список для поездки в {context.user_data['destination']} готов!\n\n"
                "📋 Вот что нужно взять с собой:\n\n"
            )
            
            for category, items in checklist['items_by_category'].items():
                message += f"🔹 {category}:\n"
                for item in items:
                    message += f"  • {item['title']}\n"
                message += "\n"
            
            keyboard = [
                [InlineKeyboardButton("📝 Редактировать", callback_data=f"edit_{db_checklist.id}")],
                [InlineKeyboardButton("📤 Поделиться", callback_data=f"share_{db_checklist.id}")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            
            # Clear user data
            context.user_data.clear()
            
        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите корректное число дней (больше 0)."
            )
        except Exception as e:
            await update.message.reply_text(
                "😔 Произошла ошибка при создании списка. Пожалуйста, попробуйте снова."
            )

    async def show_user_lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show user's saved checklists."""
        query = update.callback_query
        await query.answer()
        
        user = self.session.query(User).filter_by(
            telegram_id=update.effective_user.id
        ).first()
        
        if not user or not user.checklists:
            message = "У вас пока нет сохраненных списков."
            keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message, reply_markup=reply_markup)
            return
        
        message = "📋 Ваши списки:\n\n"
        keyboard = []
        
        for checklist in user.checklists:
            message += f"• {checklist.title}\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 {checklist.title}",
                    callback_data=f"view_{checklist.id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text=message, reply_markup=reply_markup) 