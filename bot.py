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


# ---------------------------
# Data model and persistence
# ---------------------------
@dataclass
class Task:
    id: int
    text: str
    priority: str = "normal"  # low | normal | high
    done: bool = False
    due_iso: Optional[str] = None  # ISO 8601 datetime string
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
    # If there are no (valid) credentials available, prompt the user to log in.
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
    # This starts a local server and opens the browser for the user to approve
    creds = flow.run_local_server(port=0)
    with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    return creds


def get_calendar_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds)


# ---------------------------
# Command handlers
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_first = update.effective_user.first_name if update.effective_user else "there"
    text = (
        f"Hi {user_first}! I am your Task Assistant.\n\n"
        "Commands:\n"
        "/add <text> — add a task\n"
        "/list — show tasks\n"
        "/done <id> — mark task done\n"
        "/setpriority <id> <low|normal|high> — set priority\n"
        "/due <id> <YYYY-MM-DD [HH:MM]> — set due date\n"
        "/calendar_auth — link Google Calendar\n"
        "/calendar_add <id> — add task as calendar event\n"
        "/calendar_delete <id> — delete calendar event"
    )
    keyboard = [
        [KeyboardButton("➕ Add task"), KeyboardButton("📋 List tasks")],
        [KeyboardButton("ℹ️ Help"), KeyboardButton("🔗 Calendar auth")],
    ]
    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [KeyboardButton(BTN_ADD), KeyboardButton(BTN_LIST)],
        [KeyboardButton(BTN_EDIT)],
        [KeyboardButton(BTN_CAL_ADD), KeyboardButton(BTN_CAL_EDIT)],
        [KeyboardButton(BTN_CAL_AUTH)],
    ]
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text == BTN_LIST:
        await list_tasks(update, context)
        return
    if text == BTN_ADD:
        # Start add wizard
        await update.message.reply_text("Начнём добавление задачи. Введите название задачи:")
        context.user_data["new_task"] = {}
        return
    if text == "ℹ️ Help":
        await start(update, context)
        return
    if text == BTN_CAL_AUTH:
        await calendar_auth(update, context)
        return
    if text == BTN_CAL_ADD:
        await choose_task_for_calendar(update, context)
        return
    if text == BTN_CAL_EDIT:
        await choose_task_for_calendar_edit(update, context)
        return
    if text == BTN_EDIT:
        # Offer edit options via lists (priority/due/done)
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("Изменить приоритет"), KeyboardButton("Изменить дедлайн")],
             [KeyboardButton("Отметить выполненной")],
             [KeyboardButton("Назад к меню")]], resize_keyboard=True)
        await update.message.reply_text("Что изменить?", reply_markup=keyboard)
    # Fallback
    await update.message.reply_text("Не понял. Используйте меню или команды /start /menu.")


# ---------------------------
# Conversational wizards (step-by-step)
# ---------------------------
ADD_TITLE, ADD_DATETIME, ADD_PRIORITY, ADD_CALENDAR = range(4)

# Russian UI labels
BTN_ADD = "➕ Добавить задачу"
BTN_LIST = "📋 Список задач"
BTN_EDIT = "✏️ Изменить задачу"
BTN_CAL_ADD = "📆 Добавить в календарь"
BTN_CAL_EDIT = "🗓 Изменить в календаре"
BTN_CAL_AUTH = "🔗 Привязать календарь"


def build_tasks_keyboard(tasks: List[Dict], action_prefix: str) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for t in tasks[:25]:  # cap to 25 to avoid very large keyboards
        label = f"{'✅' if t.get('done') else '⬜'} #{t.get('id')} • {t.get('text')[:32]}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"{action_prefix}|{t.get('id')}")
        ])
    return InlineKeyboardMarkup(buttons) if buttons else InlineKeyboardMarkup([[InlineKeyboardButton("Нет задач", callback_data="noop")]])


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
    # choose priority (default normal)
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("low", callback_data="prio|low"),
            InlineKeyboardButton("normal", callback_data="prio|normal"),
            InlineKeyboardButton("high", callback_data="prio|high"),
        ]]
    )
    await update.message.reply_text("Выберите приоритет (по умолчанию normal):", reply_markup=keyboard)
    return ADD_PRIORITY


async def add_wizard_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, pr = (query.data or "|").split("|", 1)
    context.user_data["new_task"]["priority"] = pr or "normal"
    # ask add to calendar
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Добавить в календарь", callback_data="addcal|yes"), InlineKeyboardButton("Не добавлять", callback_data="addcal|no")]]
    )
    await query.edit_message_text("Добавить эту задачу в Google Calendar?", reply_markup=keyboard)
    return ADD_CALENDAR


async def add_wizard_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    add_to_calendar = (query.data or "|").endswith("yes")

    # Create task now
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
            class Dummy:
                pass
            context.args = [str(new_id)]
            await calendar_add(update, context)
        except Exception:
            pass

    # Show confirmation and then list tasks
    reply = f"Задача создана: #{new_id} — {new_task['text']} [p:{new_task['priority']}]"
    if new_task.get("due_iso"):
        reply += f" | due {new_task['due_iso']}"
    await query.edit_message_text(reply)
    # Send list
    fake_update = update
    await list_tasks(fake_update, context)
    context.user_data.pop("new_task", None)
    return ConversationHandler.END


# ----- Actions by selecting a task from a list -----
async def choose_task_for_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для отметки как выполненной:", reply_markup=build_tasks_keyboard(tasks, "done"))


async def choose_task_for_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для изменения приоритета:", reply_markup=build_tasks_keyboard(tasks, "prio_task"))


async def choose_task_for_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для установки дедлайна:", reply_markup=build_tasks_keyboard(tasks, "due_task"))


async def choose_task_for_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для добавления в календарь:", reply_markup=build_tasks_keyboard(tasks, "cal_add"))


async def choose_task_for_calendar_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    await update.message.reply_text("Выберите задачу для изменения/удаления события в календаре:", reply_markup=build_tasks_keyboard(tasks, "cal_edit"))


async def on_inline_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    payload = (query.data or "|").split("|", 1)
    action = payload[0]
    arg = payload[1] if len(payload) > 1 else ""

    def find_task(task_id: int) -> Optional[Dict]:
        for t in tasks:
            if t.get("id") == task_id:
                return t
        return None

    if action == "done":
        try:
            task_id = int(arg)
        except ValueError:
            return
        t = find_task(task_id)
        if not t:
            await query.edit_message_text("Задача не найдена")
            return
        t["done"] = True
        write_user_tasks(data)
        await query.edit_message_text(f"Готово ✅ Задача #{task_id} отмечена выполненной")
        return

    if action == "prio_task":
        try:
            task_id = int(arg)
        except ValueError:
            return
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("low", callback_data=f"setprio|{task_id}|low"), InlineKeyboardButton("normal", callback_data=f"setprio|{task_id}|normal"), InlineKeyboardButton("high", callback_data=f"setprio|{task_id}|high")]]
        )
        await query.edit_message_text("Выберите новый приоритет:", reply_markup=keyboard)
        return

    if action == "setprio":
        parts = arg.split("|")
        try:
            task_id = int(parts[0])
        except Exception:
            return
        pr = parts[1] if len(parts) > 1 else "normal"
        t = find_task(task_id)
        if not t:
            await query.edit_message_text("Задача не найдена")
            return
        t["priority"] = pr
        write_user_tasks(data)
        await query.edit_message_text(f"Приоритет обновлён: #{task_id} -> {pr}")
        return

    if action == "due_task":
        try:
            task_id = int(arg)
        except ValueError:
            return
        # ask user to send a date string
        context.user_data["set_due_task_id"] = task_id
        await query.edit_message_text("Отправьте дату в формате YYYY-MM-DD [HH:MM]")
        return

    if action == "cal_add":
        try:
            task_id = int(arg)
        except ValueError:
            return
        # reuse existing calendar_add logic by simulating args
        class Dummy:
            pass
        context.args = [str(task_id)]
        await calendar_add(update, context)
        return

    if action == "cal_edit":
        try:
            task_id = int(arg)
        except ValueError:
            return
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Удалить событие", callback_data=f"caldel|{task_id}")]]
        )
        await query.edit_message_text("Выберите действие с событием календаря:", reply_markup=keyboard)
        return

    if action == "caldel":
        try:
            task_id = int(arg)
        except ValueError:
            return
        context.args = [str(task_id)]
        await calendar_delete(update, context)
        return

    # ignore other/noop
    if action == "noop":
        return


async def on_due_text_after_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "set_due_task_id" not in context.user_data:
        return
    task_id = context.user_data.pop("set_due_task_id")
    due_iso = parse_due_datetime((update.message.text or "").strip().split())
    if not due_iso:
        await update.message.reply_text("Неверный формат даты. Повторите команду /due или используйте /menu → Установить дедлайн.")
        return
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


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /add <task text>")
        return
    text = " ".join(context.args).strip()
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    task = Task(id=get_next_task_id(tasks), text=text)
    tasks.append(asdict(task))
    data[chat_id] = tasks
    write_user_tasks(data)
    await update.message.reply_text(f"Added task #{task.id}: {task.text}")


def format_task_line(t: Dict) -> str:
    status = "✅" if t.get("done") else "⬜"
    pr = t.get("priority", "normal")
    due = t.get("due_iso")
    due_str = f" | due {due}" if due else ""
    return f"{status} {t.get('id')}. {t.get('text')} [p:{pr}]{due_str}"


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    if not tasks:
        await update.message.reply_text("No tasks yet. Add one with /add <text> ✨")
        return
    lines = [format_task_line(t) for t in tasks]
    await update.message.reply_text("\n".join(lines))


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /done <id>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id must be a number")
        return

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    for t in tasks:
        if t.get("id") == task_id:
            t["done"] = True
            write_user_tasks(data)
            await update.message.reply_text(f"Marked task #{task_id} as done ✅")
            return
    await update.message.reply_text("Task not found")


async def set_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setpriority <id> <low|normal|high>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id must be a number")
        return
    pr = context.args[1].lower()
    if pr not in {"low", "normal", "high"}:
        await update.message.reply_text("Priority must be one of: low, normal, high")
        return

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    for t in tasks:
        if t.get("id") == task_id:
            t["priority"] = pr
            write_user_tasks(data)
            await update.message.reply_text(f"Priority set for task #{task_id} -> {pr}")
            return
    await update.message.reply_text("Task not found")


def parse_due_datetime(parts: List[str]) -> Optional[str]:
    # Accept: YYYY-MM-DD or YYYY-MM-DD HH:MM
    try:
        if len(parts) == 1:
            dt = datetime.strptime(parts[0], "%Y-%m-%d")
            # Default time at 09:00
            dt = dt.replace(hour=9, minute=0)
        elif len(parts) >= 2:
            dt = datetime.strptime(" ".join(parts[:2]), "%Y-%m-%d %H:%M")
        else:
            return None
        return dt.isoformat()
    except ValueError:
        return None


async def set_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /due <id> <YYYY-MM-DD [HH:MM]>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id must be a number")
        return
    due_iso = parse_due_datetime(context.args[1:])
    if not due_iso:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM")
        return

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    for t in tasks:
        if t.get("id") == task_id:
            t["due_iso"] = due_iso
            write_user_tasks(data)
            await update.message.reply_text(f"Due date set for task #{task_id} -> {due_iso}")
            # schedule reminder 30 minutes before due, if in the future
            try:
                due_dt = datetime.fromisoformat(due_iso)
                remind_at = due_dt - timedelta(minutes=30)
                if remind_at > datetime.now():
                    context.job_queue.run_once(
                        callback=send_due_reminder,
                        when=remind_at,
                        chat_id=update.effective_chat.id,
                        name=f"reminder-{chat_id}-{task_id}",
                        data={"task_id": task_id, "text": t.get("text")},
                    )
            except Exception:
                pass
            return
    await update.message.reply_text("Task not found")


async def send_due_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if not job:
        return
    data = job.data or {}
    task_id = data.get("task_id")
    text = data.get("text")
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ Reminder: task #{task_id} — {text}")


async def calendar_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not GOOGLE_CREDENTIALS_FILE.exists():
        await update.message.reply_text(
            "Missing credentials.json. Place your Google OAuth client file next to bot.py."
        )
        return
    await update.message.reply_text(
        "Starting Google OAuth flow. A browser window may open on the host machine."
    )
    loop = asyncio.get_event_loop()
    creds = await loop.run_in_executor(None, run_google_oauth_flow)
    if creds:
        await update.message.reply_text("Google Calendar linked ✅")
    else:
        await update.message.reply_text("Google Calendar auth failed")


async def calendar_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /calendar_add <id>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id must be a number")
        return

    creds = get_google_credentials()
    if not creds:
        await update.message.reply_text("Please run /calendar_auth first to link your Google Calendar.")
        return

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        await update.message.reply_text("Task not found")
        return

    due_iso = task.get("due_iso")
    if not due_iso:
        await update.message.reply_text("Set a due date first with /due <id> <YYYY-MM-DD [HH:MM]>")
        return

    try:
        service = get_calendar_service(creds)
        start_dt = datetime.fromisoformat(due_iso)
        end_dt = start_dt + timedelta(hours=1)
        event = {
            "summary": task.get("text"),
            "description": f"Task #{task_id} from Telegram Task Assistant",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": CALENDAR_TIMEZONE},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        task["calendar_event_id"] = created.get("id")
        write_user_tasks(data)
        html_link = created.get("htmlLink")
        await update.message.reply_text(
            f"Event created in Google Calendar ✅\nLink: {html_link}"
        )
    except Exception as e:
        logging.exception("Failed to create calendar event")
        await update.message.reply_text("Failed to create calendar event. Check logs and OAuth setup.")


# New: delete calendar event linked to a task
async def calendar_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /calendar_delete <id>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id must be a number")
        return

    creds = get_google_credentials()
    if not creds:
        await update.message.reply_text("Please run /calendar_auth first to link your Google Calendar.")
        return

    data = read_user_tasks()
    chat_id = str(update.effective_chat.id)
    tasks = data.get(chat_id, [])
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        await update.message.reply_text("Task not found")
        return

    event_id = task.get("calendar_event_id")
    if not event_id:
        await update.message.reply_text("No linked calendar event for this task")
        return

    try:
        service = get_calendar_service(creds)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        task["calendar_event_id"] = None
        write_user_tasks(data)
        await update.message.reply_text(f"Calendar event for task #{task_id} deleted ✅")
    except Exception:
        logging.exception("Failed to delete calendar event")
        await update.message.reply_text("Failed to delete calendar event. Check logs and OAuth setup.")
# ---------------------------
# App bootstrap
# ---------------------------
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. See .env.example and README.")

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Показать помощь и меню"),
                BotCommand("menu", "Показать меню"),
                BotCommand("add", "Добавить задачу (мастер)"),
                BotCommand("list", "Список задач"),
                BotCommand("done", "Отметить выполненной (через список)"),
                BotCommand("setpriority", "Изменить приоритет (через список)"),
                BotCommand("due", "Установить дедлайн (через список)"),
                BotCommand("calendar_auth", "Привязать Google Calendar"),
                BotCommand("calendar_add", "Добавить в календарь (через список)"),
                BotCommand("calendar_delete", "Удалить событие календаря"),
            ]
        )

    app: Application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("setpriority", set_priority))
    app.add_handler(CommandHandler("due", set_due))
    app.add_handler(CommandHandler("calendar_auth", calendar_auth))
    app.add_handler(CommandHandler("calendar_add", calendar_add))
    app.add_handler(CommandHandler("calendar_delete", calendar_delete))
    # Step-by-step conversations and inline actions
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("add", add_wizard_start),
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
    app.add_handler(CommandHandler("done", choose_task_for_done))
    app.add_handler(CommandHandler("setpriority", choose_task_for_priority))
    app.add_handler(CommandHandler("due", choose_task_for_due))
    app.add_handler(CommandHandler("calendar_add", choose_task_for_calendar))
    app.add_handler(CallbackQueryHandler(on_inline_action, pattern=r"^(done|prio_task|setprio|due_task|cal_add|cal_edit|caldel)\|"))
    # Text triggers for menu as well
    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) & (filters.Regex(r"^(Меню|Menu)$")), show_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_selection))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_due_text_after_inline))

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_FILE.touch(exist_ok=True)
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    main()



