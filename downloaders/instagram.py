"""Instagram downloads with anonymous and authenticated fallbacks."""

import asyncio
import http.cookiejar
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Tuple
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import yt_dlp

from .base import BaseDownloader, log
from .instagram_browser import BrowserDownloadError, download_with_browser

try:
    import instaloader
except ImportError:
    instaloader = None


POOL = ThreadPoolExecutor(max_workers=4)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv"}
GALLERY_TIMEOUT = 120


class InstagramDownloadError(Exception):
    """A download failure whose message can be displayed in Telegram."""


class InstagramDownloader(BaseDownloader):
    @staticmethod
    def can_handle(url: str) -> bool:
        parts = urlsplit(url)
        return parts.hostname in {"instagram.com", "www.instagram.com", "instagr.am"} and bool(
            re.match(r"/(?:p|reels?|tv|stories)/", parts.path)
        )

    @staticmethod
    def _cookies():
        """Read only Instagram cookies; never rewrite the shared cookie file."""
        source = Path(os.getenv("INSTAGRAM_COOKIES_FILE", "/var/www/ytdl-cookies.txt"))
        jar = http.cookiejar.MozillaCookieJar()
        if not source.is_file():
            return jar
        try:
            saved = http.cookiejar.MozillaCookieJar(str(source))
            saved.load(ignore_discard=True, ignore_expires=True)
            for cookie in saved:
                domain = cookie.domain.lstrip(".")
                if domain != "instagram.com" and not domain.endswith(".instagram.com"):
                    continue
                if cookie.expires == 0:
                    cookie.expires = None
                    cookie.discard = True
                if not cookie.is_expired() and cookie.value:
                    jar.set_cookie(cookie)
        except (OSError, http.cookiejar.LoadError):
            # CookieJar parse errors can include an entire cookie value.
            log.warning("Cannot read Instagram cookies from %s; expected Netscape cookie format", source)
        return jar

    @staticmethod
    def _media_files(directory: Path) -> List[Path]:
        # Natural filename order preserves carousel positions (2 before 10).
        def key(path):
            return [int(part) if part.isdigit() else part.lower()
                    for part in re.split(r"(\d+)", str(path.relative_to(directory)))]

        return sorted((path for path in directory.rglob("*")
                       if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS | VIDEO_EXTENSIONS
                       and path.stat().st_size > 0), key=key)

    @staticmethod
    def _media_type(files: List[Path]) -> str:
        # Instagram can omit vcodec even for an MP4; use the actual file type.
        photos = sum(path.suffix.lower() in PHOTO_EXTENSIONS for path in files)
        if len(files) == 1:
            return "photo" if photos else "video"
        if photos == len(files):
            return "photo_album"
        return "mixed_album" if photos else "video_album"

    @staticmethod
    def _public_error(errors, authenticated: bool) -> InstagramDownloadError:
        details = " ".join(errors).lower()
        if any(term in details for term in (
            "isn't available to everyone", "certain audiences", "login", "log in",
            "sign in", "private", "401", "restricted video", "18 years",
        )):
            if authenticated:
                message = ("Instagram обмежив доступ до цього допису. Оновіть вхід Instagram "
                           "для бота й перевірте, чи цей акаунт має доступ до допису.")
            else:
                message = ("Для цього допису потрібен вхід в Instagram. "
                           "Адміністратору потрібно додати чинні cookies Instagram для бота.")
        elif any(term in details for term in ("429", "too many requests", "please wait", "rate limit")):
            message = "Instagram тимчасово обмежив запити. Спробуйте пізніше."
        elif any(term in details for term in ("not found", "404", "does not exist", "deleted")):
            message = "Допис Instagram не знайдено або видалено. Перевірте посилання."
        elif any(term in details for term in ("timed out", "timeout")):
            message = "Instagram не відповів вчасно. Спробуйте ще раз пізніше."
        else:
            message = "Не вдалося завантажити допис Instagram. Спробуйте пізніше."
        return InstagramDownloadError(message)

    def _download_ytdlp(self, url: str, directory: Path, cookies_file):
        opts = {
            "outtmpl": str(directory / "%(id)s_%(autonumber)03d.%(ext)s"),
            "quiet": True,
            "restrictfilenames": True,
            "noplaylist": False,
            "format": "best",
            "retries": 1,
            "fragment_retries": 1,
            "extractor_retries": 1,
            "socket_timeout": 20,
        }
        if cookies_file:
            opts["cookiefile"] = str(cookies_file)
        with yt_dlp.YoutubeDL(opts) as downloader:
            downloader.extract_info(url, download=True)

    def _download_gallery(self, url: str, directory: Path, cookies_file):
        cmd = [
            sys.executable, "-m", "gallery_dl", "--config-ignore", "--no-input",
            "--quiet", "--no-colors", "--http-timeout", "20", "--retries", "1",
            "-D", str(directory),
        ]
        if cookies_file:
            cmd.extend(["--cookies", str(cookies_file)])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=GALLERY_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("gallery-dl timed out after 120 seconds") from error
        if result.returncode:
            # Prefer extractor errors over warnings and Python source lines.
            lines = result.stderr.splitlines()
            details = [line for line in lines if "[error]" in line.lower()]
            detail = " | ".join(details or lines[-3:])
            raise RuntimeError(f"gallery-dl failed ({result.returncode}): {detail}")

    def _download_instaloader(self, url: str, directory: Path, cookies_file):
        match = re.search(r"/(?:p|reels?|tv)/([\w-]+)", urlsplit(url).path)
        if not match:
            raise RuntimeError("Instaloader needs a post or reel URL")
        loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            post_metadata_txt_pattern="",
            dirname_pattern=str(directory),
            filename_pattern="{shortcode}",
            max_connection_attempts=1,
            request_timeout=20,
            fatal_status_codes=[400, 401, 403, 429],
        )
        try:
            loader.context.raise_all_errors = True
            if cookies_file:
                jar = http.cookiejar.MozillaCookieJar(str(cookies_file))
                jar.load(ignore_discard=True, ignore_expires=True)
                loader.context._session.cookies.update(jar)
                csrf = next((cookie.value for cookie in jar if cookie.name == "csrftoken"), None)
                if csrf:
                    loader.context._session.headers["X-CSRFToken"] = csrf
                loader.context.username = loader.test_login()
                if not loader.context.username:
                    raise RuntimeError("Instagram login required: session cookies are no longer valid")
            post = instaloader.Post.from_shortcode(loader.context, match.group(1))
            if not loader.download_post(post, target=str(directory)):
                raise RuntimeError("Instaloader did not download the complete post")
        finally:
            loader.close()

    def _download_browser(self, url: str, directory: Path, cookies_file):
        # The saved browser session stays in Chromium and is not given to extractors.
        download_with_browser(url, directory)

    async def download(
        self, url: str, download_dir: Path, progress_callback=None
    ) -> Tuple[List[Path], str]:
        parts = urlsplit(url)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        download_dir.mkdir(parents=True, exist_ok=True)

        def sync_download():
            cookies = self._cookies()
            authenticated = any(cookie.name == "sessionid" for cookie in cookies)
            if not authenticated:
                log.warning("Cookie file has no valid Instagram sessionid; the saved browser profile is checked separately")

            attempts = [(self._download_ytdlp, False)]
            if authenticated:
                attempts.extend([(self._download_ytdlp, True), (self._download_gallery, True)])
            attempts.append((self._download_gallery, False))
            if instaloader is not None and re.match(r"/(?:p|reels?|tv)/", parts.path):
                attempts.append((self._download_instaloader, authenticated))
            if re.match(r"/(?:p|reels?|tv)/", parts.path):
                attempts.append((self._download_browser, False))

            errors = []
            browser_error = None
            for download, use_cookies in attempts:
                label = f"{download.__name__} ({'authenticated' if use_cookies else 'anonymous'})"
                if download.__name__ == "_download_browser":
                    label = "Chromium (saved browser profile)"
                log.info("Instagram: trying %s", label)
                # Each attempt owns its files, including partial downloads and cookies.
                with TemporaryDirectory(prefix=".instagram-", dir=download_dir) as temp:
                    directory = Path(temp)
                    cookie_file = None
                    if use_cookies:
                        cookie_file = directory / "cookies.txt"
                        cookies.save(str(cookie_file), ignore_discard=True, ignore_expires=True)
                    try:
                        download(url, directory, cookie_file)
                        files = self._media_files(directory)
                        if not files:
                            raise RuntimeError("No media files downloaded")
                    except Exception as error:
                        if isinstance(error, BrowserDownloadError):
                            browser_error = error
                        errors.append(str(error))
                        log.warning("Instagram %s failed: %s", label, error)
                        continue

                    media_type = self._media_type(files)
                    batch = uuid4().hex[:12]
                    output = []
                    for index, file in enumerate(files, 1):
                        target = download_dir / f"instagram_{batch}_{index:03d}{file.suffix.lower()}"
                        shutil.move(str(file), target)
                        output.append(target)
                    return output, media_type

            if browser_error is not None:
                raise InstagramDownloadError(str(browser_error))
            raise self._public_error(errors, authenticated)

        return await asyncio.get_running_loop().run_in_executor(POOL, sync_download)
