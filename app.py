import asyncio
import os
import re
import subprocess
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

import yt_dlp
from dotenv import load_dotenv


# Завантажуємо .env файл
print("📄 Завантаження змінних середовища з /.env ...")

load_dotenv(".env", override=True)

# DEBUG
from dotenv import dotenv_values
from pathlib import Path
print("📄 DEBUG: Перевіряємо файл /.env ...")
print(" - exists:", Path(".env").exists())

env_file_values = dotenv_values(".env")




async def download_audio(url: str, output_dir: Path) -> Path:
    print(f"🎧 Починаємо обробку аудіо за посиланням: {url}")
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
        print("📥 Завантаження аудіостріму...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        print("🔊 Конвертація у MP3...")
        original_filepath = Path(ydl.prepare_filename(info))
        mp3_filepath = original_filepath.with_suffix(".mp3")
        print(f"🎉 Готово! MP3 файл створено: {mp3_filepath}")
        return mp3_filepath

    except Exception as exc:
        print(f"❌ Сталася помилка під час обробки аудіо: {exc}")
        raise


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    print(f"💬 Отримано нове повідомлення: {text}")

    youtube_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    match = youtube_regex.search(text)

    if not match:
        print("🙅 Повідомлення не містить YouTube посилання")
        await message.reply_text("Будь ласка, надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)
    print(f"🎯 Витягнуто YouTube посилання: {url}")

    await message.reply_text("Готуємо аудіо... 🎶", quote=False)
    
    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))

    try:
        mp3_file = await download_audio(url, download_dir)
    except Exception as exc:
        print(f"💥 Завантаження не вдалося: {exc}")
        await message.reply_text(f"Не вдалося завантажити аудіо: {exc}")
        return

    try:
        print(f"📤 Надсилаємо MP3 файл користувачу: {mp3_file.name}")
        with mp3_file.open("rb") as audio_stream:
            await message.reply_audio(audio=audio_stream, filename=mp3_file.name)
        print("✅ Файл успішно надіслано")

    except Exception as exc:
        print(f"❌ Не вдалося надіслати файл: {exc}")
        await message.reply_text(f"Помилка надсилання файлу: {exc}")



async def main():
    print("🚀 Запуск Telegram-бота...")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("❗ TELEGRAM_BOT_TOKEN не встановлено")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    await app.initialize()
    await app.start()

    print("🤖 Бот працює. Очікування...")
    await app.updater.start_polling()

    await asyncio.Event().wait()  # ПРОЦЕС ТРИМАЄ ЖИВИМ

if __name__ == "__main__":
    asyncio.run(main())