import os
import logging
import time
import html
from flask import Flask, send_from_directory, abort
from threading import Thread
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1002627719555"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "5973278509"))
USERS_FILE = "users.txt"
USER_FILES = "user_files.txt"
FILES_DIR = "files"

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is not set. Please configure env vars in Koyeb.")

os.makedirs(FILES_DIR, exist_ok=True)

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

file_count = 0

# --- Flask Web App ---
app = Flask(__name__)

@app.route("/files/<path:filename>")
def download_file(filename):
    filepath = os.path.join(FILES_DIR, filename)
    if not os.path.exists(filepath):
        abort(404, description="File not found")
    return send_from_directory(FILES_DIR, filename, as_attachment=True)

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# --- Helpers ---
def save_user(user_id: int):
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

def save_user_file(user_id: int, file_id: str, filename: str, tg_file_id: str, file_type: str, file_size: int):
    try:
        with open(USER_FILES, "a") as f:
            f.write(f"{user_id}|{file_id}|{filename}|{tg_file_id}|{file_type}|{file_size}\n")
    except Exception as e:
        logger.error(f"Error saving user file: {e}")

def find_file_by_id(file_id: str):
    try:
        with open(USER_FILES, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 6 and parts[1] == file_id:
                    return {
                        "filename": parts[2],
                        "tg_file_id": parts[3],
                        "file_type": parts[4],
                        "file_size": parts[5]
                    }
    except FileNotFoundError:
        return None
    return None

def get_user_files(user_id: int, limit: int = 10):
    files = []
    try:
        with open(USER_FILES, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 6 and parts[0] == str(user_id):
                    files.append((parts[1], parts[2], parts[4], parts[5]))
    except FileNotFoundError:
        return []
    return files[-limit:]

def generate_file_id(user_id: int, message_id: int) -> str:
    timestamp = int(time.time())
    return f"{timestamp}_{user_id}_{message_id}"

def get_download_domain() -> str:
    return os.getenv("CUSTOM_DOMAIN", f"{os.getenv('KOYEB_APP_NAME', 'your-app')}.koyeb.app")

# --- File Sending ---
def send_file(update: Update, context: CallbackContext, file_id: str):
    data = find_file_by_id(file_id)
    if not data:
        update.message.reply_text("❌ File not found. Please check the ID.", parse_mode=ParseMode.HTML)
        return

    tg_file_id = data["tg_file_id"]
    filename = data["filename"]
    file_type = data["file_type"]
    file_size = data["file_size"]
    direct_link = f"https://{get_download_domain()}/files/{filename}"

    caption = (
        f"📂 <b>File Retrieved!</b>\n\n"
        f"📝 <b>Name:</b> <code>{html.escape(filename)}</code>\n"
        f"📁 <b>Type:</b> {file_type}\n"
        f"📦 <b>Size:</b> {file_size} KB\n"
        f"🆔 <b>File ID:</b> <code>{file_id}</code>"
    )

    buttons = [[InlineKeyboardButton("📥 Direct Download", url=direct_link)]]
    reply_markup = InlineKeyboardMarkup(buttons)

    try:
        update.message.reply_document(
            document=tg_file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Send file error: {e}")
        update.message.reply_text("❌ Could not send file. Maybe it's too large?", parse_mode=ParseMode.HTML)

# --- Handlers ---
def start(update: Update, context: CallbackContext):
    if context.args:  # Deep link mode
        file_id = context.args[0]
        send_file(update, context, file_id)
        return

    update.message.reply_text(
        "👋 <b>Welcome to Report Cloud Storage!</b>\n\n"
        "📤 Send me any file and I’ll save it with a <b>Deep Link</b> and <b>Direct Download</b>.\n\n"
        "📥 Retrieve later with:\n<code>/get &lt;file_id&gt;</code>\n"
        "📂 List your uploads:\n<code>/myfiles</code>\n"
        "📊 Stats:\n<code>/stats</code>",
        parse_mode=ParseMode.HTML
    )

def handle_file(update: Update, context: CallbackContext):
    global file_count
    message = update.message
    user_id = message.from_user.id
    save_user(user_id)

    file_type, file_id, ext, file_size = "File", None, "bin", 0

    try:
        if message.document:  # Covers ALL file types (.mkv, .zip, .apk, .exe, etc.)
            file_type = "Document"
            file_id = message.document.file_id
            filename_original = message.document.file_name or "file.bin"
            ext = filename_original.split(".")[-1] if "." in filename_original else "bin"
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

        forwarded = message.forward(chat_id=GROUP_CHAT_ID)
        file_unique_id = generate_file_id(user_id, forwarded.message_id)

        filename = f"{file_unique_id}.{ext}"
        local_path = os.path.join(FILES_DIR, filename)

        file = context.bot.get_file(file_id)
        file.download(local_path)

        file_count += 1
        save_user_file(
            user_id, file_unique_id, filename, file_id,
            file_type, round(file_size / 1024) if file_size else "?"
        )

        direct_link = f"https://{get_download_domain()}/files/{filename}"
        deep_link = f"https://t.me/{context.bot.username}?start={file_unique_id}"

        caption = (
            f"✅ <b>File Saved!</b>\n\n"
            f"📝 <b>Name:</b> <code>{html.escape(filename)}</code>\n"
            f"📁 <b>Type:</b> {file_type}\n"
            f"📦 <b>Size:</b> {round(file_size / 1024) if file_size else '?'} KB\n"
            f"🆔 <b>File ID:</b> <code>{file_unique_id}</code>"
        )

        buttons = [
            [InlineKeyboardButton("🔗 Deep Link", url=deep_link)],
            [InlineKeyboardButton("📥 Direct Download", url=direct_link)]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        message.reply_document(
            document=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        message.reply_text("❌ Failed to save your file. Please try again.")

def get_file(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("❌ Usage: <code>/get &lt;file_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    send_file(update, context, context.args[0])

def myfiles(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    files = get_user_files(user_id, limit=10)

    if not files:
        update.message.reply_text("📭 You haven't uploaded any files yet.", parse_mode=ParseMode.HTML)
        return

    text = "📂 <b>Your Recent Files</b>\n\n"
    for fid, fname, ftype, fsize in files:
        direct_link = f"https://{get_download_domain()}/files/{fname}"
        text += (
            f"📝 <b>Name:</b> <code>{html.escape(fname)}</code>\n"
            f"📁 <b>Type:</b> {ftype}\n"
            f"📦 <b>Size:</b> {fsize} KB\n"
            f"🆔 <code>{fid}</code>\n"
            f"<a href='{direct_link}'>📥 Download</a>\n\n"
        )

    update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def stats(update: Update, context: CallbackContext):
    try:
        with open(USERS_FILE, "r") as f:
            users = len(f.readlines())
    except FileNotFoundError:
        users = 0

    try:
        with open(USER_FILES, "r") as f:
            total_files = len(f.readlines())
    except FileNotFoundError:
        total_files = 0

    update.message.reply_text(
        f"📊 <b>Stats</b>\n\n"
        f"👤 <b>Users:</b> {users}\n"
        f"📦 <b>Files uploaded:</b> {total_files}\n"
        f"📥 <b>Files this session:</b> {file_count}",
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

    Thread(target=run_flask).start()
    logger.info("🤖 Bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
