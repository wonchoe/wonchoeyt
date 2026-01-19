"""YouTube downloader using yt-dlp"""

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import yt_dlp

from .base import BaseDownloader, log


POOL = ThreadPoolExecutor(max_workers=4)


class YouTubeDownloader(BaseDownloader):
    """Download from YouTube, YouTube Music, etc."""
    
    PATTERNS = [
        r'(?:youtube\.com|youtu\.be)',
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'youtube\.com/shorts/',
    ]
    
    @staticmethod
    def can_handle(url: str) -> bool:
        """Check if URL is YouTube"""
        return any(re.search(pattern, url, re.I) for pattern in YouTubeDownloader.PATTERNS)
    
    async def download(
        self,
        url: str,
        download_dir: Path,
        mode: str = "audio",  # audio or video
        video_quality: Optional[str] = None,
        progress_callback=None
    ) -> Tuple[Path, str]:
        """
        Download from YouTube
        
        Args:
            url: YouTube URL
            download_dir: Directory to save file
            mode: 'audio' or 'video'
            video_quality: '360', '480', '720', '1080', etc.
            progress_callback: Callback for progress updates
        
        Returns:
            Tuple[Path, str]: (filepath, media_type)
        """
        
        last_update = [0]
        main_loop = asyncio.get_running_loop()
        
        def progress_hook(d):
            if not progress_callback:
                return
                
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                
                if total > 0:
                    percent = done / total * 100
                    if time.time() - last_update[0] > 0.5:
                        last_update[0] = time.time()
                        asyncio.run_coroutine_threadsafe(
                            progress_callback("downloading", percent, done, total),
                            main_loop
                        )
                else:
                    if time.time() - last_update[0] > 0.5:
                        last_update[0] = time.time()
                        asyncio.run_coroutine_threadsafe(
                            progress_callback("downloading", 0, done, 0),
                            main_loop
                        )
            
            elif d["status"] == "finished":
                asyncio.run_coroutine_threadsafe(
                    progress_callback("converting", 100, 0, 0),
                    main_loop
                )
        
        def sync_download():
            # Переконуємося що Node.js доступний для yt-dlp subprocess
            import subprocess
            node_path = None
            try:
                node_result = subprocess.run(['which', 'node'], capture_output=True, text=True, timeout=2)
                if node_result.returncode == 0:
                    node_path = node_result.stdout.strip()
                    log.info(f"🟢 Node.js found at: {node_path}")
                    
                    # КРИТИЧНО: Додаємо Node.js директорію в PATH
                    node_dir = os.path.dirname(node_path)
                    if node_dir not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = f"{node_dir}:{os.environ.get('PATH', '')}"
                        log.info(f"➕ Added Node.js to PATH: {node_dir}")
            except Exception as e:
                log.warning(f"⚠️ Node.js check failed: {e}")
            
            # Стратегія: cookies > різні player clients (OAuth deprecated!)
            cookies_path = "/var/www/ytdl-cookies.txt"
            use_cookies = os.path.exists(cookies_path)
            
            if use_cookies:
                cookie_size = os.path.getsize(cookies_path)
                log.info(f"🍪 YouTube cookies available: {cookie_size} bytes")
                
                # Перевіряємо критичні cookies
                try:
                    with open(cookies_path, 'r') as f:
                        cookie_content = f.read()
                        critical = ['__Secure-3PSID', '__Secure-1PSID', 'SAPISID', 'SSID']
                        found_critical = [c for c in critical if c in cookie_content]
                        log.info(f"🔑 Critical cookies found: {', '.join(found_critical)}")
                except Exception as e:
                    log.warning(f"⚠️ Could not verify cookies: {e}")
            else:
                log.warning("⚠️ No cookies - YouTube downloads may fail!")

            
            # Базова конфігурація (як в CLI, мінімум обмежень)
            opts = {
                "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
                "quiet": False,
                "nocheckcertificate": True,
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                "noplaylist": True,
            }

            # Налаштування JS runtime для YouTube challenges (EJS)
            if node_path:
                opts["js_runtimes"] = {"node": {"path": node_path}}
            else:
                log.warning("⚠️ No JS runtime configured for yt-dlp")
            
            # Node.js вже в PATH, yt-dlp автоматично знайде його
            if node_path:
                log.info(f"✅ Node.js configured for yt-dlp (in PATH)")



            
            if mode == "audio":
                # Максимально м'який fallback для audio
                opts["format"] = "bestaudio[protocol=https]/bestaudio*/best[protocol=https]/best"
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
                opts["writethumbnail"] = False
                opts["writesubtitles"] = False
            else:
                # Максимально агресивний fallback для відео
                if video_quality:
                    opts["format"] = (
                        f"bestvideo*[height<={video_quality}][protocol=https]+bestaudio[protocol=https]/"
                        f"bestvideo[height<={video_quality}][protocol=https]+bestaudio[protocol=https]/"
                        f"best*[height<={video_quality}][protocol=https]/"
                        f"best[height<={video_quality}][protocol=https]/"
                        "best*[protocol=https]/best[protocol=https]"
                    )
                else:
                    opts["format"] = (
                        "bestvideo*[protocol=https]+bestaudio[protocol=https]/"
                        "bestvideo[protocol=https]+bestaudio[protocol=https]/"
                        "best*[protocol=https]/best[protocol=https]"
                    )
                opts["merge_output_format"] = "mp4"
            
            # Спроба завантаження з retry механізмом
            last_error = None
            
            # Різні стратегії обходу YouTube блокування
            strategies = []
            
            # ПРІОРИТЕТ 1: Просто cookies БЕЗ extractor_args (як в CLI!)
            if use_cookies:
                opts_simple = opts.copy()
                opts_simple["cookiefile"] = cookies_path
                # НЕ додаємо extractor_args - нехай yt-dlp сам вибере клієнт
                strategies.append(("with cookies (default)", opts_simple))
            else:
                log.warning("⚠️ Proceeding without cookies; some formats may be unavailable")
                strategies.append(("without cookies", opts.copy()))
            
            for strategy_name, strategy_opts in strategies:
                try:
                    log.info(f"🔄 Attempting download {strategy_name}...")
                    
                    with yt_dlp.YoutubeDL(strategy_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        
                        if not info:
                            raise Exception("Failed to extract video info")
                        
                        # Для audio режиму файл вже конвертований в mp3
                        if mode == "audio":
                            # prepare_filename поверне .mp4, але ffmpeg вже конвертував в .mp3
                            base_path = ydl.prepare_filename(info)
                            mp3_path = str(Path(base_path).with_suffix(".mp3"))
                            
                            # Перевіряємо чи файл існує
                            if not Path(mp3_path).exists():
                                # Якщо mp3 не знайдено, шукаємо будь-який аудіо файл
                                audio_files = list(download_dir.glob("*.mp3"))
                                if audio_files:
                                    mp3_path = str(audio_files[-1])  # Найновіший файл
                                else:
                                    raise Exception(f"Audio file not found: {mp3_path}")
                            
                            log.info(f"✅ Downloaded successfully {strategy_name}")
                            return mp3_path, mode
                        else:
                            # Для відео
                            original_path = ydl.prepare_filename(info)
                            log.info(f"✅ Downloaded successfully {strategy_name}")
                            return original_path, mode
                
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    log.warning(f"⚠️ Attempt {strategy_name} failed: {error_msg}")
                    
                    # Якщо це остання спроба - кидаємо помилку
                    if strategy_name == strategies[-1][0]:
                        log.error(f"❌ All download strategies failed")
                        raise last_error
                    
                    # Інакше пробуємо наступний спосіб
                    log.info(f"🔄 Trying next strategy...")
                    continue
            
            # Якщо дійшли сюди - щось пішло не так
            raise Exception("All download strategies exhausted")
        
        loop = asyncio.get_running_loop()
        filepath, media_type = await loop.run_in_executor(POOL, sync_download)
        
        fp = Path(filepath)
        
        # Clean filename
        clean_name = self.clean_filename(fp.name)
        if clean_name != fp.name:
            new_fp = fp.parent / clean_name
            fp.rename(new_fp)
            fp = new_fp
            log.info(f"📝 Renamed to: {clean_name}")
        
        return fp, media_type
