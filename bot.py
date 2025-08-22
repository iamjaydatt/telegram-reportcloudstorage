import os
import logging
import time
import html
from flask import Flask, send_from_directory, abort
from threading import Thread
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1002627719555"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "5973278509"))
USERS_FILE = "users.txt"
USER_FILES = "user_files.txt"
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

# --- Flask Web App (for file downloads) ---
app = Flask(__name__)

@app.route("/files/<path:filename>")
def download_file(filename):
    """Serve files from storage"""
    filepath = os.path.join(FILES_DIR, filename)
    if not os.path.exists(filepath):
        abort(404, description="File not found")
    return send_from_directory(FILES_DIR, filename, as_attachment=True)

def run_flask():
    """Run Flask server on port 8080 (Koyeb requirement)"""
    app.run(host="0.0.0.0", port=8080)

# --- Helpers ---
def save_user(user_id: int) -> None:
    """Save user ID if new"""
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

def save_user_file(user_id: int, file_id: str, filename: str):
    """Log file uploaded by a user"""
    try:
        with open(USER_FILES, "a") as f:
            f.write(f"{user_id}|{file_id}|{filename}\n")
    except Exception as e:
        logger.error(f"Error saving user file: {e}")

def get_user_files(user_id: int, limit: int = 10):
    """Get last N files uploaded by user"""
    files = []
    try:
        with open(USER_FILES, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 3 and parts[0] == str(user_id):
                    files.append((parts[1], parts[2]))
    except FileNotFoundError:
        return []
    return files[-limit:]

def generate_file_id(user_id: int, message_id: int) -> str:
    """Unique file ID = timestamp + user + message"""
    timestamp = int(time.time())
    return f"{timestamp}_{user_id}_{message_id}"

def get_download_domain() -> str:
    """Domain for direct links (custom or default Koyeb)"""
    return os.getenv("CUSTOM_DOMAIN", f"{os.getenv('KOYEB_APP_NAME', 'your-app')}.koyeb.app")

# --- Telegram Handlers ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 <b>Welcome to Report Cloud Storage!</b>\n\n"
        "📤 Send me any file and I’ll save it with a <b>Deep Link</b> and <b>Direct Download</b>.\n\n"
        "📥 Retrieve later with:\n<code>/get &lt;file_id&gt;</code>\n"
        "📂 List your uploads:\n<code>/myfiles</code>\n"
        "📊 Stats:\n<code>/stats</code>",
        parse_mode=ParseMode.HTML
    )

def handle_file(update: Update, context: CallbackContext):
    """Save uploaded files and return links"""
    global file_count
    message = update.message
    user_id = message.from_user.id
    save_user(user_id)

    file_type, file_id, ext, file_size = "File", None, "bin", 0

    try:
        if message.document:
            file_type = "Document"
            file_id = message.document.file_id
            ext = message.document.file_name.split(".")[-1] if "." in message.document.file_name else "bin"
            file_size = message.document.file_size
        elif message.photo:
            file_type, file_id, ext = "Photo", message.photo[-1].file_id, "jpg"
        elif message.video:
            file_type, file_id, ext, file_size = "Video", message.video.file_id, "mp4", message.video.file_size
        elif message.audio:
            file_type, file_id, ext, file_size = "Audio", message.audio.file_id, "mp3", message.audio.file_size
        elif message.voice:
            file_type, file_id, ext, file_size = "Voice", message.voice.file_id, "ogg", message.voice.file_size
        elif message.video_note:
            file_type, file_id, ext = "Video Note", message.video_note.file_id, "mp4"
        elif message.animation:
            file_type, file_id, ext = "Animation", message.animation.file_id, "mp4"
        elif message.sticker:
            file_type, file_id, ext = "Sticker", message.sticker.file_id, "webp"
        else:
            message.reply_text("❌ Unsupported file type.")
            return

        # Forward to storage group
        forwarded = message.forward(chat_id=GROUP_CHAT_ID)
        file_unique_id = generate_file_id(user_id, forwarded.message_id)

        # Filename = File ID + extension
        filename = f"{file_unique_id}.{ext}"
        local_path = os.path.join(FILES_DIR, filename)

        # Download file
        file = context.bot.get_file(file_id)
        file.download(local_path)

        file_count += 1
        save_user_file(user_id, file_unique_id, filename)

        logger.info(f"Saved file: {filename}")
        size_kb = round(file_size / 1024) if file_size else "?"

        # Links
        direct_link = f"https://{get_download_domain()}/files/{filename}"
        deep_link = f"https://t.me/{context.bot.username}?start={file_unique_id}"

        message.reply_text(
            f"✅ <b>File Saved!</b>\n\n"
            f"📝 <b>Name:</b> <code>{html.escape(filename)}</code>\n"
            f"📁 <b>Type:</b> {file_type}\n"
            f"📦 <b>Size:</b> {size_kb} KB\n"
            f"🆔 <b>File ID:</b> <code>{file_unique_id}</code>\n\n"
            f"🔗 <b>Deep Link:</b>\n<a href='{deep_link}'>{deep_link}</a>\n\n"
            f"🔗 <b>Direct Download:</b>\n<a href='{direct_link}'>{direct_link}</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        message.reply_text("❌ Failed to save your file. Please try again.")

def get_file(update: Update, context: CallbackContext):
    """Retrieve file by ID"""
    if not context.args:
        update.message.reply_text("❌ Usage: <code>/get &lt;file_id&gt;</code>", parse_mode=ParseMode.HTML)
        return

    file_id = context.args[0]
    for fname in os.listdir(FILES_DIR):
        if fname.startswith(file_id):
            direct_link = f"https://{get_download_domain()}/files/{fname}"
            update.message.reply_text(
                f"📂 <b>File Found!</b>\n\n"
                f"📝 <b>Name:</b> <code>{html.escape(fname)}</code>\n"
                f"🔗 <b>Direct Download:</b>\n<a href='{direct_link}'>{direct_link}</a>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            return
    update.message.reply_text("❌ File not found. Please check the ID.", parse_mode=ParseMode.HTML)

def myfiles(update: Update, context: CallbackContext):
    """List last 10 files of a user"""
    user_id = update.message.from_user.id
    files = get_user_files(user_id, limit=10)

    if not files:
        update.message.reply_text("📭 You haven't uploaded any files yet.", parse_mode=ParseMode.HTML)
        return

    text = "📂 <b>Your Recent Files</b>\n\n"
    for fid, fname in files:
        direct_link = f"https://{get_download_domain()}/files/{fname}"
        text += f"🆔 <code>{fid}</code>\n<a href='{direct_link}'>Download</a>\n\n"

    update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def stats(update: Update, context: CallbackContext):
    """Show usage statistics"""
    try:
        with open(USERS_FILE, "r") as f:
            users = len(f.readlines())
    except FileNotFoundError:
        users = 0

    update.message.reply_text(
        f"📊 <b>Stats</b>\n\n"
        f"👤 <b>Users:</b> {users}\n"
        f"📦 <b>Files this session:</b> {file_count}",
        parse_mode=ParseMode.HTML
    )

def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("❓ Unknown command. Use /start to begin.", parse_mode=ParseMode.HTML)

# --- Main ---
def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("get", get_file))
    dp.add_handler(CommandHandler("myfiles", myfiles))
    dp.add_handler(MessageHandler(Filters.all & ~Filters.command, handle_file))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    # Run Flask in thread
    Thread(target=run_flask).start()

    logger.info("🤖 Bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
