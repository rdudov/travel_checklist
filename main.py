import logging
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from models.base import Base
from handlers import ChecklistHandlers

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
engine = create_engine(os.getenv('DATABASE_URL'))
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# States for conversation
WAITING_DESTINATION, WAITING_TRIP_TYPE, WAITING_DURATION = range(3)

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_message = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу вам создавать и управлять чек-листами для путешествий и не только.\n\n"
        "🌍 Для создания списка для путешествия используйте /newtrip\n"
        "📋 Для просмотра ваших списков используйте /mylists\n"
        "📝 Для создания общего чек-листа используйте /newlist\n"
        "❓ Для получения помощи используйте /help"
    )
    
    keyboard = [
        [InlineKeyboardButton("🌍 Новое путешествие", callback_data="new_trip")],
        [InlineKeyboardButton("📋 Мои списки", callback_data="my_lists")],
        [InlineKeyboardButton("📝 Новый чек-лист", callback_data="new_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 Вот что я умею:\n\n"
        "📝 Основные команды:\n"
        "/newtrip - Создать список для путешествия\n"
        "/mylists - Посмотреть ваши сохраненные списки\n"
        "/newlist - Создать общий чек-лист\n"
        "/help - Показать это сообщение\n\n"
        "✨ Дополнительные возможности:\n"
        "- Автоматический подбор вещей с учетом погоды\n"
        "- Сохранение и редактирование списков\n"
        "- Экспорт списков в разных форматах\n"
        "- Обмен списками с сообществом"
    )
    await update.message.reply_text(help_text)

async def new_trip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new trip checklist creation."""
    message = (
        "🌍 Давайте создадим список для путешествия!\n\n"
        "Куда планируете поехать? Укажите город или страну:"
    )
    await update.message.reply_text(message)
    return WAITING_DESTINATION

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses."""
    query = update.callback_query
    await query.answer()

    handlers = ChecklistHandlers(Session())

    if query.data == "new_trip":
        await new_trip(update, context)
    elif query.data == "my_lists":
        await handlers.show_user_lists(update, context)
    elif query.data == "new_list":
        await start_new_list(query, context)
    elif query.data.startswith("trip_"):
        await handlers.handle_trip_type(update, context)
    elif query.data == "main_menu":
        await start(update, context)

async def start_new_list(query: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start creation of a new general checklist."""
    message = (
        "📝 Давайте создадим новый чек-лист!\n\n"
        "Выберите тип списка или создайте свой:"
    )
    keyboard = [
        [InlineKeyboardButton("🛒 Список покупок", callback_data="shopping_list")],
        [InlineKeyboardButton("🔧 Ремонт", callback_data="repair_list")],
        [InlineKeyboardButton("✨ Свой вариант", callback_data="custom_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=message, reply_markup=reply_markup)

def main():
    """Start the bot."""
    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    # Create handlers instance
    handlers = ChecklistHandlers(Session())

    # Add conversation handler for new trip creation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newtrip", new_trip)],
        states={
            WAITING_DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_destination)
            ],
            WAITING_TRIP_TYPE: [
                CallbackQueryHandler(handlers.handle_trip_type, pattern="^trip_")
            ],
            WAITING_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_duration)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text(
        "Операция отменена. Используйте /start для возврата в главное меню."
    )
    return ConversationHandler.END

if __name__ == '__main__':
    main() 