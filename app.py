import os
import re
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters
)

import yt_dlp
from dotenv import load_dotenv


# Load ENV
print("📄 Loading .env...")
load_dotenv(".env", override=True)


async def download_audio(url: str, output_dir: Path) -> Path:
    print(f"🎧 Downloading audio: {url}")
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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        original_filepath = Path(ydl.prepare_filename(info))
        mp3_filepath = original_filepath.with_suffix(".mp3")
        print(f"🎉 MP3 ready: {mp3_filepath}")

        return mp3_filepath

    except Exception as exc:
        print(f"❌ Error: {exc}")
        raise


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    print(f"💬 Received: {text}")

    youtube_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    match = youtube_regex.search(text)

    if not match:
        await msg.reply_text("Будь ласка, надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)

    await msg.reply_text("Готуємо аудіо... 🎶", quote=False)

    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))

    try:
        mp3_file = await download_audio(url, download_dir)
    except Exception as exc:
        await msg.reply_text(f"Не вдалося завантажити аудіо: {exc}")
        return

    try:
        with mp3_file.open("rb") as file_stream:
            await msg.reply_audio(audio=file_stream, filename=mp3_file.name)
    except Exception as exc:
        await msg.reply_text(f"Помилка надсилання файлу: {exc}")


async def main():
    print("🚀 Starting bot...")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("❗ TELEGRAM_BOT_TOKEN не встановлено")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Running polling (single instance, no conflicts)...")
    await app.run_polling()   # <— ОСНОВНЕ РІШЕННЯ


if __name__ == "__main__":
    asyncio.run(main())
