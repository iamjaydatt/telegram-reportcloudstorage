import os
import logging
import time
import html
from flask import Flask, send_from_directory
from threading import Thread
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# --- Config from Environment Variables ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1002627719555"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "5973278509"))
USERS_FILE = "users.txt"
FILES_DIR = "files"

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is not set. Please configure environment variables in Koyeb.")

os.makedirs(FILES_DIR, exist_ok=True)

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

file_count = 0

# --- Flask App to serve files ---
app = Flask(__name__)

@app.route("/files/<path:filename>")
def download_file(filename):
    """Serve files stored in the /files directory"""
    return send_from_directory(FILES_DIR, filename, as_attachment=True)

def run_flask():
    """Run Flask web server on port 8080 (Koyeb requirement)"""
    app.run(host="0.0.0.0", port=8080)

# --- Helpers ---
def save_user(user_id: int) -> None:
    """Save user ID to file if not already stored"""
    try:
        users = set()
        try:
            with open(USERS_FILE, "r") as f:
                users = set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            pass
        if str(user_id) not in users:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")

def generate_file_id(user_id: int, message_id: int) -> str:
    timestamp = int(time.time())
    return f"{timestamp}_{user_id}_{message_id}"

def generate_filename(prefix: str, ext: str) -> str:
    timestamp = int(time.time())
    return f"{prefix}_{timestamp}.{ext}"

def get_download_domain() -> str:
    """Get the domain for direct download links"""
    return os.getenv("CUSTOM_DOMAIN", f"{os.getenv('KOYEB_APP_NAME', 'your-app-name')}.koyeb.app")

# --- Telegram Handlers ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Welcome to Report Cloud Storage!\n\n"
        "📁 Send me any file (document, video, audio, photo, sticker, etc)\n"
        "and I’ll save it and give you both a *deep link* and a *direct download link*."
    )

def handle_file(update: Update, context: CallbackContext):
    global file_count
    message = update.message
    user_id = message.from_user.id
    save_user(user_id)

    file_type = "File"
    file_id = None
    filename = None
    file_size = 0

    try:
        if message.document:
            file_type = "Document"
            file_id = message.document.file_id
            filename = message.document.file_name or generate_filename("document", "bin")
            file_size = message.document.file_size
        elif message.photo:
            file_type = "Photo"
            file_id = message.photo[-1].file_id
            filename = generate_filename("photo", "jpg")
        elif message.video:
            file_type = "Video"
            file_id = message.video.file_id
            filename = generate_filename("video", "mp4")
            file_size = message.video.file_size
        elif message.audio:
            file_type = "Audio"
            file_id = message.audio.file_id
            filename = generate_filename("audio", "mp3")
            file_size = message.audio.file_size
        elif message.voice:
            file_type = "Voice"
            file_id = message.voice.file_id
            filename = generate_filename("voice", "ogg")
            file_size = message.voice.file_size
        elif message.video_note:
            file_type = "Video Note"
            file_id = message.video_note.file_id
            filename = generate_filename("videonote", "mp4")
        elif message.animation:
            file_type = "Animation"
            file_id = message.animation.file_id
            filename = generate_filename("animation", "mp4")
        elif message.sticker:
            file_type = "Sticker"
            file_id = message.sticker.file_id
            filename = generate_filename("sticker", "webp")
        else:
            message.reply_text("❌ Unsupported file type.")
            return

        # Forward to storage group (like original bot)
        forwarded = message.forward(chat_id=GROUP_CHAT_ID)
        file_unique_id = generate_file_id(user_id, forwarded.message_id)

        # Download file locally for direct link
        file = context.bot.get_file(file_id)
        local_path = os.path.join(FILES_DIR, filename)
        file.download(local_path)

        file_count += 1
        size_kb = round(file_size / 1024) if file_size else "?"

        # Direct + Deep links
        direct_link = f"https://{get_download_domain()}/files/{filename}"
        deep_link = f"https://t.me/{context.bot.username}?start={file_unique_id}"

        message.reply_text(
            f"✅ *File Saved!*\n\n"
            f"📝 *Name:* `{html.escape(filename)}`\n"
            f"📁 *Type:* {file_type}\n"
            f"📦 *Size:* {size_kb} KB\n"
            f"🆔 *File ID:* `{file_unique_id}`\n\n"
            f"🔗 *Deep Link:*\n{deep_link}\n\n"
            f"🔗 *Direct Download:*\n{direct_link}",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        message.reply_text("❌ Failed to save your file. Please try again.")

def stats(update: Update, context: CallbackContext):
    update.message.reply_text(
        f"📊 Total files saved this session: *{file_count}*",
        parse_mode=ParseMode.MARKDOWN
    )

def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("❓ Unknown command. Use /start to begin.")

# --- Main ---
def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(MessageHandler(Filters.all & ~Filters.command, handle_file))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    # Run Flask in a separate thread
    Thread(target=run_flask).start()

    logger.info("🤖 Bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
