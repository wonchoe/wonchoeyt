"""Instagram downloader using yt-dlp and instaloader"""

import re
import time
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor

import yt_dlp

try:
    import instaloader
    INSTALOADER_AVAILABLE = True
except ImportError:
    INSTALOADER_AVAILABLE = False
    log.warning("⚠️ instaloader not available, photo posts may fail")

from .base import BaseDownloader, log


POOL = ThreadPoolExecutor(max_workers=4)


class InstagramDownloader(BaseDownloader):
    """Download from Instagram (posts, reels, stories, IGTV)"""
    
    PATTERNS = [
        r'instagram\.com/p/',      # posts
        r'instagram\.com/reel/',   # reels
        r'instagram\.com/tv/',     # IGTV
        r'instagram\.com/stories/', # stories
        r'instagr\.am/',
    ]
    
    @staticmethod
    def can_handle(url: str) -> bool:
        """Check if URL is Instagram"""
        return any(re.search(pattern, url, re.I) for pattern in InstagramDownloader.PATTERNS)
    
    async def download(
        self,
        url: str,
        download_dir: Path,
        progress_callback=None
    ) -> Tuple[List[Path], str]:
        """
        Download from Instagram
        
        Args:
            url: Instagram URL
            download_dir: Directory to save files
            progress_callback: Callback for progress updates
        
        Returns:
            Tuple[List[Path], str]: (filepaths, media_type)
            media_type: 'photo', 'video', 'carousel'
        """
        
        # Clean URL - remove query parameters that confuse downloaders
        url = re.sub(r'\?.*$', '', url)
        log.info(f"🔗 Clean URL: {url}")
        
        last_update = [0]
        
        def progress_hook(d):
            # Progress hook runs in thread, skip for now
            pass
        
        def sync_download():
            """Download using yt-dlp (works for most Instagram content)"""
            
            # Try yt-dlp first
            try:
                files, media_type = download_with_ytdlp()
                
                # If yt-dlp returned 0 files, try instaloader
                if not files and INSTALOADER_AVAILABLE:
                    log.info("📸 yt-dlp returned 0 files, trying instaloader...")
                    return download_with_instaloader()
                
                return files, media_type
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # If "no video in this post" - try instaloader for photos
                if ("no video" in error_msg or "no formats" in error_msg) and INSTALOADER_AVAILABLE:
                    log.info("📸 Trying instaloader for photo post...")
                    return download_with_instaloader()
                else:
                    raise
        
        def download_with_ytdlp():
            """Download using yt-dlp"""
            log.info("🔄 Trying yt-dlp...")
            opts = {
                "cookiefile": "/tmp/cookies.txt",
                "outtmpl": str(download_dir / "%(title)s_%(autonumber)s.%(ext)s"),
                "quiet": False,  # Show more info
                "no_warnings": False,
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                # Force download all items in post (carousel)
                "noplaylist": False,
                # Get best quality for photos
                "format": "best",
            }
            
            files = []
            media_type = "video"
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if it's a carousel (multiple items)
                if "entries" in info and info["entries"]:
                    # Carousel/album - multiple photos/videos
                    photos = []
                    videos = []
                    
                    for entry in info["entries"]:
                        if not entry:
                            continue
                        filepath = ydl.prepare_filename(entry)
                        fp = Path(filepath)
                        
                        if fp.exists():
                            files.append(fp)
                            
                            # Classify by extension and format info
                            ext = fp.suffix.lower()
                            vcodec = entry.get("vcodec", "none")
                            
                            # Photo if no video codec or static image extensions
                            if ext in ['.jpg', '.jpeg', '.png', '.webp'] or vcodec == "none":
                                photos.append(fp)
                            else:
                                videos.append(fp)
                    
                    # Determine media type
                    if photos and not videos:
                        media_type = "photo_album"
                    elif videos and not photos:
                        media_type = "video_album"
                    else:
                        media_type = "mixed_album"
                    
                    log.info(f"📦 Carousel: {len(photos)} photos, {len(videos)} videos")
                
                else:
                    # Single item
                    filepath = ydl.prepare_filename(info)
                    fp = Path(filepath)
                    
                    if fp.exists():
                        files.append(fp)
                        
                        # Detect if photo or video
                        ext = fp.suffix.lower()
                        vcodec = info.get("vcodec", "none")
                        
                        if ext in ['.jpg', '.jpeg', '.png', '.webp'] or vcodec == "none":
                            media_type = "photo"
                            log.info(f"📸 Single photo")
                        else:
                            media_type = "video"
                            log.info(f"🎬 Single video")
            
            return files, media_type
        
        def download_with_instaloader():
            """Download photos using instaloader"""
            if not INSTALOADER_AVAILABLE:
                raise Exception("instaloader not installed")
            
            # Extract shortcode from URL
            match = re.search(r'instagram\.com/(?:p|reel|tv)/([^/]+)', url)
            if not match:
                raise Exception("Cannot extract Instagram shortcode")
            
            shortcode = match.group(1)
            
            # Setup instaloader
            L = instaloader.Instaloader(
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                dirname_pattern=str(download_dir),
                filename_pattern="{shortcode}_{mediacount}"
            )
            
            try:
                # Download post
                post = instaloader.Post.from_shortcode(L.context, shortcode)
                
                files = []
                media_type = "photo"
                
                # Download all items in post
                if post.typename == 'GraphSidecar':  # Carousel
                    media_type = "photo_album"
                    count = post.mediacount
                    log.info(f"📦 Downloading carousel with {count} items...")
                    
                    L.download_post(post, target=str(download_dir))
                    
                    # Find downloaded files - instaloader uses pattern: shortcode_count_index.ext
                    for i in range(1, count + 1):
                        pattern = f"{shortcode}_{count}_{i}.*"
                        found = list(download_dir.glob(pattern))
                        for fp in found:
                            if fp.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                                files.append(fp)
                                break
                    
                    log.info(f"📦 Photo album: {len(files)} photos downloaded")
                
                else:  # Single photo
                    L.download_post(post, target=str(download_dir))
                    
                    # Find downloaded file - instaloader uses pattern: shortcode_1_1.ext or shortcode.ext
                    patterns = [f"{shortcode}_1_1.*", f"{shortcode}.*"]
                    for pattern in patterns:
                        found = list(download_dir.glob(pattern))
                        for fp in found:
                            if fp.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp'] and '_' not in fp.stem[len(shortcode):]:
                                files.append(fp)
                                break
                        if files:
                            break
                    
                    log.info(f"📸 Single photo downloaded")
                
                if not files:
                    raise Exception("No files downloaded")
                
                return files, media_type
            
            except Exception as e:
                log.error(f"Instaloader error: {e}")
                raise
        
        loop = asyncio.get_running_loop()
        files, media_type = await loop.run_in_executor(POOL, sync_download)
        
        # Clean filenames
        cleaned_files = []
        for fp in files:
            if fp.exists():
                clean_name = self.clean_filename(fp.name)
                if clean_name != fp.name:
                    new_fp = fp.parent / clean_name
                    fp.rename(new_fp)
                    fp = new_fp
                    log.info(f"📝 Renamed to: {clean_name}")
                cleaned_files.append(fp)
        
        return cleaned_files, media_type
