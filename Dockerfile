FROM python:3.11-slim

WORKDIR /app

# ✅ Встановити Node.js (для yt-dlp JS runtime)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ Встановити yt-dlp через pip (найновіша версія)
RUN pip install --no-cache-dir -U yt-dlp

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ✅ Перевірка чи Node.js встановлено
RUN node --version && npm --version

CMD ["python", "app.py"]

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ...existing code...

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
