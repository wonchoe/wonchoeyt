import asyncio
import os
import re
import subprocess
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

import yt_dlp


def update_yt_dlp() -> None:
    try:
        print("🔄 Updating yt dlp to the latest version...")
        subprocess.check_call([
            os.environ.get("PYTHON", "python"),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--upgrade",
            "yt-dlp",
        ])
        print("✅ yt dlp updated successfully")
    except Exception as exc:
        print(f"⚠️ Warning updating yt dlp failed: {exc}")


async def download_audio(url: str, output_dir: Path) -> Path:
    print(f"🎧 Starting audio extraction from URL: {url}")
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
        print("📥 Downloading audio stream...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        print("🔊 Converting to MP3...")
        original_filepath = Path(ydl.prepare_filename(info))
        mp3_filepath = original_filepath.with_suffix(".mp3")
        print(f"🎉 Done MP3 ready: {mp3_filepath}")
        return mp3_filepath

    except Exception as exc:
        print(f"❌ Error while processing audio: {exc}")
        raise


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    print(f"💬 New message received: {text}")

    youtube_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    match = youtube_regex.search(text)

    if not match:
        print("🙅 Not a YouTube link")
        await message.reply_text("Будь ласка надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)
    print(f"🎯 Extracted YouTube URL: {url}")

    await message.reply_text("Готуємо аудіо... 🎶", quote=False)

    update_yt_dlp()
    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))

    try:
        mp3_file = await download_audio(url, download_dir)
    except Exception as exc:
        print(f"💥 Download failed: {exc}")
        await message.reply_text(f"Не вдалося завантажити аудіо: {exc}")
        return

    try:
        print(f"📤 Sending MP3 file to user: {mp3_file.name}")
        with mp3_file.open("rb") as audio_stream:
            await message.reply_audio(audio=audio_stream, filename=mp3_file.name)
        print("✅ File sent successfully")

    except Exception as exc:
        print(f"❌ Failed to send file: {exc}")
        await message.reply_text(f"Не вдалося відправити файл: {exc}")


def main():
    print("🚀 Telegram bot is starting up...")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("❗ TELEGRAM_BOT_TOKEN is not set")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🤖 Bot is running. Press Ctrl + C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
