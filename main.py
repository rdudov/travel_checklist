import logging
import os
import json
from datetime import datetime
import threading

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
from constants import WAITING_DESTINATION, WAITING_TRIP_TYPE, WAITING_DURATION, WAITING_START_DATE, WAITING_NEW_ITEM_NAME

# Load environment variables
load_dotenv()

# Проверка загрузки важных переменных окружения
def check_environment_variables():
    """Check if all required environment variables are set and log their status."""
    required_vars = {
        "TELEGRAM_TOKEN": "Telegram Bot Token",
        "DATABASE_URL": "Database URL",
        "OPENAI_API_KEY": "OpenAI API Key",
        "OPENAI_MODEL": "OpenAI Model Name"
    }
    
    optional_vars = {
        "OPENWEATHER_API_KEY": "OpenWeather API Key",
        "NGROK_AUTH_TOKEN": "Ngrok Authentication Token",
        "PUBLIC_WEB_URL": "Public Web URL"
    }
    
    all_required_set = True
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            # Маскируем значение для безопасности в логах
            if var == "OPENAI_API_KEY" or var == "TELEGRAM_TOKEN":
                masked_value = f"{value[:3]}...{value[-3:]}" if len(value) > 6 else "***"
                module_logger.info(f"{description} ({var}) is set: {masked_value}")
            else:
                module_logger.info(f"{description} ({var}) is set: {value}")
        else:
            module_logger.error(f"{description} ({var}) is NOT SET!")
            all_required_set = False
    
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            if var == "NGROK_AUTH_TOKEN":
                masked_value = f"{value[:3]}...{value[-3:]}" if len(value) > 6 else "***"
                module_logger.info(f"{description} ({var}) is set: {masked_value}")
            else:
                module_logger.info(f"{description} ({var}) is set: {value}")
        else:
            module_logger.warning(f"{description} ({var}) is not set (optional)")
    
    return all_required_set

# Custom Formatter to include extra fields
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            'timestamp': self.formatTime(record, self.datefmt),
            'name': record.name,
            'level': record.levelname,
            'message': record.getMessage(),
        }
        if hasattr(record, 'user_interaction') and record.user_interaction:
            # Add all extra fields if user_interaction is True
            extra_data = {k: v for k, v in record.__dict__.items() 
                          if k not in log_entry and k not in ['args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName']}
            log_entry.update(extra_data)
        return json.dumps(log_entry, ensure_ascii=False)

# Configure handlers with the custom formatter
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Remove default basicConfig handlers if any were added
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

formatter = JsonFormatter()

# File Handler
fh = logging.FileHandler("bot.log", encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)

# Stream Handler (Console)
sh = logging.StreamHandler()
sh.setLevel(logging.INFO)
sh.setFormatter(formatter)
logger.addHandler(sh)

# Re-get the specific logger if needed elsewhere, though configuring the root logger often suffices
module_logger = logging.getLogger(__name__)

# Add a filter to log user interactions (applied to handlers or logger)
class UserInteractionFilter(logging.Filter):
    def filter(self, record):
        return "user_interaction" in record.__dict__

# Apply filter to handlers
fh.addFilter(UserInteractionFilter())
sh.addFilter(UserInteractionFilter())

# Database setup
engine = create_engine(os.getenv('DATABASE_URL'))
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

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
    
    # Handle both direct commands and callback queries
    if update.callback_query:
        await update.callback_query.message.reply_text(welcome_message, reply_markup=reply_markup)
    else:
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
    
    if update.callback_query:
        await update.callback_query.message.reply_text(message)
    else:
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
        try:
            await query.message.reply_text("Возвращаемся в главное меню...")
            await start(update, context)
        except Exception as e:
            module_logger.error(f"Error handling main_menu button: {str(e)}", 
                       extra={"user_interaction": True, "callback_data": query.data})
    elif query.data.startswith("edit_"):
        checklist_id = int(query.data.split("_")[1])
        await handlers.edit_checklist(update, context, checklist_id)
    elif query.data.startswith("share_"):
        checklist_id = int(query.data.split("_")[1])
        await handlers.share_checklist(update, context, checklist_id)
    elif query.data.startswith("view_"):
        checklist_id = int(query.data.split("_")[1])
        await handlers.view_checklist(update, context, checklist_id)
    elif query.data.startswith("category_"):
        await handlers.handle_category_selection(update, context)
    elif query.data.startswith("add_item_"):
        await handlers.handle_add_item(update, context)
    elif query.data.startswith("add_to_category_"):
        await handlers.handle_add_to_category(update, context)
    elif query.data.startswith("delete_item_"):
        await handlers.handle_delete_item(update, context)
    else:
        module_logger.warning("Unknown callback data", 
                    extra={"user_interaction": True, "callback_data": query.data})

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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "😔 Произошла ошибка при обработке запроса. Пожалуйста, попробуйте снова или используйте /start для возврата в главное меню."
        )

def main():
    """Start the bot."""
    # Check environment variables before starting
    all_vars_set = check_environment_variables()
    if not all_vars_set:
        module_logger.warning("Some required environment variables are missing. The bot may not function correctly.")
    
    # Start web server in a separate thread
    start_web_server()
    
    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    # Create handlers instance
    handlers = ChecklistHandlers(Session())

    # Add conversation handler for new trip creation
    trip_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("newtrip", new_trip),
            CallbackQueryHandler(new_trip, pattern="^new_trip$")
        ],
        states={
            WAITING_DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_destination)
            ],
            WAITING_START_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_start_date)
            ],
            WAITING_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_duration)
            ],
            WAITING_TRIP_TYPE: [
                CallbackQueryHandler(handlers.handle_trip_type, pattern="^trip_")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CallbackQueryHandler(button_handler, pattern="^(main_menu|my_lists|new_list)$"),
        ],
        name="trip_conversation",
    )
    
    # Add conversation handler for item editing
    edit_item_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.handle_add_to_category, pattern="^add_to_category_")
        ],
        states={
            WAITING_NEW_ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_new_item_name)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler, pattern="^edit_"),
        ],
        name="edit_item_conversation",
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("mylists", my_lists_command))
    application.add_handler(trip_conv_handler)
    application.add_handler(edit_item_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text(
        "Операция отменена. Используйте /start для возврата в главное меню."
    )
    return ConversationHandler.END

async def my_lists_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mylists command."""
    handlers = ChecklistHandlers(Session())
    # Create a dummy callback query to reuse show_user_lists
    class DummyCallbackQuery:
        def __init__(self, message):
            self.message = message
            
        async def answer(self):
            pass
            
        async def edit_message_text(self, text, reply_markup=None):
            await self.message.reply_text(text, reply_markup=reply_markup)
    
    update.callback_query = DummyCallbackQuery(update.message)
    await handlers.show_user_lists(update, context)

def start_web_server():
    """Start the FastAPI web server in a separate thread."""
    def run_server():
        try:
            from web.main import app
            import uvicorn
            module_logger.info("Starting web server...", extra={"user_interaction": True})
            uvicorn.run(app, host="0.0.0.0", port=8000)
        except Exception as e:
            module_logger.error(f"Error starting web server: {str(e)}", extra={"user_interaction": True})
    
    # Try to start ngrok tunnel if available
    try:
        import pyngrok.ngrok as ngrok
        # Check if NGROK_AUTH_TOKEN is set in .env
        ngrok_token = os.getenv('NGROK_AUTH_TOKEN')
        if ngrok_token:
            ngrok.set_auth_token(ngrok_token)
            # Start a tunnel to port 8000
            http_tunnel = ngrok.connect(8000)
            public_url = http_tunnel.public_url
            module_logger.info(f"ngrok tunnel established: {public_url}", 
                         extra={"user_interaction": True, "public_url": public_url})
            # Set an environment variable with the public URL for the handlers to use
            os.environ['PUBLIC_WEB_URL'] = public_url
        else:
            module_logger.info("NGROK_AUTH_TOKEN not set, skipping ngrok tunnel", 
                         extra={"user_interaction": True})
    except ImportError:
        module_logger.info("pyngrok not installed, skipping ngrok tunnel. Install with: pip install pyngrok", 
                    extra={"user_interaction": True})
    except Exception as e:
        module_logger.error(f"Error setting up ngrok tunnel: {str(e)}", 
                     extra={"user_interaction": True})
    
    # Start the server in a daemon thread
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    module_logger.info("Web server thread started", extra={"user_interaction": True})

if __name__ == '__main__':
    main() 