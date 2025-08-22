import os
import logging
import time
import html
import asyncio
from collections import defaultdict
from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters
)

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1002627719555"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "5973278509"))
USERS_FILE = "users.txt"

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is not set. Please configure environment variables.")

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- In-memory counters ---
file_count = 0
user_file_counter = defaultdict(int)  # Tracks per-user uploads


# --- Helpers ---
def generate_file_id(user_id: int) -> str:
    """Generate unique File ID = UserID + Timestamp + PerUserCount"""
    global user_file_counter
    user_file_counter[user_id] += 1
    return f"{user_id}{int(time.time())}{user_file_counter[user_id]}"


def save_user(user_id: int) -> None:
    """Save user ID if not already stored."""
    try:
        users = set()
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                users = set(line.strip() for line in f if line.strip())
        if str(user_id) not in users:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")


def format_file_size(size: int) -> str:
    """Convert bytes into human-readable format."""
    if not size:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{round(size, 2)} {unit}"
        size /= 1024
    return f"{round(size, 2)} PB"


def detect_file_type(message: Message) -> tuple[str, str, int]:
    """Return file_type, display_name, size"""
    if message.document:
        return f"Document ({message.document.mime_type.split('/')[-1].upper()})", message.document.file_name or "Document", message.document.file_size
    if message.video:
        return "Video", "Video", message.video.file_size
    if message.audio:
        return "Audio", message.audio.file_name or "Audio", message.audio.file_size
    if message.photo:
        return "Photo (JPEG/PNG)", "Photo", 0
    if message.voice:
        return "Voice", "Voice", message.voice.file_size
    if message.video_note:
        return "Video Note", "Video Note", 0
    return "File", "Unnamed", 0


async def send_announcement(bot, chat_id: int, message: Message):
    """Forward announcements to users safely"""
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )
    except Exception as e:
        logger.error(f"Failed to announce to {chat_id}: {e}")


# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    args = context.args
    if args:
        try:
            file_id = args[0]
            # FileID structure: UserID+Timestamp+Count
            # Extract message_id via GROUP_CHAT copy
            # Here we only use timestamp part as deep link
            message_id = int(file_id[-1])  # simplistic (expand logic if needed)
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=GROUP_CHAT_ID,
                message_id=message_id
            )
            return
        except Exception:
            await update.message.reply_text("❌ Invalid File ID / Deep link.")
            return

    await update.message.reply_text(
        "👋 *Welcome to Report Cloud Storage!*\n\n"
        "📁 Upload any file and receive a unique *File ID*.\n"
        "🔗 Retrieve files anytime using your Deep Link.\n\n"
        "*Commands:*\n"
        "• /help – How to use\n"
        "• /stats – Bot stats\n"
        "• /myfiles – View your files\n"
        "• /announce – (Admin only) Broadcast",
        parse_mode=ParseMode.MARKDOWN
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*📖 How to Use:*\n\n"
        "1️⃣ Send any file (doc/photo/video).\n"
        "2️⃣ Get a *File ID* + *Deep Link*.\n"
        "3️⃣ Retrieve anytime: `https://t.me/{bot}?start=<FileID>`\n\n"
        "Admin:\n"
        "• Reply + /announce to broadcast.",
        parse_mode=ParseMode.MARKDOWN
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = 0
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = len([line for line in f if line.strip()])

    await update.message.reply_text(
        f"📊 *Total Files:* {file_count}\n👥 *Users:* {users}",
        parse_mode=ParseMode.MARKDOWN
    )


async def myfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = user_file_counter.get(user_id, 0)
    if count == 0:
        await update.message.reply_text("📂 You haven’t uploaded any files yet.")
    else:
        await update.message.reply_text(f"📂 You have uploaded *{count}* files.", parse_mode=ParseMode.MARKDOWN)


async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a message to announce it.")
        return

    try:
        with open(USERS_FILE, "r") as f:
            users = [int(u.strip()) for u in f if u.strip()]
    except FileNotFoundError:
        await update.message.reply_text("❌ No users found.")
        return

    success, fail = 0, 0
    for uid in users:
        try:
            await send_announcement(context.bot, uid, update.message.reply_to_message)
            success += 1
            await asyncio.sleep(0.1)
        except Exception:
            fail += 1

    await update.message.reply_text(f"✅ Sent to {success}, ❌ Failed {fail}")


# --- File Handler ---
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global file_count
    msg = update.message
    user_id = msg.from_user.id

    if msg.from_user.is_bot:
        return

    save_user(user_id)

    if any([msg.document, msg.photo, msg.video, msg.audio, msg.voice, msg.video_note]):
        try:
            forwarded = await msg.forward(chat_id=GROUP_CHAT_ID)
            file_id = generate_file_id(user_id)
            file_count += 1

            file_type, file_name, file_size = detect_file_type(msg)
            size = format_file_size(file_size)
            deep_link = f"https://t.me/{context.bot.username}?start={file_id}"

            await msg.reply_text(
                f"✅ *File Saved!*\n\n"
                f"📝 *Name:* `{html.escape(file_name)}`\n"
                f"📁 *Type:* {file_type}\n"
                f"📦 *Size:* {size}\n"
                f"🆔 *File ID:* `{file_id}`\n\n"
                f"🔗 *Deep Link:* {deep_link}",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Upload error: {e}")
            await msg.reply_text("❌ Failed to save file.")
    elif msg.text:
        await msg.reply_text("❌ Invalid File ID. Use deep link only.")


# --- Main ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("myfiles", myfiles))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file))

    logger.info("🤖 Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
