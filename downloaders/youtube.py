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
            
            # Перевірка cookies файлу
            cookies_path = "/tmp/ytdl-cookies.txt"
            if os.path.exists(cookies_path):
                cookie_size = os.path.getsize(cookies_path)
                with open(cookies_path, 'r') as f:
                    cookie_lines = [line for line in f if line.strip() and not line.startswith('#')]
                    cookie_count = len(cookie_lines)
                    
                    # Перевіряємо критичні YouTube cookies
                    cookie_names = [line.split('\t')[5] if len(line.split('\t')) > 5 else '' for line in cookie_lines]
                    critical_cookies = ['__Secure-3PSID', '__Secure-1PSID', 'SAPISID', 'SSID']
                    found_critical = [c for c in critical_cookies if c in cookie_names]
                    missing_critical = [c for c in critical_cookies if c not in cookie_names]
                    
                log.info(f"🍪 YouTube cookies loaded: {cookie_count} cookies ({cookie_size} bytes)")
                if found_critical:
                    log.info(f"✅ Critical cookies found: {', '.join(found_critical)}")
                if missing_critical:
                    log.warning(f"⚠️  Missing critical cookies: {', '.join(missing_critical)}")
                    log.warning("   YouTube may block requests without these cookies")
            else:
                log.warning("⚠️  YouTube cookies NOT FOUND at /tmp/ytdl-cookies.txt")
                log.warning("   Bot may encounter 'Sign in to confirm you're not a bot' errors")
            
            opts = {
                "cookiefile": cookies_path,
                "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
                "quiet": False,
                "verbose": False,
                "nocheckcertificate": True,
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                "noplaylist": True,
            }
            
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
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                original_path = ydl.prepare_filename(info)
                
                if mode == "audio":
                    return str(Path(original_path).with_suffix(".mp3")), mode
                return original_path, mode
        
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
