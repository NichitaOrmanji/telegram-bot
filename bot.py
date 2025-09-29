# bot.py
import os
import json
from dotenv import load_dotenv
import random
from telegram import InputFile
from telegram.error import BadRequest
from telegram import Update
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest
from datetime import datetime, timedelta, time as dt_time

# ------------------- НАСТРОЙКИ -------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

TASKS_FILE = "tasks.json"
REMINDERS_FILE = "reminders.json"
BIRTHDAYS_FILE = "birthdays.json"
EVENTS_FILE = "events.json"
TASKS_HISTORY_FILE = "tasks_history.json"

# ------------------- УТИЛИТЫ -------------------
def load_data(file):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_id_from_update(update: Update) -> str:
    """Возвращаем строковый user_id (используем effective_user)"""
    if update.effective_user:
        return str(update.effective_user.id)
    # fallback
    if hasattr(update, "callback_query") and update.callback_query:
        return str(update.callback_query.from_user.id)
    return "unknown"

def main_menu_keyboard():
    keyboard = [
        ["➕ Добавить задачу", "📋 Мои задачи"],
        ["⏰ Добавить напоминание", "🔔 Мои напоминания"],
        ["📅 Мой день", "📆 Мой месяц"],
        ["🎉 События", "📖 5 минут"] 
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def send_or_edit(update: Update, text: str, reply_markup=None):
    """
    Безопасно отправляет или редактирует сообщение.
    Важно: callback_query.edit_message_text принимает только InlineKeyboardMarkup (inline).
    Если вызываем edit из callback и передан ReplyKeyboardMarkup (main menu), то:
      - редактируем текущее сообщение без клавиатуры
      - и отправляем новое сообщение с main menu (ReplyKeyboardMarkup)
    Также аккуратно ловим BadRequest("Message is not modified") и игнорируем.
    """
    try:
        if update.message and update.message.text is not None:
            return await update.message.reply_text(text, reply_markup=reply_markup)
        elif update.callback_query:
            # callback
            if reply_markup is None or isinstance(reply_markup, InlineKeyboardMarkup):
                try:
                    return await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
                except BadRequest as e:
                    # если "message is not modified" — игнорируем
                    msg = str(e)
                    if "Message is not modified" in msg:
                        return None
                    # иначе — fallback: отправим новое сообщение
                    return await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
            else:
                # reply_markup — ReplyKeyboardMarkup (main menu) — не подходит для edit_message_text
                # редактируем текущее сообщение без клавиатуры (игнорируем ошибку "not modified"),
                # затем отправляем новое сообщение с клавиатурой.
                try:
                    await update.callback_query.edit_message_text(text)
                except BadRequest:
                    pass
                return await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    except Exception:
        # как последний вариант — если что-то сломалось, постим обычное сообщение в чат
        try:
            if update.effective_chat:
                return await update.effective_chat.send_message(text)
        except Exception:
            return None

# ------------------- ХРАНЕНИЕ ДАННЫХ -------------------
tasks = load_data(TASKS_FILE)
reminders = load_data(REMINDERS_FILE)
birthdays = load_data(BIRTHDAYS_FILE)
events = load_data(EVENTS_FILE)
tasks_history = load_data(TASKS_HISTORY_FILE)

# ------------------- СОСТОЯНИЯ CONVERSATION -------------------
ASK_TASK_DAY_TYPE, ASK_TASK_TEXT, ASK_TASK_OTHER_DATE = range(3)
ASK_REM_TYPE, ASK_REM_TEXT, ASK_REM_DATE, ASK_REM_TIME = range(4)
BDAY_NAME, BDAY_DATE, EVENT_TITLE, EVENT_DATE = range(6, 10)

# ------------------- START -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
         "Привет! 👋 Я помогу тебе организовать день и не забывать важное!\n\n"
        "Вот что ты можешь делать:\n"
        "📝 Добавлять задачи на день, а также планировать их на дни вперед \n"
        "⏰ Ставить напоминания: на день, на предстоящий день или настроить ежедневные напоминания\n"
        "🎉 Сохранять события и получать уведомления — например, дни рождения друзей\n"
        "📄 Получать полезные файлы для быстрого 5-минутного чтения\n\n"
        "Используй кнопки внизу. В любой момент нажми «Отмена», чтобы вернуться в главное меню."
    )
       
    await send_or_edit(update, txt, reply_markup=main_menu_keyboard())

# ------------------- ЗАДАЧИ -------------------
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([["На сегодня", "На другой день"], ["Отмена"]], resize_keyboard=True)
    await send_or_edit(update, "Выберите: задача на сегодня или на другой день?", reply_markup=kb)
    return ASK_TASK_DAY_TYPE

async def add_task_day_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "На сегодня":
        context.user_data["task_day_type"] = "today"
        await send_or_edit(update, "✍ Введите задачу на сегодня:")
        return ASK_TASK_TEXT
    elif text == "На другой день":
        context.user_data["task_day_type"] = "other"
        await send_or_edit(update, "✍ Введите дату в формате ДД.MM.ГГГГ:(год нынешний)")
        return ASK_TASK_OTHER_DATE
    else:
        return await cancel(update, context)

async def add_task_other_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_text = update.message.text.strip()
    try:
        d = datetime.strptime(date_text, "%d.%m.%Y").date()
        context.user_data["task_other_date"] = d
        await send_or_edit(update, "✍ Введите текст задачи для указанной даты:")
        return ASK_TASK_TEXT
    except Exception:
        await send_or_edit(update, "⚠ Неверный формат. Попробуйте ДД.MM.ГГГГ или нажмите Отмена.")
        return ASK_TASK_OTHER_DATE

async def add_task_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    if context.user_data.get("task_day_type") == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        date_obj = context.user_data.get("task_other_date")
        date_str = date_obj.strftime("%Y-%m-%d")
    text = update.message.text
    tasks.setdefault(user_id, []).append({"text": text, "done": False, "date": date_str})
    save_data(TASKS_FILE, tasks)
    await send_or_edit(update, f"✅ Задача добавлена: {text}", reply_markup=main_menu_keyboard())
    context.user_data.pop("task_day_type", None)
    context.user_data.pop("task_other_date", None)
    return ConversationHandler.END

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    today = datetime.now().strftime("%Y-%m-%d")
    user_tasks = tasks.get(user_id, [])
    today_tasks = [t for t in user_tasks if t.get("date") == today]
    other_tasks = [t for t in user_tasks if t.get("date") != today]

    msg = "📋 Задачи на сегодня:\n"
    kb = []
    if today_tasks:
        for i, t in enumerate(today_tasks, 1):
            status = "✅" if t.get("done") else "❌"
            msg += f"{i}. {t.get('text','')} {status}\n"
            if not t.get("done"):
                kb.append([InlineKeyboardButton("✔ Выполнено", callback_data=f"task:today:done:{i-1}"),
                           InlineKeyboardButton("❌ Удалить", callback_data=f"task:today:del:{i-1}")])
            else:
                # если задача уже выполнена — показываем только кнопку удаления
                kb.append([InlineKeyboardButton("❌ Удалить", callback_data=f"task:today:del:{i-1}")])
    else:
        msg += "Нет задач на сегодня\n"

    msg += "\n📋 Задачи на другие дни:\n"
    if other_tasks:
        for i, t in enumerate(other_tasks, 1):
            status = "✅" if t.get("done") else "❌"
            date_str = datetime.strptime(t.get("date"), "%Y-%m-%d").strftime("%d.%m.%Y")
            msg += f"{i}. {t.get('text','')} ({date_str}) {status}\n"
            if not t.get("done"):
                kb.append([InlineKeyboardButton("✔ Выполнено", callback_data=f"task:other:done:{i-1}"),
                           InlineKeyboardButton("❌ Удалить", callback_data=f"task:other:del:{i-1}")])
            else:
                kb.append([InlineKeyboardButton("❌ Удалить", callback_data=f"task:other:del:{i-1}")])
    else:
        msg += "Нет задач на другие дни\n"

    # Если есть inline-кнопки — отправляем/редактируем сообщение с inline-клавиатурой как раньше.
    if kb:
        await send_or_edit(update, msg, reply_markup=InlineKeyboardMarkup(kb))
        return

    # Если inline-кнопок нет — хотим показать сообщение с обычным меню один раз.
    # При callback_query: удаляем исходное inline-сообщение (если возможно),
    # а потом отправляем одно новое сообщение с main_menu_keyboard().
    if hasattr(update, "callback_query") and update.callback_query:
        try:
            # попробуем удалить исходное сообщение с inline-кнопками, чтобы избежать двойной выдачи
            await update.callback_query.message.delete()
        except Exception:
            # если удалить нельзя — игнорируем и будем использовать send_or_edit как запасной вариант
            try:
                await send_or_edit(update, msg, reply_markup=main_menu_keyboard())
            except Exception:
                # окончательный запасной вариант: попытка отправить в чат напрямую
                if update.effective_chat:
                    await update.effective_chat.send_message(msg, reply_markup=main_menu_keyboard())
            return

        # после успешной (или терпимой) попытки удаления — отправим одно сообщение с меню
        if update.effective_chat:
            await update.effective_chat.send_message(msg, reply_markup=main_menu_keyboard())
        else:
            # если нет effective_chat — fallback через send_or_edit
            await send_or_edit(update, msg, reply_markup=main_menu_keyboard())
    else:
        # обычный текстовый (не callback) вызов — используем send_or_edit как раньше
        await send_or_edit(update, msg, reply_markup=main_menu_keyboard())


async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")  # e.g. task:today:done:0
    if len(data) != 4:
        await list_tasks(update, context)
        return
    _, group, action, idx_str = data
    try:
        idx = int(idx_str)
    except:
        await list_tasks(update, context)
        return

    user_id = get_user_id_from_update(update)
    user_tasks = tasks.get(user_id, [])
    today = datetime.now().strftime("%Y-%m-%d")
    today_tasks = [t for t in user_tasks if t.get("date") == today]
    other_tasks = [t for t in user_tasks if t.get("date") != today]

    source = today_tasks if group == "today" else other_tasks
    if idx < 0 or idx >= len(source):
        await list_tasks(update, context)
        return

    entry = source[idx]
    # find original index
    orig_index = None
    for oi, t in enumerate(user_tasks):
        if t is entry or (t.get("text") == entry.get("text") and t.get("date") == entry.get("date")):
            orig_index = oi
            break
    if orig_index is None:
        await list_tasks(update, context)
        return

    if action == "done":
        tasks[user_id][orig_index]["done"] = True
        save_data(TASKS_FILE, tasks)
        await list_tasks(update, context)
    elif action == "del":
        tasks[user_id].pop(orig_index)
        save_data(TASKS_FILE, tasks)
        await list_tasks(update, context)

# ------------------- НАПОМИНАНИЯ -------------------
async def add_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([["На сегодня", "На другой день"], ["Ежедневно", "Отмена"]], resize_keyboard=True)
    await send_or_edit(update, "Выберите тип напоминания:", reply_markup=kb)
    return ASK_REM_TYPE

async def add_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice not in ["На сегодня", "На другой день", "Ежедневно"]:
        return await cancel(update, context)
    
    context.user_data["rem_type"] = choice
    await send_or_edit(update, "✍ Введите текст напоминания:", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
    return ASK_REM_TEXT

async def add_reminder_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rem_text"] = update.message.text.strip()
    rtype = context.user_data.get("rem_type")

    if rtype == "На другой день":
        await send_or_edit(update, "Введите дату напоминания в формате ДД.MM.ГГГГ:(год настоящий)", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
        return ASK_REM_DATE
    else:
        await send_or_edit(update, "Введите время в формате ЧЧ:ММ (например, 09:30):", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
        return ASK_REM_TIME

async def add_reminder_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = update.message.text.strip()
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        context.user_data["rem_date"] = d.strftime("%Y-%m-%d")
        await send_or_edit(update, "Введите время в формате ЧЧ:ММ (например, 09:30):", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
        return ASK_REM_TIME
    except Exception:
        await send_or_edit(update, "⚠ Неверный формат даты. Попробуйте ДД.MM.ГГГГ или нажмите Отмена.")
        return ASK_REM_DATE

async def add_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    text = context.user_data.get("rem_text")
    rtype = context.user_data.get("rem_type")
    date_val = context.user_data.get("rem_date") if rtype == "На другой день" else None
    time_str = update.message.text.strip()
    try:
        h, m = map(int, time_str.split(":"))
        t_formatted = f"{h:02d}:{m:02d}"
        reminder = {
            "text": text,
            "time": t_formatted,
            "type": rtype,
            "enabled": True,
            "fired_today": False
        }
        if date_val:
            reminder["date"] = date_val
        reminders.setdefault(user_id, []).append(reminder)
        save_data(REMINDERS_FILE, reminders)
        await send_or_edit(update, f"✅ Напоминание добавлено: «{text}» в {t_formatted}", reply_markup=main_menu_keyboard())

        context.user_data.pop("rem_text", None)
        context.user_data.pop("rem_type", None)
        context.user_data.pop("rem_date", None)
        return ConversationHandler.END
    except Exception:
        await send_or_edit(update, "⚠ Неверный формат времени. Попробуйте ЧЧ:ММ или нажмите Отмена.")
        return ASK_REM_TIME

async def reminder_checker(context: ContextTypes.DEFAULT_TYPE):
    now_hm = datetime.now().strftime("%H:%M")
    for user_id, rem_list in list(reminders.items()):
        for rem in list(rem_list):
            if rem.get("enabled") and rem.get("time") == now_hm and not rem.get("fired_today"):
                try:
                    await context.bot.send_message(int(user_id), f"🔔 Напоминание: {rem['text']}")
                except Exception:
                    pass
                if rem.get("type") == "На сегодня":
                    rem_list.remove(rem)
                else:
                    rem["fired_today"] = True
        save_data(REMINDERS_FILE, reminders)

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    user_reminders = reminders.get(user_id, [])
    today = datetime.now().strftime("%Y-%m-%d")

    today_rem = []
    other_rem = []

    for r in user_reminders:
        if r.get("type") == "Ежедневно" or r.get("type") == "На сегодня":
            today_rem.append(r)
        else:
            other_rem.append(r)

    msg = "⏰ Напоминания:\n\n"
    kb = []

    msg += "📅 На сегодня:\n"
    if today_rem:
        for i, r in enumerate(today_rem, 1):
            status = "✅" if r.get("fired_today") else "❌"
            type_note = "(ежедневно)" if r.get("type") == "Ежедневно" else ""
            msg += f"{i}. {r.get('text','')} ({r.get('time','')} {type_note}) {status}\n"
            if r.get("type") == "Ежедневно":
                if r.get("enabled", True):
                    kb.append([InlineKeyboardButton("⏸ Остановить", callback_data=f"rem:stop:{user_reminders.index(r)}"),
                               InlineKeyboardButton("❌ Удалить", callback_data=f"rem:del:{user_reminders.index(r)}")])
                else:
                    kb.append([InlineKeyboardButton("▶ Возобновить", callback_data=f"rem:start:{user_reminders.index(r)}"),
                               InlineKeyboardButton("❌ Удалить", callback_data=f"rem:del:{user_reminders.index(r)}")])
            else:
                kb.append([InlineKeyboardButton("❌ Удалить", callback_data=f"rem:del:{user_reminders.index(r)}")])
    else:
        msg += "Нет напоминаний на сегодня\n"

    msg += "\n📅 На другие дни:\n"
    if other_rem:
        for i, r in enumerate(other_rem, 1):
            date_str = r.get("date", "?")
            status = "✅" if r.get("fired_today") else "❌"
            msg += f"{i}. {r.get('text','')} ({date_str}, {r.get('time','')}) {status}\n"
            kb.append([InlineKeyboardButton("❌ Удалить", callback_data=f"rem:del:{user_reminders.index(r)}")])
    else:
        msg += "Нет напоминаний на другие дни\n"

    if kb:
        await send_or_edit(update, msg, reply_markup=InlineKeyboardMarkup(kb))
        return

    if hasattr(update, "callback_query") and update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            try:
                await send_or_edit(update, msg, reply_markup=main_menu_keyboard())
            except Exception:
                if update.effective_chat:
                    await update.effective_chat.send_message(msg, reply_markup=main_menu_keyboard())
            return

        if update.effective_chat:
            await update.effective_chat.send_message(msg, reply_markup=main_menu_keyboard())
        else:
            await send_or_edit(update, msg, reply_markup=main_menu_keyboard())
    else:
        await send_or_edit(update, msg, reply_markup=main_menu_keyboard())

async def rem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3:
        await list_reminders(update, context)
        return
    _, action, idx_str = parts
    try:
        idx = int(idx_str)
    except:
        await list_reminders(update, context)
        return
    user_id = get_user_id_from_update(update)
    rlist = reminders.get(user_id, [])
    if idx < 0 or idx >= len(rlist):
        await list_reminders(update, context)
        return
    if action == "stop":
        rlist[idx]["enabled"] = False
    elif action == "start":
        rlist[idx]["enabled"] = True
    elif action == "del":
        rlist.pop(idx)
    save_data(REMINDERS_FILE, reminders)
    await list_reminders(update, context)

# ------------------- РАНДОМ ФАЙЛЫ ----------------

async def send_random_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    PDF_DIR = "pdfs"  # папка с файлами

    if not os.path.exists(PDF_DIR):
        await update.message.reply_text("⚠ Папка с PDF не найдена.", reply_markup=main_menu_keyboard())
        return

    pdf_files = [f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        await update.message.reply_text("⚠ PDF файлов пока нет.", reply_markup=main_menu_keyboard())
        return

    chosen_pdf = random.choice(pdf_files)
    file_path = os.path.join(PDF_DIR, chosen_pdf)

    try:
        # открываем файл в бинарном режиме и передаём объект
        with open(file_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=chosen_pdf
            )
    except Exception as e:
        await update.message.reply_text(
            f"⚠ Ошибка при отправке файла: {e}",
            reply_markup=main_menu_keyboard()
        )

# ------------------- СОБЫТИЯ -------------------
async def events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([["🎂 День рождения", "📌 Ивент"], ["📅 Список событий", "Отмена"]], resize_keyboard=True)
    await send_or_edit(update, "Выберите действие с событиями:", reply_markup=kb)

# Добавление дня рождения
async def start_add_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_or_edit(update, "✍ Введите имя человека (имя и/или фамилия):", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
    return BDAY_NAME

async def receive_birthday_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["birthday_name"] = update.message.text.strip()
    await send_or_edit(update, "✍ Теперь введите дату дня рождения в формате ДД.MM.ГГГГ (например, 26.09.2025,(год нынешний)):", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
    return BDAY_DATE

async def receive_birthday_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    name = context.user_data.get("birthday_name")
    try:
        d = datetime.strptime(update.message.text.strip(), "%d.%m.%Y").date()
        birthdays.setdefault(user_id, []).append({"name": name, "date": d.strftime("%Y-%m-%d")})
        save_data(BIRTHDAYS_FILE, birthdays)
        await send_or_edit(update, f"✅ День рождения добавлен: {name} — {d.strftime('%d.%m.%Y')}", reply_markup=main_menu_keyboard())
        context.user_data.pop("birthday_name", None)
        return ConversationHandler.END
    except Exception:
        await send_or_edit(update, "⚠ Неверный формат. Попробуйте снова ДД.MM.ГГГГ или нажмите Отмена.")
        return BDAY_DATE

# Добавление ивента
async def start_add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_or_edit(update, "✍ Введите название события:", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
    return EVENT_TITLE

async def receive_event_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["event_title"] = update.message.text.strip()
    await send_or_edit(update, "✍ Теперь введите дату события в формате ДД.MM.ГГГГ:", reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True))
    return EVENT_DATE

async def receive_event_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    title = context.user_data.get("event_title")
    try:
        d = datetime.strptime(update.message.text.strip(), "%d.%m.%Y").date()
        events.setdefault(user_id, []).append({"title": title, "date": d.strftime("%Y-%m-%d")})
        save_data(EVENTS_FILE, events)
        await send_or_edit(update, f"✅ Ивент добавлен: {title} — {d.strftime('%d.%m.%Y')}", reply_markup=main_menu_keyboard())
        context.user_data.pop("event_title", None)
        return ConversationHandler.END
    except Exception:
        await send_or_edit(update, "⚠ Неверный формат. Попробуйте снова ДД.MM.ГГГГ или нажмите Отмена.")
        return EVENT_DATE

async def build_events_list(user_id: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_events = []

    # we keep references to current indices in original lists
    for i, b in enumerate(birthdays.get(user_id, [])):
        all_events.append({"id": f"b{i}", "type": "birthday", "name": b["name"], "date": b["date"]})
    for i, e in enumerate(events.get(user_id, [])):
        all_events.append({"id": f"e{i}", "type": "event", "title": e["title"], "date": e["date"]})

    if not all_events:
        return "У вас нет событий.", None

    all_events.sort(key=lambda x: x["date"])

    msg_lines = []
    buttons = []
    for i, ev in enumerate(all_events, 1):
        dt = datetime.strptime(ev["date"], "%Y-%m-%d")
        note = "🎉 Сегодня!" if ev["date"] == today_str else ""
        if ev["type"] == "birthday":
            msg_lines.append(f"{i}. 🎂 {ev['name']} - {dt.strftime('%d.%m.%Y')} {note}")
            buttons.append([InlineKeyboardButton(f"❌ Удалить {ev['name']}", callback_data=f"del_{ev['id']}")])
        else:
            msg_lines.append(f"{i}. 📌 {ev['title']} - {dt.strftime('%d.%m.%Y')} {note}")
            buttons.append([InlineKeyboardButton(f"❌ Удалить {ev['title']}", callback_data=f"del_{ev['id']}")])

    text = "\n".join(msg_lines)
    return text, InlineKeyboardMarkup(buttons)

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    text, kb = await build_events_list(user_id)
    await send_or_edit(update, text, reply_markup=kb or main_menu_keyboard())

async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = get_user_id_from_update(update)
    # callback data format: del_b0 or del_e1
    try:
        _, ev_id = query.data.split("_", 1)
    except Exception:
        await list_events(update, context)
        return
    if ev_id.startswith("b"):
        idx = int(ev_id[1:])
        if user_id in birthdays and 0 <= idx < len(birthdays[user_id]):
            birthdays[user_id].pop(idx)
            save_data(BIRTHDAYS_FILE, birthdays)
    elif ev_id.startswith("e"):
        idx = int(ev_id[1:])
        if user_id in events and 0 <= idx < len(events[user_id]):
            events[user_id].pop(idx)
            save_data(EVENTS_FILE, events)

    # пересобираем и редактируем то же сообщение
    text, kb = await build_events_list(user_id)
    # edit original message; if no events left - edit text and then send main menu
    try:
        if kb:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            # edit message to "У вас нет событий."
            await query.edit_message_text(text)
            # send menu as a separate message with ReplyKeyboardMarkup
            await query.message.reply_text("Возвращаю в главное меню.", reply_markup=main_menu_keyboard())
    except BadRequest as e:
        # fallback: отправим новое сообщение с меню
        try:
            await query.message.reply_text(text, reply_markup=kb or main_menu_keyboard())
        except Exception:
            pass

# ------------------- МОЙ ДЕНЬ и МОЙ МЕСЯЦ -------------------
async def my_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    today = datetime.now().strftime("%Y-%m-%d")
    today_tasks = [t for t in tasks.get(user_id, []) if t.get("date") == today]
    msg = "📅 Мой день\n\n📋 Задачи на сегодня:\n"
    if today_tasks:
        for i, t in enumerate(today_tasks, 1):
            status = "✅" if t.get("done") else "❌"
            msg += f"{i}. {t.get('text','')} {status}\n"
    else:
        msg += "Нет задач на сегодня\n"

    msg += "\n🎉 События на сегодня:\n"
    today_events = []
    for b in birthdays.get(user_id, []):
        if b.get("date") == today:
            today_events.append(("birthday", b.get("name")))
    for e in events.get(user_id, []):
        if e.get("date") == today:
            today_events.append(("event", e.get("title")))
    if today_events:
        for i, ev in enumerate(today_events, 1):
            icon = "🎂" if ev[0] == "birthday" else "📌"
            msg += f"{i}. {icon} {ev[1]}\n"
    else:
        msg += "Нет событий на сегодня\n"
    await send_or_edit(update, msg, reply_markup=main_menu_keyboard())

async def my_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id_from_update(update)
    month_prefix = datetime.now().strftime("%Y-%m")
    msg = "📆 Мой месяц\n\n📋 Задачи на этот месяц:\n"
    month_tasks = [t for t in tasks.get(user_id, []) if t.get("date","").startswith(month_prefix)]
    if month_tasks:
        for i, t in enumerate(month_tasks, 1):
            date_str = datetime.strptime(t["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
            status = "✅" if t.get("done") else "❌"
            msg += f"{i}. {t.get('text','')} ({date_str}) {status}\n"
    else:
        msg += "Нет задач на этот месяц\n"

    msg += "\n🎉 События на этот месяц:\n"
    month_events = []
    for b in birthdays.get(user_id, []):
        if b.get("date","").startswith(month_prefix):
            month_events.append(("birthday", b.get("name"), b.get("date")))
    for e in events.get(user_id, []):
        if e.get("date","").startswith(month_prefix):
            month_events.append(("event", e.get("title"), e.get("date")))
    month_events.sort(key=lambda x: x[2])
    if month_events:
        for i, ev in enumerate(month_events, 1):
            icon = "🎂" if ev[0]=="birthday" else "📌"
            dt = datetime.strptime(ev[2], "%Y-%m-%d")
            msg += f"{i}. {icon} {ev[1]} ({dt.strftime('%d.%m.%Y')})\n"
    else:
        msg += "Нет событий на этот месяц\n"
    await send_or_edit(update, msg, reply_markup=main_menu_keyboard())

# ------------------- СБРОС / ЕЖЕДНЕВНЫЕ ЗАДАЧИ -------------------
def schedule_daily_reset(app):
    async def reset_tasks(context: ContextTypes.DEFAULT_TYPE):
        # сохраняем историю задач в tasks_history, затем очищаем today's tasks
        for user_id, user_tasks in list(tasks.items()):
            if user_tasks:
                tasks_history.setdefault(user_id, []).append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "tasks": user_tasks
                })
        save_data(TASKS_HISTORY_FILE, tasks_history)
        # очищаем все задачи (user хотел сброс после 23:55). Если хочешь только пометить как прошлые — можно изменить.
        tasks.clear()
        save_data(TASKS_FILE, tasks)
        # сброс fired_today у ежедневных напоминаний
        for user_id, rem_list in reminders.items():
            for rem in rem_list:
                if rem.get("type") == "Ежедневно":
                    rem["fired_today"] = False
        save_data(REMINDERS_FILE, reminders)

    # Запланировать на 23:55 каждый день
    try:
        app.job_queue.run_daily(reset_tasks, dt_time(hour=23, minute=55))
    except Exception:
        pass

# ------------------- CANCEL -------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальная отмена — поддерживает и текстовые сообщения, и inline-кнопки (callback_query).
    Возвращает в главное меню и завершает ConversationHandler.
    Не очищаем весь context.user_data (это ломает внутреннее состояние ConversationHandler).
    """
    # если это callback (нажатие inline-кнопки)
    if update.callback_query:
        cq = update.callback_query
        # обязательно ответим на callback_query, чтобы клиент не оставил его в подвешенном состоянии
        try:
            await cq.answer()
        except Exception:
            pass

        # попробуем отредактировать исходное сообщение (удалить inline-кнопки)
        try:
            await cq.edit_message_text("❌ Отменено.", reply_markup=None)
        except BadRequest:
            # если редактирование не прошло — отправим простой reply
            try:
                await cq.message.reply_text("❌ Отменено.")
            except Exception:
                pass

        # отправим главное меню обычным сообщением (ReplyKeyboardMarkup)
        try:
            await cq.message.reply_text("Возвращаю в главное меню.", reply_markup=main_menu_keyboard())
        except Exception:
            try:
                if update.effective_chat:
                    await update.effective_chat.send_message("Возвращаю в главное меню.", reply_markup=main_menu_keyboard())
            except Exception:
                pass

    # если это обычное текстовое сообщение (например, пользователь ввёл Отмена)
    elif update.message:
        try:
            await update.message.reply_text("❌ Отменено.", reply_markup=main_menu_keyboard())
        except Exception:
            pass

    # УДАЛИТЕ context.user_data.clear() — вместо этого аккуратно удаляем только те ключи, что мы сами создавали
    for k in (
        "task_day_type", "task_other_date",
        "rem_text", "rem_type", "rem_date",
        "birthday_name", "event_title"
    ):
        context.user_data.pop(k, None)

    return ConversationHandler.END


# ------------------- РЕГИСТРАЦИЯ ХЕНДЛЕРОВ И ЗАПУСК -------------------
def main():
    # Загружаем данные
    global tasks, reminders, birthdays, events, tasks_history
    tasks = load_data(TASKS_FILE)
    reminders = load_data(REMINDERS_FILE)
    birthdays = load_data(BIRTHDAYS_FILE)
    events = load_data(EVENTS_FILE)
    tasks_history = load_data(TASKS_HISTORY_FILE)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команда /start
    app.add_handler(CommandHandler("start", start))

    # Tasks conversation
    task_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить задачу$"), add_task_start)],
        states={
            ASK_TASK_DAY_TYPE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_day_type)
            ],
            ASK_TASK_OTHER_DATE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_other_date)
            ],
            ASK_TASK_TEXT: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_receive)
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^Отмена$"), cancel)],
        per_message=False
    )
    app.add_handler(task_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 Мои задачи$"), list_tasks))
    app.add_handler(CallbackQueryHandler(task_callback, pattern="^task:"))

    # Reminders conversation
    reminder_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⏰ Добавить напоминание$"), add_reminder_start)],
        states={
            ASK_REM_TYPE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_type)
            ],
            ASK_REM_TEXT: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_text)
            ],
            ASK_REM_DATE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_date)
            ],
            ASK_REM_TIME: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_time)
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^Отмена$"), cancel)],
        per_message=False
    )
    app.add_handler(reminder_conv)
    app.add_handler(MessageHandler(filters.Regex("^🔔 Мои напоминания$"), list_reminders))
    app.add_handler(CallbackQueryHandler(rem_callback, pattern="^rem:"))

    # Events conversation & handlers
    app.add_handler(MessageHandler(filters.Regex("^🎉 События$"), events_menu))

    birthday_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎂 День рождения$"), start_add_birthday)],
        states={
            BDAY_NAME: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_birthday_name)
            ],
            BDAY_DATE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_birthday_date)
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^Отмена$"), cancel)],
        per_message=False
    )
    app.add_handler(birthday_conv)

    event_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📌 Ивент$"), start_add_event)],
        states={
            EVENT_TITLE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_event_title)
            ],
            EVENT_DATE: [
                MessageHandler(filters.Regex("^Отмена$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_event_date)
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^Отмена$"), cancel)],
        per_message=False
    )
    app.add_handler(event_conv)

    # Кнопка 5 минут
    app.add_handler(MessageHandler(filters.Regex("^📖 5 минут$"), send_random_pdf))

    # List / delete events
    app.add_handler(MessageHandler(filters.Regex("^📅 Список событий$"), list_events))
    app.add_handler(CallbackQueryHandler(delete_event, pattern="^del_"))

    # Day / Month
    app.add_handler(MessageHandler(filters.Regex("^📅 Мой день$"), my_day))
    app.add_handler(MessageHandler(filters.Regex("^📆 Мой месяц$"), my_month))

    # ----------------------
    # Глобальная кнопка Отмена (текстовая)
    # Обработает "Отмена" в ситуациях, когда нет активного ConversationHandler,
    # например: меню "🎉 События" (обычная ReplyKeyboardMarkup).
    # Добавляем ПОСЛЕ регистрации всех ConversationHandler'ов, чтобы не конфликтовать с их fallback'ами.
    app.add_handler(MessageHandler(filters.Regex("^Отмена$"), cancel))
    # ----------------------

    # Планировщик: проверки напоминаний каждую минуту
    try:
        app.job_queue.run_repeating(reminder_checker, interval=60, first=5)
    except Exception:
        pass

    # Планировщик: ежедневный сброс (23:55)
    schedule_daily_reset(app)

    print("Бот запущен...")
    PORT = int(os.environ.get("PORT", 8443))  # Render задаёт PORT
    RENDER_URL = "https://telegram-bot-zk6v.onrender.com"  # 👉 замени на свой Render URL

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{RENDER_URL}/{TELEGRAM_TOKEN}"
    )


if __name__ == "__main__":
    main()
