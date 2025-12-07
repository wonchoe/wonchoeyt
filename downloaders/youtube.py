"""YouTube downloader using yt-dlp"""

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
            opts = {
                "cookiefile": "/tmp/cookies.txt",
                "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
                "quiet": True,
                "nocheckcertificate": True,
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                "noplaylist": True,
            }
            
            if mode == "audio":
                opts["format"] = "bestaudio/best"
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
                opts["writethumbnail"] = False
                opts["writesubtitles"] = False
            else:
                if video_quality:
                    opts["format"] = f"bestvideo[height<={video_quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={video_quality}]"
                else:
                    opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
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
