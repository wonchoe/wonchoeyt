import os
import re
from pathlib import Path
import sys
import fcntl
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

import yt_dlp
from dotenv import load_dotenv

# --------------------------
# LOGGING
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("ytdl-bot")


# --------------------------
# ENV LOAD
# --------------------------
log.info("📄 Loading .env...")
load_dotenv(".env", override=True)


# --------------------------
# PROCESS LOCK
# --------------------------
def acquire_lock_or_exit():
    lock_file = "/tmp/ytdlbot.lock"
    try:
        global lock_fp
        lock_fp = open(lock_file, 'w')
        fcntl.lockf(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log.info(f"🔒 Lock acquired: {lock_file}")
    except IOError:
        log.error("🚫 Bot instance already running! Exiting…")
        sys.exit(1)

acquire_lock_or_exit()


# --------------------------
# AUDIO DOWNLOAD
# --------------------------
async def download_audio(url: str, output_dir: Path) -> Path:
    log.info(f"🎧 Starting audio download: {url}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "cookiefile": "/tmp/cookies.txt",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }],
        "quiet": True,
        "nocheckcertificate": True,
    }

    try:
        log.info("📥 Extracting audio stream...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        original_filepath = Path(ydl.prepare_filename(info))
        mp3_filepath = original_filepath.with_suffix(".mp3")

        log.info(f"🎉 MP3 created: {mp3_filepath}")
        return mp3_filepath

    except Exception as exc:
        log.error(f"❌ Error while downloading audio: {exc}")
        raise


# --------------------------
# MESSAGE HANDLER
# --------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    log.info(f"💬 Incoming message: {text}")

    youtube_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    match = youtube_regex.search(text)

    if not match:
        log.info("🙅 No YouTube link detected")
        await msg.reply_text("Будь ласка, надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)
    log.info(f"🎯 Extracted URL: {url}")

    await msg.reply_text("Готуємо аудіо... 🎶", quote=False)

    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))

    try:
        mp3_file = await download_audio(url, download_dir)
    except Exception as exc:
        log.error(f"💥 Download failed: {exc}")
        await msg.reply_text(f"Не вдалося завантажити аудіо: {exc}")
        return

    try:
        log.info(f"📤 Sending MP3: {mp3_file.name}")
        with mp3_file.open("rb") as f:
            await msg.reply_audio(audio=f, filename=mp3_file.name)
        log.info("✅ File sent successfully")
    except Exception as exc:
        log.error(f"❌ Error sending file: {exc}")
        await msg.reply_text(f"Помилка надсилання файлу: {exc}")


# --------------------------
# MAIN
# --------------------------
def main():
    log.info("🚀 Starting Telegram bot...")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.critical("❗ TELEGRAM_BOT_TOKEN not set!")
        raise RuntimeError("Missing token")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("🤖 Polling started. Waiting for messages...")

    app.run_polling(close_loop=False)  # важливо для Docker


if __name__ == "__main__":
    main()
