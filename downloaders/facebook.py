"""Facebook/Meta video downloader using yt-dlp with cookies"""

import re
import os
import logging
from pathlib import Path
from typing import List, Tuple
import yt_dlp

from .base import BaseDownloader

log = logging.getLogger("ytbot")

COOKIES_FILE = "/tmp/cookies.txt"

class FacebookDownloader(BaseDownloader):
    """Download videos from Facebook, Instagram stories, and other Meta platforms"""
    
    PATTERNS = [
        r'(?:https?://)?(?:www\.|m\.|web\.)?facebook\.com/',
        r'(?:https?://)?(?:www\.)?fb\.watch/',
        r'(?:https?://)?(?:www\.)?fb\.com/',
    ]
    
    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if URL is from Facebook/Meta"""
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in cls.PATTERNS)
    
    async def download(
        self,
        url: str,
        download_type: str = "video",
        quality: str = "720",
        progress_callback=None
    ) -> Tuple[List[Path], str]:
        """
        Download Facebook video
        
        Args:
            url: Facebook video URL (posts, reels, stories, watch)
            download_type: Only "video" supported
            quality: Video quality (360, 480, 720)
            progress_callback: Async callback for progress updates
            
        Returns:
            Tuple of (list of file paths, media type)
        """
        from concurrent.futures import ThreadPoolExecutor
        import asyncio
        
        POOL = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        
        # Clean URL - remove tracking parameters
        url = re.sub(r'[?&](mibextid|sfnsn|story_fbid|substory_index)=[^&]*', '', url)
        url = re.sub(r'\?$', '', url)
        
        # Expand short share links
        if '/share/r/' in url or '/share/v/' in url:
            log.info(f"🔄 Expanding short link...")
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                response = urllib.request.urlopen(req, timeout=10)
                url = response.url
                log.info(f"📍 Expanded to: {url}")
            except Exception as e:
                log.warning(f"Could not expand link: {e}, trying original URL")
        
        log.info(f"📥 Facebook download started: {url}")
        
        def sync_download():
            """Synchronous download in thread pool"""
            download_dir = Path("downloads")
            download_dir.mkdir(exist_ok=True)
            
            # Check if cookies file exists
            cookies_available = os.path.exists(COOKIES_FILE)
            if not cookies_available:
                log.warning("⚠️ Cookies file not found, Facebook downloads may fail")
            
            # yt-dlp options for Facebook
            ydl_opts = {
                'format': self._get_format_string(quality),
                'outtmpl': str(download_dir / '%(title).50s-%(id)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'extract_flat': False,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            }
            
            # Add cookies if available
            if cookies_available:
                ydl_opts['cookiefile'] = COOKIES_FILE
                log.info("🍪 Using cookies for authentication")
            
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
                    log.info(f"🎬 Downloading Facebook video (quality: {quality}p)...")
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
                log.error(f"Facebook download error: {e}")
                raise
        
        # Run in thread pool
        return await loop.run_in_executor(POOL, sync_download)
    
    def _get_format_string(self, quality: str) -> str:
        """
        Get yt-dlp format string for Facebook videos
        
        Facebook format priorities:
        - Try to get specific quality with video+audio
        - Fallback to best available format
        """
        quality_map = {
            "360": "best[height<=360]/bestvideo[height<=360]+bestaudio/best",
            "480": "best[height<=480]/bestvideo[height<=480]+bestaudio/best", 
            "720": "best[height<=720]/bestvideo[height<=720]+bestaudio/best",
        }
        
        return quality_map.get(quality, quality_map["720"])
