import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

# Google Calendar imports
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


# ---------------------------
# Configuration and constants
# ---------------------------
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "UTC")
DATA_FILE = Path(__file__).with_name("storage.json")
GOOGLE_TOKEN_FILE = Path(__file__).with_name("token.json")
GOOGLE_CREDENTIALS_FILE = Path(__file__).with_name("credentials.json")

# If modifying these scopes, delete the file token.json.
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# UI Labels
BTN_ADD = "➕ Добавить задачу"
BTN_LIST = "📋 Список задач"
BTN_EDIT = "✏️ Изменить задачу"
BTN_CAL_ADD = "📆 Добавить в календарь"
BTN_CAL_EDIT = "🗓 Изменить в календаре"
BTN_CAL_AUTH = "🔗 Привязать календарь"

# Conversation states
ADD_TITLE, ADD_DATETIME, ADD_PRIORITY, ADD_CALENDAR = range(4)
EDIT_CHOOSE_ACTION, EDIT_CHOOSE_TASK_PRIO, EDIT_CHOOSE_TASK_DUE = range(4, 7)


# ---------------------------
# Data model and persistence
# ---------------------------
@dataclass
class Task:
    id: int
    text: str
    priority: str = "normal"
    done: bool = False
    due_iso: Optional[str] = None
    calendar_event_id: Optional[str] = None


def read_user_tasks() -> Dict[str, List[Dict]]:
    if not DATA_FILE.exists():
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_user_tasks(data: Dict[str, List[Dict]]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_next_task_id(tasks: List[Dict]) -> int:
    if not tasks:
        return 1
    return max(t.get("id", 0) for t in tasks) + 1


# ---------------------------
# Google Calendar helpers
# ---------------------------
def get_google_credentials() -> Optional[Credentials]:
    creds: Optional[Credentials] = None
    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        except Exception:
            creds = None
    return creds


def run_google_oauth_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)
    with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    return creds


def get_calendar_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds)


def parse_due_datetime(parts: List[str]) -> Optional[str]:
    try:
        if len(parts) == 1:
            dt = datetime.strptime(parts[0], "%Y-%m-%d")
            dt = dt.replace(hour=9, minute=0)
        elif len(parts) >= 2:
            dt = datetime.strptime(" ".join(parts[:2]), "%Y-%m-%d %H:%M")
        else:
            return None
        return dt.isoformat()
    except ValueError:
        return None


def build_tasks_keyboard(tasks: List[Dict], action_prefix: str) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for t in tasks[:25]:
        label = f"{'✅' if t.get('done') else '⬜'} #{t.get('id')} • {t.get('text')[:32]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"{action_prefix}|{t.get('id')}")])
    return InlineKeyboardMarkup(buttons) if buttons else InlineKeyboardMarkup([[InlineKeyboardButton("Нет задач", callback_data="noop")]])


def format_task_line(t: Dict) -> str:
    status = "✅" if t.get("done") else "⬜"
    pr = t.get("priority", "normal")
    due = t.get("due_iso")
    due_str = f" | до {due}" if due else ""
    return f"{status} #{t.get('id')}. {t.get('text')} [p:{pr}]{due_str}"


# ---------------------------
# Main menu and commands
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_first = update.effective_user.first_name if update.effective_user else "Пользователь"
    text = (
        f"Привет, {user_first}! Я твой помощник по задачам.\n\n"
        "Используй меню ниже для работы с задачами."
    )
    keyboard = [
        [KeyboardButton(BTN_ADD), KeyboardButton(BTN_LIST)],
        [KeyboardButton(BTN_EDIT)],
        [KeyboardButton(BTN_CAL_ADD), KeyboardButton(BTN_CAL_EDIT)],
        [KeyboardButton(BTN_CAL_AUTH)],
    ]
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [KeyboardButton(BTN_ADD), KeyboardButton(BTN_LIST)],
        [KeyboardButton(BTN_EDIT)],
        [KeyboardButton(BTN_CAL_ADD), KeyboardButton(BTN_CAL_EDIT)],
        [KeyboardButton(BTN_CAL_AUTH)],
    ]
    await update.message.reply_text("Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))


# ---------------------------
# Add Task Wizard
# ---------------------------
async def add_wizard_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Введите название задачи:")
    context.user_data["new_task"] = {}
    return ADD_TITLE


async def add_wizard_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Название пустое. Введите название задачи:")
        return ADD_TITLE
    context.user_data["new_task"]["text"] = text
    await update.message.reply_text("Укажите дату и время в формате YYYY-MM-DD [HH:MM]:")
    return ADD_DATETIME


async def add_wizard_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    due_iso = parse_due_datetime((update.message.text or "").strip().split())
    if not due_iso:
        await update.message.reply_text("Неверный формат. Введите YYYY-MM-DD [HH:MM]:")
        return ADD_DATETIME
    context.user_data["new_task"]["due_iso"] = due_iso
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("low", callback_data="prio|low"),
        InlineKeyboardButton("normal", callback_data="prio|normal"),
        InlineKeyboardButton("high", callback_data="prio|high"),
    ]])
    await update.message.reply_text("Выберите приоритет (по умолчанию normal):", reply_markup=keyboard)
    return ADD_PRIORITY


async def add_wizard_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, pr = (query.data or "|").split("|", 1)
    context.user_data["new_task"]["priority"] = pr or "normal"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Добавить в календарь", callback_data="addcal|yes"),
        InlineKeyboardButton("Не добавлять", callback_data="addcal|no")
    ]])
    await query.edit_message_text("Добавить эту задачу в Google Calendar?", reply_markup=keyboard)
    return ADD_CALENDAR


async def add_wizard_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    add_to_calendar = (query.data or "|").endswith("yes")

    # Create task
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    new_id = get_next_task_id(tasks)
    new_task = {
        "id": new_id,
        "text": context.user_data.get("new_task", {}).get("text", ""),
        "priority": context.user_data.get("new_task", {}).get("priority", "normal"),
        "done": False,
        "due_iso": context.user_data.get("new_task", {}).get("due_iso"),
        "calendar_event_id": None,
    }
    tasks.append(new_task)
    data[chat_id] = tasks
    write_user_tasks(data)

    # Optionally add to calendar
    if add_to_calendar:
        try:
            creds = get_google_credentials()
            if creds:
                service = get_calendar_service(creds)
                start_dt = datetime.fromisoformat(new_task["due_iso"])
                end_dt = start_dt + timedelta(hours=1)
                event = {
                    "summary": new_task["text"],
                    "description": f"Задача #{new_id}",
                    "start": {"dateTime": start_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE},
                    "end": {"dateTime": end_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE},
                }
                created = service.events().insert(calendarId="primary", body=event).execute()
                new_task["calendar_event_id"] = created.get("id")
                write_user_tasks(data)
        except Exception as e:
            logging.exception("Failed to add to calendar")

    # Show confirmation
    reply = f"✅ Задача #{new_id} создана: {new_task['text']} [p:{new_task['priority']}]"
    if new_task.get("due_iso"):
        reply += f" | до {new_task['due_iso']}"
    await query.edit_message_text(reply)

    # Show list of tasks
    await list_tasks(update, context)
    context.user_data.pop("new_task", None)
    return ConversationHandler.END


# ---------------------------
# List and display
# ---------------------------
async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    if not tasks:
        await update.message.reply_text("Пока нет задач. Добавьте первую через меню!")
        return
    lines = [format_task_line(t) for t in tasks]
    await update.message.reply_text("\n".join(lines))


# ---------------------------
# Calendar operations
# ---------------------------
async def calendar_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Привязка Google Calendar через ссылку"""
    if not GOOGLE_CREDENTIALS_FILE.exists():
        await update.message.reply_text("Не найден credentials.json. Разместите файл OAuth рядом с calendar_bot.py.")
        return
    
    try:
        # Создаем flow для получения URL
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GOOGLE_CREDENTIALS_FILE), 
            GOOGLE_SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Для ручного ввода кода
        )
        
        # Получаем URL авторизации
        auth_url, _ = flow.authorization_url(prompt='consent')
        
        await update.message.reply_text(
            f"🔗 Перейдите по ссылке для авторизации:\n\n{auth_url}\n\n"
            "После авторизации скопируйте код и отправьте его мне."
        )
        
        # Сохраняем flow в context для последующего использования
        context.user_data['oauth_flow'] = flow
        context.user_data['awaiting_oauth_code'] = True
        
    except Exception as e:
        logging.exception("Failed to start OAuth flow")
        await update.message.reply_text("Ошибка при создании ссылки авторизации.")
        
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()

    # Handle OAuth code
    if context.user_data.get('awaiting_oauth_code'):
        try:
            flow = context.user_data.get('oauth_flow')
            if flow:
                # Получаем токен по коду
                flow.fetch_token(code=text)
                creds = flow.credentials
                
                # Сохраняем токен
                with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
                    token.write(creds.to_json())
                
                await update.message.reply_text("✅ Google Calendar успешно привязан!")
                
                # Очищаем context
                context.user_data.pop('oauth_flow', None)
                context.user_data.pop('awaiting_oauth_code', None)
                return
        except Exception as e:
            logging.exception("Failed to process OAuth code")
            await update.message.reply_text(
                "❌ Ошибка при обработке кода. Попробуйте еще раз или используйте команду /menu"
            )
            context.user_data.pop('oauth_flow', None)
            context.user_data.pop('awaiting_oauth_code', None)
            return

    # Handle due date entry
    if "set_due_task_id" in context.user_data:
        # ... остальной код


async def choose_task_for_calendar_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для добавления в календарь:", reply_markup=build_tasks_keyboard(tasks, "cal_add"))


async def choose_task_for_calendar_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для изменения/удаления события в календаре:", reply_markup=build_tasks_keyboard(tasks, "cal_edit"))


# ---------------------------
# Edit task operations
# ---------------------------
async def choose_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Изменить приоритет", callback_data="editact|prio"),
        InlineKeyboardButton("Установить дедлайн", callback_data="editact|due"),
        InlineKeyboardButton("Отметить выполненной", callback_data="editact|done"),
    ]])
    await update.message.reply_text("Что изменить?", reply_markup=keyboard)


async def handle_edit_action(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.answer()
    _, action = (query.data or "|").split("|", 1)
    data = read_user_tasks()
    chat_id = str(query.from_user.id)
    tasks = data.get(chat_id, [])
    
    if action == "prio":
        await query.edit_message_text("Выберите задачу:", reply_markup=build_tasks_keyboard(tasks, "setprio_task"))
    elif action == "due":
        await query.edit_message_text("Выберите задачу:", reply_markup=build_tasks_keyboard(tasks, "setdue_task"))
    elif action == "done":
        await query.edit_message_text("Выберите задачу:", reply_markup=build_tasks_keyboard(tasks, "done_task"))


# ---------------------------
# Inline callback handlers
# ---------------------------
async def on_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    payload = (query.data or "|").split("|", 1)
    action = payload[0]
    arg = payload[1] if len(payload) > 1 else ""

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])

    def find_task(task_id: int):
        for t in tasks:
            if t.get("id") == task_id:
                return t
        return None

    # Done task
    if action == "done_task":
        try:
            task_id = int(arg)
            t = find_task(task_id)
            if t:
                t["done"] = True
                write_user_tasks(data)
                await query.edit_message_text(f"✅ Задача #{task_id} отмечена выполненной")
        except ValueError:
            pass
        return

    # Change priority - choose task
    if action == "setprio_task":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("low", callback_data=f"setprio|{arg}|low"),
            InlineKeyboardButton("normal", callback_data=f"setprio|{arg}|normal"),
            InlineKeyboardButton("high", callback_data=f"setprio|{arg}|high"),
        ]])
        await query.edit_message_text("Выберите приоритет:", reply_markup=keyboard)
        return

    # Change priority - execute
    if action == "setprio":
        parts = arg.split("|")
        try:
            task_id = int(parts[0])
            pr = parts[1] if len(parts) > 1 else "normal"
            t = find_task(task_id)
            if t:
                t["priority"] = pr
                write_user_tasks(data)
                await query.edit_message_text(f"Приоритет обновлён: #{task_id} -> {pr}")
        except Exception:
            pass
        return

    # Set due - ask date
    if action == "setdue_task":
        try:
            task_id = int(arg)
            context.user_data["set_due_task_id"] = task_id
            await query.edit_message_text("Отправьте дату в формате YYYY-MM-DD [HH:MM]")
        except ValueError:
            pass
        return

    # Calendar add
    if action == "cal_add":
        try:
            task_id = int(arg)
            t = find_task(task_id)
            if not t or not t.get("due_iso"):
                await query.edit_message_text("У задачи нет дедлайна. Установите его сначала.")
                return
            creds = get_google_credentials()
            if not creds:
                await query.edit_message_text("Сначала привяжите Google Calendar.")
                return
            service = get_calendar_service(creds)
            start_dt = datetime.fromisoformat(t["due_iso"])
            end_dt = start_dt + timedelta(hours=1)
            event = {"summary": t["text"], "description": f"Задача #{task_id}", "start": {"dateTime": start_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE}, "end": {"dateTime": end_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE}}
            created = service.events().insert(calendarId="primary", body=event).execute()
            t["calendar_event_id"] = created.get("id")
            write_user_tasks(data)
            await query.edit_message_text(f"✅ Событие создано в Google Calendar\n{created.get('htmlLink')}")
        except Exception as e:
            logging.exception("Failed calendar add")
            await query.edit_message_text("Ошибка при добавлении в календарь.")
        return

    # Calendar edit/delete
    if action == "cal_edit":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Удалить событие", callback_data=f"cal_delete|{arg}")
        ]])
        await query.edit_message_text("Выберите действие:", reply_markup=keyboard)
        return

    if action == "cal_delete":
        try:
            task_id = int(arg)
            t = find_task(task_id)
            if not t or not t.get("calendar_event_id"):
                await query.edit_message_text("У задачи нет связанного события календаря.")
                return
            creds = get_google_credentials()
            if not creds:
                await query.edit_message_text("Сначала привяжите Google Calendar.")
                return
            service = get_calendar_service(creds)
            service.events().delete(calendarId="primary", eventId=t["calendar_event_id"]).execute()
            t["calendar_event_id"] = None
            write_user_tasks(data)
            await query.edit_message_text(f"✅ Событие календаря удалено для задачи #{task_id}")
        except Exception as e:
            logging.exception("Failed calendar delete")
            await query.edit_message_text("Ошибка при удалении события.")
        return

    # Edit action selection
    if action == "editact":
        await handle_edit_action(query, context)
        return


# ---------------------------
# Text message handlers
# ---------------------------
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()

    # Handle due date entry
    if "set_due_task_id" in context.user_data:
        task_id = context.user_data.pop("set_due_task_id")
        due_iso = parse_due_datetime(text.split())
        if due_iso:
            data = read_user_tasks()
            chat_id = str(update.effective_chat.id)
            tasks = data.get(chat_id, [])
            for t in tasks:
                if t.get("id") == task_id:
                    t["due_iso"] = due_iso
                    write_user_tasks(data)
                    await update.message.reply_text(f"Дедлайн установлен для задачи #{task_id}: {due_iso}")
                    return
            await update.message.reply_text("Задача не найдена")
        else:
            await update.message.reply_text("Неверный формат. Введите YYYY-MM-DD [HH:MM]")
        return

    # Handle menu buttons
    if text == BTN_ADD:
        await add_wizard_start(update, context)
        return
    if text == BTN_LIST:
        await list_tasks(update, context)
        return
    if text == BTN_EDIT:
        await choose_edit_action(update, context)
        return
    if text == BTN_CAL_ADD:
        await choose_task_for_calendar_add(update, context)
        return
    if text == BTN_CAL_EDIT:
        await choose_task_for_calendar_edit(update, context)
        return
    if text == BTN_CAL_AUTH:
        await calendar_auth(update, context)
        return

    # Fallback
    await update.message.reply_text("Не понял. Используйте кнопки меню.")


# ---------------------------
# App bootstrap
# ---------------------------
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. See .env.example and README.")

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Показать меню"),
            BotCommand("menu", "Показать меню"),
        ])

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("list", list_tasks))

    # Add wizard conversation
    app.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & filters.Regex(f"^{BTN_ADD}$"), add_wizard_start),
        ],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_wizard_title)],
            ADD_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_wizard_datetime)],
            ADD_PRIORITY: [CallbackQueryHandler(add_wizard_priority, pattern=r"^prio\|")],
            ADD_CALENDAR: [CallbackQueryHandler(add_wizard_calendar, pattern=r"^addcal\|")],
        },
        fallbacks=[],
    ))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(on_inline_callback, pattern=r"^.+"))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_FILE.touch(exist_ok=True)
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    main()

