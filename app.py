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
from datetime import datetime, timedelta

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
ACTIVE_DOWNLOADS = set()  # файли, які зараз завантажуються


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
                "player_client": ["web"],  # ✅ Тільки web
                "skip": ["hls", "dash"],
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
# CLEANUP HELPERS
# ---------------------------------------------------------
def cleanup_old_files(download_dir: Path, max_age_minutes: int = 30):
    """Видаляє файли старіші за max_age_minutes, крім активних завантажень"""
    if not download_dir.exists():
        return
    
    now = datetime.now()
    cutoff = now - timedelta(minutes=max_age_minutes)
    
    cleaned = 0
    for file in download_dir.iterdir():
        if not file.is_file():
            continue
            
        # Не чіпаємо активні завантаження
        if str(file) in ACTIVE_DOWNLOADS:
            continue
        
        # Перевіряємо час модифікації
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        if mtime < cutoff:
            try:
                file.unlink()
                cleaned += 1
                log.info(f"🧹 Cleaned old file: {file.name}")
            except Exception as e:
                log.warning(f"Failed to clean {file.name}: {e}")
    
    if cleaned > 0:
        log.info(f"🧹 Cleaned {cleaned} old files")


def cleanup_all_except_active(download_dir: Path):
    """Видаляє всі файли крім активних завантажень"""
    if not download_dir.exists():
        return
    
    cleaned = 0
    for file in download_dir.iterdir():
        if not file.is_file():
            continue
            
        # Не чіпаємо активні завантаження
        if str(file) in ACTIVE_DOWNLOADS:
            continue
        
        try:
            file.unlink()
            cleaned += 1
            log.info(f"🧹 Cleaned: {file.name}")
        except Exception as e:
            log.warning(f"Failed to clean {file.name}: {e}")
    
    if cleaned > 0:
        log.info(f"🧹 Cleaned {cleaned} files")


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

    # Очищуємо старі файли перед початком
    cleanup_old_files(download_dir, max_age_minutes=30)

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
            "restrictfilenames": True,
            # ✅ Тільки web client
            "extractor_args": {
                "youtube": {
                    "player_client": ["web"],
                    "skip": ["hls", "dash"],
                }
            }
        }

        if mode == AUDIO:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            opts["writethumbnail"] = False
            opts["writesubtitles"] = False
            opts["noplaylist"] = True
        else:
            if video_fmt:
                opts["format"] = f"bestvideo[height<={video_fmt}]+bestaudio/best"
            else:
                opts["format"] = "bestvideo+bestaudio/best"
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
    
    # Додаємо файл до активних завантажень
    ACTIVE_DOWNLOADS.add(str(fp))
    
    try:
        # Verify file exists
        if not fp.exists():
            log.error(f"File not found: {filepath}")
            await status_msg.edit_text("❌ Помилка: файл не знайдено після конвертації")
            return

        # Clean filename: replace URL encoding and special chars with underscores
        clean_name = fp.name
        clean_name = clean_name.replace("%20", "_")
        clean_name = re.sub(r'%[0-9A-Fa-f]{2}', '_', clean_name)
        clean_name = re.sub(r'[^\w\s._-]', '_', clean_name)
        clean_name = re.sub(r'_+', '_', clean_name)
        clean_name = clean_name.strip('_')
        
        # Rename file if needed
        if clean_name != fp.name:
            # Видаляємо старий шлях з активних
            ACTIVE_DOWNLOADS.discard(str(fp))
            
            new_fp = fp.parent / clean_name
            fp.rename(new_fp)
            fp = new_fp
            
            # Додаємо новий шлях до активних
            ACTIVE_DOWNLOADS.add(str(fp))
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
            return

        await status_msg.edit_text("📤 Завантаження в Telegram...")

        try:
            with fp.open("rb") as f:
                if mode == AUDIO:
                    await context.bot.send_audio(
                        chat_id,
                        audio=InputFile(f, filename=fp.name)
                    )
                else:
                    await context.bot.send_video(
                        chat_id,
                        video=InputFile(f, filename=fp.name),
                        supports_streaming=True
                    )

            # Видаляємо статусне повідомлення після успішного завантаження
            try:
                await status_msg.delete()
            except Exception:
                pass  # Ігноруємо помилки видалення
                
        except Exception as e:
            await status_msg.edit_text(f"❌ Помилка відправки: {e}")
            log.error(f"Upload error: {e}")
    
    finally:
        # Видаляємо з активних і прибираємо файл
        ACTIVE_DOWNLOADS.discard(str(fp))
        try:
            if fp.exists():
                fp.unlink()
                log.info(f"🗑️ Removed: {fp.name}")
        except Exception as e:
            log.warning(f"Failed to remove {fp.name}: {e}")


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

    # Знайти URL
    url_match = re.search(r'https?://[^\s]+', link)
    if not url_match:
        await msg.reply_text("Будь ласка, надішліть посилання.")
        return

    url = url_match.group(0)
    
    # ✅ Логування URL
    log.info(f"📥 Received URL: {url}")

    # ✅ Перевірка cookies
    cookies_path = Path("/tmp/cookies.txt")
    if cookies_path.exists():
        cookie_age = datetime.now() - datetime.fromtimestamp(cookies_path.stat().st_mtime)
        log.info(f"🍪 Cookies found, age: {cookie_age.days}d {cookie_age.seconds // 3600}h")
        
        # Показуємо перші 5 рядків cookies для дебагу
        try:
            with open(cookies_path, 'r') as f:
                lines = f.readlines()[:5]
                log.info(f"🍪 First cookies lines: {[l.strip()[:50] for l in lines if not l.startswith('#')]}")
        except Exception as e:
            log.warning(f"⚠️ Can't read cookies: {e}")
    else:
        log.warning("⚠️ No cookies.txt found at /tmp/cookies.txt")

    # Перевіряємо чи yt-dlp може його обробити
    try:
        opts = {
            "quiet": True,
            "cookiefile": "/tmp/cookies.txt",
            "nocheckcertificate": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web"],
                    "skip": ["hls", "dash"],
                }
            }
        }
        
        log.info(f"🔍 Extracting info with opts: {opts}")
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # ✅ Перевірка чи є аудіо/відео формати
            formats = info.get('formats', [])
            has_formats = any(
                f.get('vcodec') != 'none' or f.get('acodec') != 'none'
                for f in formats
            )
            
            if not has_formats:
                log.error("❌ No audio/video formats available, only images")
                log.info(f"Available formats: {[f.get('format_id') for f in formats]}")
                
                # ✅ Спробувати через embed (fallback)
                try:
                    log.info("🔄 Trying embed extractor as fallback...")
                    opts_embed = opts.copy()
                    opts_embed["extractor_args"] = {
                        "youtube": {
                            "player_client": ["web_embedded"],
                            "skip": ["hls", "dash"],
                        }
                    }
                    
                    with yt_dlp.YoutubeDL(opts_embed) as ydl_embed:
                        info = ydl_embed.extract_info(url, download=False)
                        formats = info.get('formats', [])
                        has_formats = any(
                            f.get('vcodec') != 'none' or f.get('acodec') != 'none'
                            for f in formats
                        )
                        
                        if not has_formats:
                            raise Exception("Still no formats")
                        
                        log.info("✅ Embed extractor worked!")
                        
                except Exception as embed_err:
                    log.error(f"❌ Embed fallback failed: {embed_err}")
                    await msg.reply_text(
                        "❌ **YouTube заблокував доступ**\n\n"
                        "Доступні тільки зображення (thumbnails).\n\n"
                        "🔄 Спробуйте:\n"
                        "• Інше відео\n"
                        "• Почекати 10-15 хвилин\n"
                        "• Повідомити адміна (@username)\n\n"
                        "⚠️ YouTube посилив захист від ботів",
                        parse_mode="Markdown"
                    )
                    return
            
            # ✅ Логування інфо
            log.info(f"✅ Info extracted successfully")
            log.info(f"   Title: {info.get('title', 'N/A')[:50]}")
            log.info(f"   Uploader: {info.get('uploader', 'N/A')}")
            log.info(f"   Duration: {info.get('duration', 0)}s")
            log.info(f"   Formats: {len(formats)}")
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        log.error(f"❌ DownloadError: {error_msg}")
        
        # Детальні повідомлення про помилки
        if "Sign in to confirm" in error_msg or "bot" in error_msg.lower():
            await msg.reply_text(
                "❌ **YouTube bot detection**\n\n"
                "YouTube заблокував доступ.\n\n"
                "🔄 Спробуйте:\n"
                "• Почекати 5-10 хвилин\n"
                "• Інше відео\n"
                "• Повідомити адміна про проблему\n\n"
                f"Помилка: `{error_msg[:150]}`",
                parse_mode="Markdown"
            )
        elif "Video unavailable" in error_msg:
            await msg.reply_text(
                "❌ **Відео недоступне**\n\n"
                "Можливі причини:\n"
                "• Відео приватне\n"
                "• Відео видалене\n"
                "• Географічні обмеження\n\n"
                f"Деталі: `{error_msg[:150]}`",
                parse_mode="Markdown"
            )
        elif "429" in error_msg or "Too Many Requests" in error_msg:
            await msg.reply_text(
                "❌ **Забагато запитів**\n\n"
                "YouTube тимчасово заблокував доступ.\n"
                "Почекайте 10-15 хвилин.",
                parse_mode="Markdown"
            )
        else:
            await msg.reply_text(
                f"❌ **Помилка YouTube**\n\n"
                f"`{error_msg[:200]}`\n\n"
                f"Спробуйте інше відео або повідомте адміна.",
                parse_mode="Markdown"
            )
        return
        
    except Exception as e:
        error_msg = str(e)
        log.error(f"❌ Unexpected error: {error_msg}")
        log.exception("Full traceback:")
        
        await msg.reply_text(
            f"❌ **Несподівана помилка**\n\n"
            f"Тип: `{type(e).__name__}`\n"
            f"Повідомлення: `{error_msg[:150]}`\n\n"
            f"Це посилання не підтримується або є проблема з сервером.",
            parse_mode="Markdown"
        )
        return

    # Зберігаємо
    context.user_data["yt_url"] = url
    USER_LINK[update.effective_chat.id] = url

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
        # Видаляємо повідомлення з вибором якості
        try:
            await query.message.delete()
        except Exception:
            pass
        
        quality = mode.split("_")[1]
        await download(update, context, url, VIDEO, video_fmt=quality)
    elif mode == AUDIO:
        # Видаляємо повідомлення "Що завантажити?"
        try:
            await query.message.delete()
        except Exception:
            pass
        
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

    # Очищуємо всі старі файли при старті
    download_dir = Path("downloads")
    download_dir.mkdir(exist_ok=True)
    cleanup_all_except_active(download_dir)

    # Graceful shutdown handler
    def signal_handler(signum, frame):
        log.info(f"📡 Received signal {signum}, shutting down...")
        release_lock()
        POOL.shutdown(wait=True, cancel_futures=False)
        # Очищуємо при виході
        cleanup_all_except_active(download_dir)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log.info("🤖 Bot started")
    try:
        app.run_polling(close_loop=False)
    finally:
        release_lock()
        POOL.shutdown(wait=True)
        cleanup_all_except_active(download_dir)


if __name__ == "__main__":
    main()
