"""
Multi-platform Media Downloader Bot
Supports: YouTube, Instagram, Facebook, TikTok
"""

import os
import re
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from downloaders import YouTubeDownloader, InstagramDownloader, FacebookDownloader, TikTokDownloader
from utils import cleanup_old_files, cleanup_all_except_active, upload_to_gofile


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
# STORAGE
# ---------------------------------------------------------
USER_LINK = {}  # chat_id → link
ACTIVE_DOWNLOADS = set()  # файли, які зараз завантажуються


# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------
AUDIO = "audio"
VIDEO = "video"
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------
# DOWNLOADERS
# ---------------------------------------------------------
DOWNLOADERS = [
    YouTubeDownloader(),
    InstagramDownloader(),
    FacebookDownloader(),
    TikTokDownloader(),
]


def get_downloader(url: str):
    """Get appropriate downloader for URL"""
    for downloader in DOWNLOADERS:
        downloader_name = downloader.__class__.__name__
        can_handle = downloader.can_handle(url)
        log.debug(f"🔍 {downloader_name}.can_handle({url[:50]}...) = {can_handle}")
        if can_handle:
            log.info(f"✅ Using {downloader_name}")
            return downloader
    log.warning(f"❌ No downloader found for: {url}")
    return None


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
async def safe_edit_message(message, text: str):
    """Safely edit message, ignoring timeout errors"""
    try:
        await message.edit_text(text)
    except Exception as e:
        log.debug(f"Failed to edit message: {e}")


# ---------------------------------------------------------
# PROGRESS BAR
# ---------------------------------------------------------
def make_bar(percent: float):
    filled = int(percent / 5)
    return "█" * filled + "░" * (20 - filled)


# ---------------------------------------------------------
# HANDLE URL
# ---------------------------------------------------------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming URL"""
    msg = update.message
    text = msg.text.strip()
    
    log.info(f"📨 Received message: {text[:100]}")
    
    # Знайти URL
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        await msg.reply_text("Будь ласка, надішліть посилання.")
        return
    
    url = url_match.group(0)
    chat_id = update.effective_chat.id
    
    log.info(f"🔗 Detected URL: {url}")
    
    # Перевірка підтримки
    downloader = get_downloader(url)
    if not downloader:
        await msg.reply_text(
            "❌ Це посилання не підтримується.\n\n"
            "Підтримуються:\n"
            "• YouTube (відео, музика)\n"
            "• Instagram (пости, reels, IGTV)\n"
            "• Facebook (відео, watch)\n"
            "• TikTok (відео)"
        )
        return
    
    # Зберігаємо URL
    context.user_data["url"] = url
    USER_LINK[chat_id] = url
    
    # Визначаємо тип downloader
    if isinstance(downloader, YouTubeDownloader):
        # YouTube - вибір аудіо/відео
        keyboard = [
            [InlineKeyboardButton("🎵 Audio", callback_data="audio")],
            [InlineKeyboardButton("🎬 Video", callback_data="video")],
        ]
        await msg.reply_text("Виберіть формат:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif isinstance(downloader, InstagramDownloader):
        # Instagram - одразу завантажуємо
        await download_instagram(update, context, url)
    
    elif isinstance(downloader, FacebookDownloader):
        # Facebook - одразу завантажуємо відео
        await download_facebook(update, context, url)
    
    elif isinstance(downloader, TikTokDownloader):
        # TikTok - одразу завантажуємо відео
        await download_tiktok(update, context, url)


# ---------------------------------------------------------
# DOWNLOAD INSTAGRAM
# ---------------------------------------------------------
async def download_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download from Instagram"""
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(chat_id, "⏳ Завантажую Instagram...")
    
    cleanup_old_files(DOWNLOAD_DIR, max_age_minutes=30, active_downloads=ACTIVE_DOWNLOADS)
    
    async def progress_callback(status, percent, done, total):
        """Progress updates"""
        if status == "downloading" and percent > 0:
            bar = make_bar(percent)
            await status_msg.edit_text(f"⬇️ Завантаження...\n{bar} {percent:.1f}%")
        elif status == "processing":
            await status_msg.edit_text("🔄 Обробка...")
    
    try:
        log.info(f"📥 Instagram download started: {url}")
        downloader = InstagramDownloader()
        files, media_type = await downloader.download(
            url, 
            DOWNLOAD_DIR,
            progress_callback=progress_callback
        )
        
        log.info(f"✅ Downloaded {len(files)} files, type: {media_type}")
        
        if not files:
            await status_msg.edit_text("❌ Не вдалося завантажити")
            return
        
        # Додаємо до активних
        for fp in files:
            ACTIVE_DOWNLOADS.add(str(fp))
        
        try:
            await status_msg.edit_text("📤 Відправка в Telegram...")
            
            # Перевіряємо загальний розмір для альбомів
            total_size = sum(fp.stat().st_size for fp in files if fp.exists())
            max_size = 50 * 1024 * 1024  # 50 MB per file
            
            # Відправляємо як media group якщо це альбом і всі файли підходять
            if media_type in ["photo_album", "video_album", "mixed_album"] and len(files) > 1:
                # Media group (до 10 елементів в Telegram)
                small_files = [fp for fp in files if fp.exists() and fp.stat().st_size < max_size]
                
                if small_files and len(small_files) <= 10:
                    media_group = []
                    
                    for fp in small_files[:10]:  # Max 10 items
                        ext = fp.suffix.lower()
                        
                        with fp.open("rb") as f:
                            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                                media_group.append(InputMediaPhoto(media=f.read()))
                            else:
                                media_group.append(InputMediaVideo(media=f.read()))
                    
                    if media_group:
                        await context.bot.send_media_group(chat_id, media=media_group)
                        await status_msg.delete()
                        
                        # Cleanup
                        for fp in files:
                            ACTIVE_DOWNLOADS.discard(str(fp))
                            try:
                                if fp.exists():
                                    fp.unlink()
                                    log.info(f"🗑️ Removed: {fp.name}")
                            except Exception as e:
                                log.warning(f"Failed to remove {fp.name}: {e}")
                        return
            
            # Відправляємо файли окремо
            for fp in files:
                if not fp.exists():
                    continue
                
                file_size = fp.stat().st_size
                
                # Великі файли на gofile
                if file_size > max_size:
                    link = await upload_to_gofile(fp)
                    await context.bot.send_message(
                        chat_id,
                        f"✅ Файл завеликий ({file_size / 1024 / 1024:.1f} MB)\n\n"
                        f"🔗 Завантажено на gofile.io:\n{link}"
                    )
                else:
                    with fp.open("rb") as f:
                        ext = fp.suffix.lower()
                        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                            await context.bot.send_photo(chat_id, photo=InputFile(f, filename=fp.name))
                        else:
                            await context.bot.send_video(
                                chat_id,
                                video=InputFile(f, filename=fp.name),
                                supports_streaming=True
                            )
            
            # Видаляємо статус
            try:
                await status_msg.delete()
            except:
                pass
        
        finally:
            # Очищення
            for fp in files:
                ACTIVE_DOWNLOADS.discard(str(fp))
                try:
                    if fp.exists():
                        fp.unlink()
                        log.info(f"🗑️ Removed: {fp.name}")
                except Exception as e:
                    log.warning(f"Failed to remove {fp.name}: {e}")
    
    except Exception as e:
        log.error(f"Instagram download error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Помилка: {str(e)[:100]}")


# ---------------------------------------------------------
# DOWNLOAD FACEBOOK
# ---------------------------------------------------------
async def download_facebook(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download from Facebook"""
    from downloaders import FacebookDownloader
    
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(chat_id, "⏳ Підготовка...")
    
    try:
        downloader = FacebookDownloader()
        
        # Progress callback
        async def progress(text: str):
            try:
                await status_msg.edit_text(text)
            except:
                pass
        
        # Одразу завантажуємо відео (якість 720p за замовчуванням)
        files, media_type = await downloader.download(
            url,
            download_type=VIDEO,
            quality="720",
            progress_callback=progress
        )
        
        if not files:
            await status_msg.edit_text("❌ Не вдалося завантажити")
            return
        
        # Надсилаємо файл
        for fp in files:
            ACTIVE_DOWNLOADS.add(str(fp))
            
            file_size = fp.stat().st_size
            
            # Якщо файл більше 50MB - завантажуємо на gofile.io
            if file_size > 50 * 1024 * 1024:
                await safe_edit_message(status_msg, f"📤 Файл завеликий ({file_size / 1024 / 1024:.1f} MB), завантажую на gofile.io...")
                link = await upload_to_gofile(fp)
                await context.bot.send_message(
                    chat_id,
                    f"✅ Файл завеликий ({file_size / 1024 / 1024:.1f} MB)\n\n"
                    f"🔗 Завантажено на gofile.io:\n{link}"
                )
            else:
                await safe_edit_message(status_msg, f"📤 Надсилаю відео ({file_size / 1024 / 1024:.1f} MB)...")
                with fp.open("rb") as f:
                    await context.bot.send_video(
                        chat_id,
                        video=InputFile(f, filename=fp.name),
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120
                    )
            
            # Видаляємо статус
            try:
                await status_msg.delete()
            except:
                pass
            
            # Очищення
            ACTIVE_DOWNLOADS.discard(str(fp))
            try:
                if fp.exists():
                    fp.unlink()
                    log.info(f"🗑️ Removed: {fp.name}")
            except Exception as e:
                log.warning(f"Failed to remove {fp.name}: {e}")
    
    except Exception as e:
        log.error(f"Facebook download error: {e}", exc_info=True)
        error_msg = str(e)
        
        # Спеціальне повідомлення для Facebook Reels
        if 'Cannot parse data' in error_msg or '/reel/' in url:
            await status_msg.edit_text(
                "⚠️ Facebook Reels зараз не підтримуються через зміни в API Facebook.\n\n"
                "✅ Працює:\n"
                "• Звичайні відеопости\n"
                "• Facebook Watch\n"
                "• fb.watch посилання\n\n"
                "🔄 Спробуйте інше відео або зачекайте оновлення yt-dlp."
            )
        else:
            await status_msg.edit_text(f"❌ Помилка: {error_msg[:150]}")


# ---------------------------------------------------------
# DOWNLOAD TIKTOK
# ---------------------------------------------------------
async def download_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download from TikTok"""
    from downloaders import TikTokDownloader
    
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(chat_id, "⏳ Підготовка...")
    
    try:
        downloader = TikTokDownloader()
        
        # Progress callback
        async def progress(text: str):
            try:
                await status_msg.edit_text(text)
            except:
                pass
        
        # Завантажуємо відео
        files, media_type = await downloader.download(
            url,
            download_type=VIDEO,
            progress_callback=progress
        )
        
        if not files:
            await status_msg.edit_text("❌ Не вдалося завантажити")
            return
        
        # Надсилаємо файл
        for fp in files:
            ACTIVE_DOWNLOADS.add(str(fp))
            
            file_size = fp.stat().st_size
            
            # Якщо файл більше 50MB - завантажуємо на gofile.io
            if file_size > 50 * 1024 * 1024:
                await safe_edit_message(status_msg, f"📤 Файл завеликий ({file_size / 1024 / 1024:.1f} MB), завантажую на gofile.io...")
                link = await upload_to_gofile(fp)
                await context.bot.send_message(
                    chat_id,
                    f"✅ Файл завеликий ({file_size / 1024 / 1024:.1f} MB)\n\n"
                    f"🔗 Завантажено на gofile.io:\n{link}"
                )
            else:
                await safe_edit_message(status_msg, f"📤 Надсилаю відео ({file_size / 1024 / 1024:.1f} MB)...")
                with fp.open("rb") as f:
                    await context.bot.send_video(
                        chat_id,
                        video=InputFile(f, filename=fp.name),
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120
                    )
            
            # Видаляємо статус
            try:
                await status_msg.delete()
            except:
                pass
            
            # Очищення
            ACTIVE_DOWNLOADS.discard(str(fp))
            try:
                if fp.exists():
                    fp.unlink()
                    log.info(f"🗑️ Removed: {fp.name}")
            except Exception as e:
                log.warning(f"Failed to remove {fp.name}: {e}")
    
    except Exception as e:
        log.error(f"TikTok download error: {e}", exc_info=True)
        await safe_edit_message(status_msg, f"❌ Помилка: {str(e)[:150]}")


# ---------------------------------------------------------
# DOWNLOAD YOUTUBE
# ---------------------------------------------------------
async def download_youtube(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    mode: str,
    video_quality: str = None
):
    """Download from YouTube"""
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(chat_id, "⏳ Починаємо...")
    
    cleanup_old_files(DOWNLOAD_DIR, max_age_minutes=30, active_downloads=ACTIVE_DOWNLOADS)
    
    async def progress_callback(status, percent, done, total):
        """Progress updates"""
        if status == "downloading":
            if percent > 0:
                bar = make_bar(percent)
                await status_msg.edit_text(f"⬇️ Завантаження...\n{bar} {percent:.1f}%")
            else:
                mb = done / 1024 / 1024
                await status_msg.edit_text(f"⬇️ Завантаження...\n{mb:.1f} MB")
        elif status == "converting":
            await status_msg.edit_text("🔄 Конвертуємо...")
    
    try:
        downloader = YouTubeDownloader()
        fp, media_type = await downloader.download(
            url,
            DOWNLOAD_DIR,
            mode=mode,
            video_quality=video_quality,
            progress_callback=progress_callback
        )
        
        ACTIVE_DOWNLOADS.add(str(fp))
        
        try:
            if not fp.exists():
                await status_msg.edit_text("❌ Файл не знайдено")
                return
            
            file_size = fp.stat().st_size
            max_size = 50 * 1024 * 1024
            
            if file_size > max_size:
                await status_msg.edit_text(f"📤 Файл завеликий, завантажую на GoFile.io...")
                link = await upload_to_gofile(fp)
                file_type = "Відео" if mode == VIDEO else "Аудіо"
                await status_msg.edit_text(
                    f"✅ {file_type} завелике ({file_size / 1024 / 1024:.1f} MB)\n\n"
                    f"🔗 Завантажено на gofile.io:\n{link}"
                )
                return
            
            await status_msg.edit_text("📤 Завантаження в Telegram...")
            
            with fp.open("rb") as f:
                if mode == AUDIO:
                    await context.bot.send_audio(chat_id, audio=InputFile(f, filename=fp.name))
                else:
                    await context.bot.send_video(
                        chat_id,
                        video=InputFile(f, filename=fp.name),
                        supports_streaming=True
                    )
            
            try:
                await status_msg.delete()
            except:
                pass
        
        finally:
            ACTIVE_DOWNLOADS.discard(str(fp))
            try:
                if fp.exists():
                    fp.unlink()
                    log.info(f"🗑️ Removed: {fp.name}")
            except Exception as e:
                log.warning(f"Failed to remove {fp.name}: {e}")
    
    except Exception as e:
        log.error(f"YouTube download error: {e}")
        await status_msg.edit_text(f"❌ Помилка: {e}")


# ---------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    mode = query.data
    
    url = context.user_data.get("url") or USER_LINK.get(chat_id)
    
    if not url:
        await query.edit_message_text("❌ Посилання не знайдено. Надішліть URL ще раз.")
        return
    
    if mode == VIDEO:
        # Вибір якості
        keyboard = [
            [InlineKeyboardButton("360p", callback_data="video_360")],
            [InlineKeyboardButton("480p", callback_data="video_480")],
            [InlineKeyboardButton("720p", callback_data="video_720")],
        ]
        await query.edit_message_text(
            "Оберіть якість:\n(нижча якість = менший розмір)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif mode.startswith("video_"):
        try:
            await query.message.delete()
        except:
            pass
        quality = mode.split("_")[1]
        await download_youtube(update, context, url, VIDEO, video_quality=quality)
    
    elif mode == AUDIO:
        try:
            await query.message.delete()
        except:
            pass
        await download_youtube(update, context, url, AUDIO)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    
    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    cleanup_all_except_active(DOWNLOAD_DIR, active_downloads=ACTIVE_DOWNLOADS)
    
    log.info("🤖 Bot started")
    log.info("📦 Downloaders: YouTube, Instagram, Facebook, TikTok")
    
    try:
        app.run_polling(close_loop=False)
    finally:
        cleanup_all_except_active(DOWNLOAD_DIR, active_downloads=ACTIVE_DOWNLOADS)


if __name__ == "__main__":
    main()
