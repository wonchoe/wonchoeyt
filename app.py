import os
import re
import sys
import time
import json
import fcntl
import logging
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import yt_dlp


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("ytbot")


# ---------------------------------------------------------
# ENV
# ---------------------------------------------------------
load_dotenv(".env", override=True)


# ---------------------------------------------------------
# SINGLE INSTANCE LOCK
# ---------------------------------------------------------
def lock_or_exit():
    try:
        fp = open("/tmp/ytdlbot.lock", "w")
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log.info("🔒 lock acquired")
    except IOError:
        log.error("🚫 another instance is running")
        sys.exit(1)


lock_or_exit()


# ---------------------------------------------------------
# STORAGE
# ---------------------------------------------------------
USER_LINK = {}   # chat_id → link


# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------
AUDIO = "audio"
VIDEO = "video"
QUALITY = "quality"


# ---------------------------------------------------------
# PROGRESS BAR HELPERS
# ---------------------------------------------------------
def make_bar(percent: float):
    filled = int(percent / 5)
    return "█" * filled + "░" * (20 - filled)


# ---------------------------------------------------------
# YT-DLP THREAD EXECUTOR
# ---------------------------------------------------------
POOL = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------
# GET FORMATS
# ---------------------------------------------------------
async def get_formats(url: str):
    options = {
        "quiet": True,
        "cookiefile": "/tmp/cookies.txt",
        "nocheckcertificate": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "web", "android"],
            }
        }
    }
    loop = asyncio.get_running_loop()

    def extract():
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    info = await loop.run_in_executor(POOL, extract)

    out = {}
    for f in info.get("formats", []):
        h = f.get("height")
        if h and f.get("ext") in ["mp4", "webm"]:
            out[h] = f["format_id"]

    out = dict(sorted(out.items(), reverse=True))
    log.info(f"Available formats: {out}")
    return out


# ---------------------------------------------------------
# DOWNLOAD (THREAD) + PROGRESS (ASYNC)
# ---------------------------------------------------------
async def download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    mode: str,
    video_fmt: str | None = None,
):
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(chat_id, "⏳ Starting...")

    download_dir = Path("downloads")
    download_dir.mkdir(exist_ok=True)

    last_update = 0

    # async progress callback
    async def update_progress(d):
        nonlocal last_update

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)

            if total > 0:
                percent = done / total * 100
                if time.time() - last_update > 0.5:
                    last_update = time.time()
                    bar = make_bar(percent)
                    try:
                        await status_msg.edit_text(
                            f"⬇️ Downloading...\n{bar} {percent:.1f}%"
                        )
                    except:
                        pass
            else:
                if time.time() - last_update > 0.5:
                    mb = done / 1024 / 1024
                    try:
                        await status_msg.edit_text(
                            f"⬇️ Downloading...\n{mb:.1f} MB"
                        )
                    except:
                        pass

        elif d["status"] == "finished":
            try:
                await status_msg.edit_text("🔄 Converting...")
            except:
                pass

    # sync wrapper
    def sync_download():
        opts = {
            "cookiefile": "/tmp/cookies.txt",
            "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "nocheckcertificate": True,
            "progress_hooks": [lambda d: asyncio.run_coroutine_threadsafe(update_progress(d), asyncio.get_running_loop())],
        }

        if mode == AUDIO:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }]
        else:
            if video_fmt:
                opts["format"] = f"{video_fmt}+bestaudio/best"
            else:
                opts["format"] = "bestvideo+bestaudio"
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info), mode

    loop = asyncio.get_running_loop()
    filepath, mode = await loop.run_in_executor(POOL, sync_download)

    fp = Path(filepath)
    if mode == AUDIO:
        fp = fp.with_suffix(".mp3")

    await status_msg.edit_text("📤 Uploading...")

    with fp.open("rb") as f:
        await context.bot.send_document(
            chat_id,
            document=InputFile(f, filename=fp.name),
            caption="Готово ✔"
        )

    await status_msg.edit_text("✅ Done")


# ---------------------------------------------------------
# TEXT HANDLER
# ---------------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    link = msg.text.strip()

    yt_re = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+")
    m = yt_re.search(link)
    if not m:
        await msg.reply_text("Будь ласка, надішліть YouTube лінк.")
        return

    USER_LINK[update.effective_chat.id] = m.group(0)

    kb = [
        [InlineKeyboardButton("🎧 Audio", callback_data=AUDIO)],
        [InlineKeyboardButton("🎬 Video", callback_data=VIDEO)],
    ]
    await msg.reply_text("Що завантажити?", reply_markup=InlineKeyboardMarkup(kb))


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    context.user_data["yt_url"] = url   # <——— ФІКС

    keyboard = [
        [InlineKeyboardButton("🎵 Audio", callback_data="audio")],
        [InlineKeyboardButton("🎬 Video", callback_data="video")],
    ]

    await update.message.reply_text(
        "Виберіть формат:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("yt_url")  # <——— ФІКС

    if not url:
        await query.edit_message_text("Немає посилання. Надішліть URL ще раз.")
        return

    data = q.data

    if data == AUDIO:
        await q.edit_message_text("🎧 Завантажуємо аудіо...")
        return await download(update, context, link, AUDIO)

    if data == VIDEO:
        await q.edit_message_text("🔎 Отримуємо формати...")
        formats = await get_formats(link)

        if not formats:
            return await q.edit_message_text("⚠️ Не знайдено форматів.")

        kb = [
            [InlineKeyboardButton(f"{h}p", callback_data=f"{QUALITY}:{h}")]
            for h in formats.keys()
        ]
        return await q.edit_message_text(
            "Оберіть якість:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    if data.startswith(f"{QUALITY}:"):
        height = int(data.split(":")[1])
        formats = await get_formats(link)
        fmt_id = formats.get(height)

        await q.edit_message_text(f"🎬 Завантажуємо {height}p...")
        return await download(update, context, link, VIDEO, fmt_id)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("🤖 Bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
