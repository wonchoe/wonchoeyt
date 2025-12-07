"""YouTube downloader using yt-dlp"""

import os
import re
import time
import asyncio
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
            except Exception as e:
                log.warning(f"⚠️  Could not locate Node.js: {e}")
            
            # Стратегія: спочатку без cookies (для публічних відео), потім з cookies якщо потрібно
            cookies_path = "/tmp/ytdl-cookies.txt"
            use_cookies = os.path.exists(cookies_path)
            
            if use_cookies:
                cookie_size = os.path.getsize(cookies_path)
                log.info(f"🍪 YouTube cookies available: {cookie_size} bytes")
            else:
                log.info("🔓 No cookies - will try without authentication (public videos only)")
            
            # Базова конфігурація без cookies
            opts = {
                "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
                "quiet": False,
                "verbose": False,
                "nocheckcertificate": True,
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                "noplaylist": True,
                # Використовуємо android client для обходу Sign in challenge
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "web"],
                        "skip": ["hls", "dash"],
                    }
                },
            }
            
            # Додаємо cookies тільки якщо вони є
            if use_cookies:
                opts["cookiefile"] = cookies_path
            
            # Якщо Node.js знайдено, додаємо в конфігурацію для JS challenge solving
            if node_path:
                opts["exec_cmd"] = {"node": node_path}
                log.info(f"✅ Node.js configured for yt-dlp at: {node_path}")


            
            if mode == "audio":
                # Максимально м'який fallback для audio
                opts["format"] = "bestaudio/bestaudio*/best/best*"
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
                        f"bestvideo*[height<={video_quality}]+bestaudio*/"
                        f"bestvideo[height<={video_quality}]+bestaudio/"
                        f"best*[height<={video_quality}]/"
                        f"best[height<={video_quality}]/"
                        "best*/best"
                    )
                else:
                    opts["format"] = (
                        "bestvideo*+bestaudio*/"
                        "bestvideo+bestaudio/"
                        "best*/best"
                    )
                opts["merge_output_format"] = "mp4"
            
            # Спроба завантаження з retry механізмом
            last_error = None
            attempts = []
            
            # Спроба 1: з cookies (якщо є)
            if use_cookies:
                attempts.append(("with cookies", opts.copy()))
            
            # Спроба 2: без cookies (для публічних відео)
            opts_no_cookies = opts.copy()
            if "cookiefile" in opts_no_cookies:
                del opts_no_cookies["cookiefile"]
            attempts.append(("without cookies", opts_no_cookies))
            
            for attempt_name, attempt_opts in attempts:
                try:
                    log.info(f"🔄 Attempting download {attempt_name}...")
                    
                    with yt_dlp.YoutubeDL(attempt_opts) as ydl:
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
                            
                            log.info(f"✅ Downloaded successfully {attempt_name}")
                            return mp3_path, mode
                        else:
                            # Для відео
                            original_path = ydl.prepare_filename(info)
                            log.info(f"✅ Downloaded successfully {attempt_name}")
                            return original_path, mode
                
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    log.warning(f"⚠️ Attempt {attempt_name} failed: {error_msg}")
                    
                    # Якщо це остання спроба - кидаємо помилку
                    if attempt_name == attempts[-1][0]:
                        log.error(f"❌ All download attempts failed")
                        raise last_error
                    
                    # Інакше пробуємо наступний спосіб
                    log.info(f"🔄 Trying next method...")
                    continue
            
            # Якщо дійшли сюди - щось пішло не так
            raise Exception("All download attempts exhausted")
        
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
