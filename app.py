"""
Telegram bot service for downloading and converting YouTube videos to MP3.

This script uses the yt‑dlp library to fetch the best available audio stream
from a given YouTube link and converts it into MP3 using FFmpeg.  The
application also exposes an asynchronous Telegram bot that listens for
messages containing YouTube URLs and responds with the converted MP3 file.

The `update_yt_dlp` function attempts to keep the yt‑dlp package up to
date by running a pip upgrade at runtime.  Keeping yt‑dlp current is
important because the tool relies on regular updates to parse web pages
correctly; official documentation recommends updating regularly【907565628753983†L320-L343】.

Environment variables:

  TELEGRAM_BOT_TOKEN  Required. The bot token provided by BotFather.
  DOWNLOAD_DIR        Optional. Directory for storing downloaded files.

Dependencies:

  - yt-dlp: for downloading media from YouTube.
  - python-telegram-bot: for interacting with the Telegram Bot API.
  - ffmpeg: system package used by yt-dlp to perform audio extraction.

Usage:

  Run this script directly with Python.  The bot will start polling for
  messages.  When a user sends a YouTube link, the bot downloads the
  associated audio, converts it to MP3 and sends the file back.

Note:

  Always respect copyright law when downloading media.  Only download
  content that you have the right to access【907565628753983†L50-L66】.
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path

from telegram import Update
from telegram.ext import (ApplicationBuilder, ContextTypes,
                          MessageHandler, filters)

import yt_dlp


def update_yt_dlp() -> None:
    """Attempt to update the yt-dlp package in place.

    Regular updates ensure that yt‑dlp can continue to download content
    successfully when video hosting sites change their formats.  This
    function calls pip to upgrade yt‑dlp to its latest version.  If the
    update fails (for example, due to network issues), the function logs
    the error and continues with the existing installed version.
    """
    try:
        # Use sys.executable to ensure pip corresponds to the running Python
        subprocess.check_call([
            os.environ.get("PYTHON", "python"),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--upgrade",
            "yt-dlp",
        ])
    except Exception as exc:
        print(f"Warning: yt-dlp update failed: {exc}")


async def download_audio(url: str, output_dir: Path) -> Path:
    """Download and convert a YouTube video to MP3.

    Args:
        url: The URL of the YouTube video to download.
        output_dir: Directory where the downloaded file should be stored.

    Returns:
        Path to the resulting MP3 file.

    This function uses yt‑dlp's post‑processing capabilities to extract the
    best audio from the given URL and convert it to MP3 using FFmpeg.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Configuration for yt-dlp: choose best audio and post-process to MP3
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(output_dir / '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',  # Use '0' to let ffmpeg pick the best quality【728962533621149†L312-L336】
        }],
        'quiet': True,
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Derive the path of the converted MP3 file
        original_filepath = Path(ydl.prepare_filename(info))
        mp3_filepath = original_filepath.with_suffix('.mp3')
    return mp3_filepath


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages from Telegram users.

    If the message contains a YouTube URL, the bot attempts to download
    the audio, convert it to MP3 and send it back.  Otherwise, it
    instructs the user to send a valid YouTube link.
    """
    message = update.message
    if not message or not message.text:
        return
    text = message.text.strip()
    # Simple pattern to detect YouTube URLs
    youtube_regex = re.compile(r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+')
    match = youtube_regex.search(text)
    if not match:
        await message.reply_text("Будь ласка надішліть коректне посилання на YouTube.")
        return

    url = match.group(0)
    await message.reply_text("Готуємо аудіо, будь ласка зачекайте...", quote=False)

    # Update yt‑dlp to the latest version before downloading
    update_yt_dlp()
    download_dir = Path(os.environ.get('DOWNLOAD_DIR', 'downloads'))

    try:
        mp3_file = await download_audio(url, download_dir)
    except Exception as exc:
        await message.reply_text(f"Не вдалося завантажити аудіо: {exc}")
        return

    # Send the MP3 file back to the user
    try:
        with mp3_file.open('rb') as audio_stream:
            await message.reply_audio(audio=audio_stream, filename=mp3_file.name)
    except Exception as exc:
        await message.reply_text(f"Не вдалося відправити файл: {exc}")


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('Please set the TELEGRAM_BOT_TOKEN environment variable.')

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()