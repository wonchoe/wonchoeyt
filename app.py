import os
import re
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import yt_dlp
from dotenv import load_dotenv
import sys
import fcntl

print("📄 Loading .env...")
load_dotenv(".env", override=True)

def acquire_lock_or_exit():
    lock_file = "/tmp/ytdlbot.lock"
    try:
        global lock_fp
        lock_fp = open(lock_file, 'w')
        fcntl.lockf(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(f"🔒 Lock acquired: {lock_file}")
    except IOError:
        print("🚫 Bot instance already running! Exiting…")
        sys.exit(1)

acquire_lock_or_exit()

async def download_audio(url: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }],
        "quiet": True,
        "nocheckcertificate": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    original_filepath = Path(ydl.prepare_filename(info))
    mp3_filepath = original_filepath.with_suffix(".mp3")
    return mp3_filepath


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    youtube_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    match = youtube_regex.search(text)

    if not match:
        await msg.reply_text("Будь ласка, надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)
    await msg.reply_text("Готуємо аудіо... 🎶", quote=False)

    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))
    mp3_file = await download_audio(url, download_dir)

    with mp3_file.open("rb") as f:
        await msg.reply_audio(audio=f, filename=mp3_file.name)


def main():
    print("🚀 Starting bot...")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("❗ TELEGRAM_BOT_TOKEN не встановлено")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Running polling...")
    app.run_polling()  # <-- ГОЛОВНЕ! НІЯКИХ asyncio.run()


if __name__ == "__main__":
    main()
