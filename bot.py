import os
import logging
import time
from telegram import Update, ParseMode, Message
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.helpers import escape_markdown

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

# --- Utils ---
def generate_file_id(user_id: int, message_id: int) -> str:
    return f"{user_id}_{int(time.time())}_{message_id}"

def save_user(user_id: int) -> None:
    """Save user ID if not already stored."""
    try:
        users = set()
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                users = {line.strip() for line in f if line.strip()}
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
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def detect_file_type(message: Message) -> tuple[str, str, int]:
    """Return file_type, display_name, size"""
    if message.document:
        return (f"Document ({message.document.mime_type or ''})", 
                message.document.file_name or "Document", 
                message.document.file_size)
    if message.video:
        return (f"Video ({message.video.mime_type or ''})", "Video", message.video.file_size)
    if message.audio:
        return (f"Audio ({message.audio.mime_type or ''})", 
                message.audio.file_name or "Audio", 
                message.audio.file_size)
    if message.photo:
        return ("Photo (JPEG/PNG)", "Photo", 0)
    if message.voice:
        return ("Voice (OGG/OPUS)", "Voice", message.voice.file_size)
    if message.video_note:
        return ("Video Note (Round)", "Video Note", 0)
    return ("File", "Unnamed", 0)

def send_announcement_to_user(bot, chat_id: int, message: Message) -> bool:
    """Send message safely to user and return success status."""
    try:
        if message.text:
            bot.send_message(chat_id=chat_id, text=message.text, parse_mode=ParseMode.MARKDOWN_V2)
        elif message.photo:
            bot.send_photo(chat_id=chat_id, photo=message.photo[-1].file_id,
                           caption=message.caption or "")
        elif message.video:
            bot.send_video(chat_id=chat_id, video=message.video.file_id,
                           caption=message.caption or "")
        elif message.document:
            bot.send_document(chat_id=chat_id, document=message.document.file_id,
                              caption=message.caption or "")
        elif message.audio:
            bot.send_audio(chat_id=chat_id, audio=message.audio.file_id,
                           caption=message.caption or "")
        elif message.voice:
            bot.send_voice(chat_id=chat_id, voice=message.voice.file_id,
                           caption=message.caption or "")
        elif message.video_note:
            bot.send_video_note(chat_id=chat_id, video_note=message.video_note.file_id)
        elif message.caption:
            bot.send_message(chat_id=chat_id, text=message.caption)
        return True
    except Exception as e:
        logger.warning(f"Announcement failed for {chat_id}: {e}")
        return False

# --- Commands ---
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    save_user(user_id)

    args = context.args
    if args and len(args) == 1:
        try:
            parts = args[0].split("_")
            if len(parts) == 3:
                message_id = int(parts[2])
                context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=GROUP_CHAT_ID,
                    message_id=message_id
                )
                return
        except Exception:
            update.message.reply_text("❌ Invalid deep link.")
            return

    update.message.reply_text(
        "👋 *Welcome to Report Cloud Storage!*\n\n"
        "📁 Upload any file and receive a unique *File ID*.\n"
        "🔗 Retrieve files anytime using the File ID or deep link.\n\n"
        "*Commands:*\n"
        "• /help – How to use\n"
        "• /stats – Session Stats\n"
        "• /announce – (Admin only) Broadcast message",
        parse_mode=ParseMode.MARKDOWN_V2
    )

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "📖 *How to Use:*\n\n"
        "1️⃣ Send any file (document, photo, video, etc).\n"
        "2️⃣ Receive a *File ID* and copyable *Deep Link*.\n"
        f"3️⃣ Retrieve your file: `https://t.me/{context.bot.username}?start=<FileID>`\n\n"
        "4️⃣ Broadcast message (Admin only): Reply to a message and type /announce",
        parse_mode=ParseMode.MARKDOWN_V2
    )

def stats(update: Update, context: CallbackContext) -> None:
    users = 0
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = sum(1 for line in f if line.strip())
    files = context.bot_data.get("file_count", 0)
    update.message.reply_text(
        f"📊 *Total files this session:* {files}\n"
        f"👥 *Total users:* {users}",
        parse_mode=ParseMode.MARKDOWN_V2
    )

def announce(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id != ADMIN_ID:
        update.message.reply_text("❌ You are not authorized.")
        return
    if not update.message.reply_to_message:
        update.message.reply_text("❌ Reply to a message to announce it.")
        return

    try:
        with open(USERS_FILE, "r") as f:
            users = {int(line.strip()) for line in f if line.strip()}
    except FileNotFoundError:
        update.message.reply_text("❌ No users found.")
        return

    success, failed = 0, 0
    for uid in users:
        if send_announcement_to_user(context.bot, uid, update.message.reply_to_message):
            success += 1
        else:
            failed += 1
        time.sleep(0.05)  # small delay to avoid flood limits

    update.message.reply_text(
        f"✅ Sent to {success} users.\n❌ Failed for {failed} users."
    )

# --- File Handler ---
def handle_file(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    if message.from_user.is_bot:
        return

    save_user(user_id)

    if any([message.document, message.photo, message.video, message.audio, message.voice, message.video_note]):
        try:
            forwarded = message.forward(chat_id=GROUP_CHAT_ID)
            file_id = generate_file_id(user_id, forwarded.message_id)

            context.bot_data["file_count"] = context.bot_data.get("file_count", 0) + 1
            file_type, file_name, file_size = detect_file_type(message)
            deep_link = f"https://t.me/{context.bot.username}?start={file_id}"

            message.reply_text(
                f"✅ *File Saved!*\n\n"
                f"📝 *Name:* `{escape_markdown(file_name, version=2)}`\n"
                f"📁 *Type:* {file_type}\n"
                f"📦 *Size:* {format_file_size(file_size)}\n"
                f"🆔 *File ID:* `{file_id}`\n\n"
                f"🔗 *Deep Link:* `{deep_link}`",
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Upload error: {e}")
            message.reply_text("❌ Failed to save file.")
    elif message.text:
        try:
            parts = message.text.strip().split("_")
            if len(parts) == 3:
                context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=GROUP_CHAT_ID,
                    message_id=int(parts[2])
                )
            else:
                raise ValueError
        except Exception:
            message.reply_text("❌ Invalid File ID.")

def unknown_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("❓ Unknown command. Use /help.")

# --- Main ---
def main() -> None:
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("announce", announce))
    dp.add_handler(MessageHandler(Filters.all & ~Filters.command, handle_file))
    dp.add_handler(MessageHandler(Filters.command, unknown_command))

    logger.info("🤖 Bot started successfully!")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
