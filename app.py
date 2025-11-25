import os
import re
import sys
import time
import json
import fcntl
import logging
import asyncio
import signal
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
import aiohttp


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
lock_file = None

def lock_or_exit():
    global lock_file
    try:
        lock_file = open("/tmp/ytdlbot.lock", "w")
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log.info("🔒 lock acquired")
    except IOError:
        log.error("🚫 another instance is running")
        sys.exit(1)

def release_lock():
    global lock_file
    if lock_file:
        try:
            fcntl.lockf(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            os.unlink("/tmp/ytdlbot.lock")
            log.info("🔓 lock released")
        except:
            pass

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
    status_msg = await context.bot.send_message(chat_id, "⏳ Починаємо...")

    download_dir = Path("downloads")
    download_dir.mkdir(exist_ok=True)

    last_update = [0]
    main_loop = asyncio.get_running_loop()

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)

            if total > 0:
                percent = done / total * 100
                if time.time() - last_update[0] > 0.5:
                    last_update[0] = time.time()
                    bar = make_bar(percent)
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit_text(f"⬇️ Завантаження...\n{bar} {percent:.1f}%"),
                        main_loop
                    )
            else:
                if time.time() - last_update[0] > 0.5:
                    last_update[0] = time.time()
                    mb = done / 1024 / 1024
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit_text(f"⬇️ Завантаження...\n{mb:.1f} MB"),
                        main_loop
                    )

        elif d["status"] == "finished":
            asyncio.run_coroutine_threadsafe(
                status_msg.edit_text("🔄 Конвертуємо..."),
                main_loop
            )

    def sync_download():
        opts = {
            "cookiefile": "/tmp/cookies.txt",
            "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "nocheckcertificate": True,
            "progress_hooks": [progress_hook],
            # Clean up filenames
            "restrictfilenames": True,  # ASCII only
        }

        if mode == AUDIO:
            # Download best audio + convert to MP3
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",  # 192kbps = good quality
            }]
            opts["writethumbnail"] = False
            opts["writesubtitles"] = False
            opts["noplaylist"] = True
        else:
            if video_fmt:
                opts["format"] = f"bestvideo[height<={video_fmt}]+bestaudio/best"
            else:
                opts["format"] = "bestvideo+bestaudio"
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            original_path = ydl.prepare_filename(info)
            
            # For audio, return MP3 path
            if mode == AUDIO:
                return str(Path(original_path).with_suffix(".mp3")), mode
            return original_path, mode

    loop = asyncio.get_running_loop()
    filepath, mode = await loop.run_in_executor(POOL, sync_download)

    fp = Path(filepath)
    
    # Verify file exists
    if not fp.exists():
        log.error(f"File not found: {filepath}")
        await status_msg.edit_text("❌ Помилка: файл не знайдено після конвертації")
        return

    # Clean filename: replace URL encoding and special chars with underscores
    clean_name = fp.name
    clean_name = clean_name.replace("%20", "_")  # spaces
    clean_name = re.sub(r'%[0-9A-Fa-f]{2}', '_', clean_name)  # other URL encoding
    clean_name = re.sub(r'[^\w\s._-]', '_', clean_name)  # special chars
    clean_name = re.sub(r'_+', '_', clean_name)  # multiple underscores
    clean_name = clean_name.strip('_')  # trim edges
    
    # Rename file if needed
    if clean_name != fp.name:
        new_fp = fp.parent / clean_name
        fp.rename(new_fp)
        fp = new_fp
        log.info(f"Renamed to: {clean_name}")

    # Check file size
    file_size = fp.stat().st_size
    max_size = 50 * 1024 * 1024  # 50 MB

    # Upload large files to GoFile
    if file_size > max_size:
        file_type = "Відео" if mode == VIDEO else "Аудіо"
        await status_msg.edit_text(f"📤 {file_type} завелике, завантажую на GoFile.io...")
        try:
            link = await upload_to_gofile(fp)
            await status_msg.edit_text(
                f"✅ {file_type} завелике для Telegram ({file_size / 1024 / 1024:.1f} MB).\n\n"
                f"🔗 Файл було завантажено на gofile.io: {link}\n\n"
            )
        except Exception as e:
            log.error(f"Upload to GoFile failed: {e}")
            await status_msg.edit_text(
                f"❌ Не вдалось завантажити: {e}\n\n"
                f"{'Спробуйте нижчу якість або коротше відео.' if mode == VIDEO else 'Спробуйте коротшу аудіодоріжку.'}"
            )
        finally:
            fp.unlink()
        return

    await status_msg.edit_text("📤 Завантаження в Telegram...")

    try:
        with fp.open("rb") as f:
            if mode == AUDIO:
                await context.bot.send_audio(
                    chat_id,
                    audio=InputFile(f, filename=fp.name),
                    caption="✅ Готово"
                )
            else:
                await context.bot.send_video(
                    chat_id,
                    video=InputFile(f, filename=fp.name),
                    caption="✅ Готово",
                    supports_streaming=True
                )

        await status_msg.edit_text("✅ Завантажено в Telegram")
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка відправки: {e}")
        log.error(f"Upload error: {e}")
    
    # Clean up
    try:
        fp.unlink()
    except:
        pass


async def upload_to_fileio(filepath: Path) -> str:
    """Upload to file.io with proper error handling"""
    async with aiohttp.ClientSession() as session:
        with open(filepath, 'rb') as f:
            data = aiohttp.FormData()
            data.add_field('file', f, filename=filepath.name)
            
            try:
                async with session.post('https://file.io', data=data) as resp:
                    if resp.status != 200:
                        raise Exception(f"Upload failed: {resp.status}")
                    
                    content_type = resp.headers.get('Content-Type', '')
                    if 'json' not in content_type:
                        text = await resp.text()
                        raise Exception(f"Unexpected response: {text[:200]}")
                    
                    result = await resp.json()
                    
                    if not result.get('success'):
                        raise Exception(f"Upload failed: {result.get('message', 'unknown error')}")
                    
                    return result['link']
                    
            except aiohttp.ClientError as e:
                raise Exception(f"Network error: {e}")


async def upload_to_gofile(filepath: Path) -> str:
    """Alternative: Upload to gofile.io (more reliable)"""
    async with aiohttp.ClientSession() as session:
        # Get server
        async with session.get('https://api.gofile.io/servers') as resp:
            data = await resp.json()
            server = data['data']['servers'][0]['name']
        
        # Upload file
        with open(filepath, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('file', f, filename=filepath.name)
            
            async with session.post(f'https://{server}.gofile.io/contents/uploadfile', data=form) as resp:
                result = await resp.json()
                if result['status'] != 'ok':
                    raise Exception(f"Upload failed: {result}")
                
                return result['data']['downloadPage']


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
    chat_id = update.effective_chat.id

    # Зберігаємо в обох місцях для сумісності
    context.user_data["yt_url"] = url
    USER_LINK[chat_id] = url

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

    chat_id = update.effective_chat.id
    mode = query.data

    url = context.user_data.get("yt_url") or USER_LINK.get(chat_id)

    if not url:
        await query.edit_message_text("❌ Помилка: посилання не знайдено. Надішліть URL ще раз.")
        return

    if mode == VIDEO:
        keyboard = [
            [InlineKeyboardButton("360p", callback_data="video_360")],
            [InlineKeyboardButton("480p", callback_data="video_480")],
            [InlineKeyboardButton("720p", callback_data="video_720")],
        ]
        await query.edit_message_text(
            "Оберіть якість відео:\n(нижча якість = менший розмір)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif mode.startswith("video_"):
        quality = mode.split("_")[1]
        await download(update, context, url, VIDEO, video_fmt=quality)
    elif mode == AUDIO:
        await download(update, context, url, AUDIO)


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

    # Graceful shutdown handler
    def signal_handler(signum, frame):
        log.info(f"📡 Received signal {signum}, shutting down...")
        release_lock()
        POOL.shutdown(wait=True, cancel_futures=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log.info("🤖 Bot started")
    try:
        app.run_polling(close_loop=False)
    finally:
        release_lock()
        POOL.shutdown(wait=True)


if __name__ == "__main__":
    main()
