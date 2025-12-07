"""TikTok video downloader using yt-dlp"""

import re
import logging
from pathlib import Path
from typing import List, Tuple
import yt_dlp

from .base import BaseDownloader

log = logging.getLogger("ytbot")

class TikTokDownloader(BaseDownloader):
    """Download videos from TikTok"""
    
    PATTERNS = [
        r'(?:https?://)?(?:www\.|vm\.|vt\.)?tiktok\.com/',
    ]
    
    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if URL is from TikTok"""
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in cls.PATTERNS)
    
    async def download(
        self,
        url: str,
        download_type: str = "video",
        quality: str = "best",
        progress_callback=None
    ) -> Tuple[List[Path], str]:
        """
        Download TikTok video
        
        Args:
            url: TikTok video URL (including vm.tiktok.com short links)
            download_type: Only "video" supported
            quality: Video quality (ignored, TikTok provides single quality)
            progress_callback: Async callback for progress updates
            
        Returns:
            Tuple of (list of file paths, media type)
        """
        from concurrent.futures import ThreadPoolExecutor
        import asyncio
        
        POOL = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        
        log.info(f"📥 TikTok download started: {url}")
        
        def sync_download():
            """Synchronous download in thread pool"""
            download_dir = Path("downloads")
            download_dir.mkdir(exist_ok=True)
            
            # yt-dlp options for TikTok
            ydl_opts = {
                'format': 'best',  # TikTok usually has single quality
                'outtmpl': str(download_dir / '%(title).50s-%(id)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'extract_flat': False,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
                # TikTok specific options
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://www.tiktok.com/',
                },
            }
            
            # Add progress hook
            if progress_callback:
                def progress_hook(d):
                    if d['status'] == 'downloading':
                        try:
                            percent = d.get('_percent_str', '0%').strip()
                            speed = d.get('_speed_str', 'N/A').strip()
                            eta = d.get('_eta_str', 'N/A').strip()
                            
                            message = f"⬇️ Downloading: {percent}"
                            if speed != 'N/A':
                                message += f" | {speed}"
                            if eta != 'N/A':
                                message += f" | ETA: {eta}"
                            
                            # Call async callback from thread
                            from asyncio import run_coroutine_threadsafe
                            run_coroutine_threadsafe(
                                progress_callback(message),
                                loop
                            )
                        except Exception as e:
                            log.error(f"Progress hook error: {e}")
                
                ydl_opts['progress_hooks'] = [progress_hook]
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    log.info(f"🎵 Downloading TikTok video...")
                    info = ydl.extract_info(url, download=True)
                    
                    if not info:
                        raise Exception("Failed to extract video info")
                    
                    # Find downloaded file
                    title = info.get('title', 'video')
                    video_id = info.get('id', '')
                    
                    # Try multiple patterns to find the file
                    patterns = [
                        f"*{video_id}*.mp4",
                        f"*{video_id}*.mkv",
                        f"{self.clean_filename(title)[:30]}*.mp4",
                    ]
                    
                    files = []
                    for pattern in patterns:
                        found = list(download_dir.glob(pattern))
                        if found:
                            files = [found[0]]
                            break
                    
                    if not files:
                        # Last resort: get newest video file
                        video_files = list(download_dir.glob("*.mp4")) + list(download_dir.glob("*.mkv"))
                        if video_files:
                            files = [max(video_files, key=lambda p: p.stat().st_mtime)]
                    
                    if not files:
                        raise Exception("Downloaded file not found")
                    
                    log.info(f"✅ Downloaded: {files[0].name}")
                    return files, "video"
                    
            except Exception as e:
                log.error(f"TikTok download error: {e}")
                raise
        
        # Run in thread pool
        return await loop.run_in_executor(POOL, sync_download)
