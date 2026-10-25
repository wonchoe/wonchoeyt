"""Download media exposed by the Instagram web page in a saved browser session."""

import json
import os
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


_BROWSER_LOCK = threading.Lock()
DEFAULT_PROFILE = "/var/www/playwright-profile/instagram-downloads"
READY_FILE = ".login-ready"
PAUSED_FILE = ".login-required"


class BrowserDownloadError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def profile_path():
    return Path(os.getenv("INSTAGRAM_BROWSER_PROFILE", DEFAULT_PROFILE)).expanduser().resolve()


@contextmanager
def profile_lock(profile):
    """Prevent login, downloads, and other processes from opening the same profile."""
    import fcntl

    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = profile / ".profile.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BrowserDownloadError("busy", "Браузер Instagram зайнятий входом або іншим завантаженням. Спробуйте пізніше.") from None
        yield
    finally:
        os.close(descriptor)


def launch_context(playwright, profile, headless=True):
    return playwright.chromium.launch_persistent_context(
        str(profile), headless=headless, locale="en-US",
        viewport={"width": 1280, "height": 900},
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        timeout=30000,
    )


def has_session(context):
    return any(cookie["name"] == "sessionid" and cookie.get("value")
               and (cookie.get("expires", -1) <= 0 or cookie["expires"] > time.time())
               for cookie in context.cookies("https://www.instagram.com/"))


def mark_paused(profile):
    (profile / PAUSED_FILE).touch(mode=0o600)


def page_problem(page):
    path = urlsplit(page.url).path.lower()
    text = page.locator("body").inner_text(timeout=5000).lower()
    if any(part in path for part in ("/challenge", "/checkpoint", "/accounts/suspended", "/accounts/disabled")) or any(
        part in text for part in ("we suspect automated behavior", "we detected automated behavior",
                                  "confirm it's you", "suspicious activity", "your account has been suspended")
    ):
        return "challenge"
    if "/accounts/login" in path:
        return "login"
    password = page.locator('input[name="password"]')
    if password.count() and password.first.is_visible():
        return "login"
    if "age-restricted content" in text or "this account is private" in text:
        return "access"
    if "please wait a few minutes before you try again" in text:
        return "rate"
    if any(part in text for part in ("sorry, this page isn't available", "page may have been removed")):
        return "unavailable"
    return None


def media_host(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(
        host == domain or host.endswith("." + domain)
        for domain in ("cdninstagram.com", "fbcdn.net")
    )


def shortcode_from_url(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/(?:p|reels?|tv)/([A-Za-z0-9_-]+)/?", parts.path)
    if parts.hostname not in {"instagram.com", "www.instagram.com", "instagr.am"} or not match:
        raise BrowserDownloadError("unsupported", "Браузерне завантаження підтримує посилання на дописи та Reels Instagram.")
    return match.group(1)


def media_id(shortcode):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    value = 0
    for char in shortcode:
        value = value * 64 + alphabet.index(char)
    return str(value)


def find_post(data, shortcode):
    """Match the requested post, ignoring recommendations and other carousel posts."""
    expected_id = media_id(shortcode)
    stack = [(data, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 60:
            continue
        if isinstance(node, dict):
            matches = node.get("code") == shortcode or node.get("shortcode") == shortcode or any(
                str(node.get(key, "")).split("_")[0] == expected_id for key in ("pk", "id")
            )
            if matches and any(key in node for key in (
                "video_url", "video_versions", "video_dash_manifest", "image_versions2",
                "display_url", "carousel_media", "edge_sidecar_to_children",
            )):
                yield node
            stack.extend((value, depth + 1) for value in reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in reversed(node))
        elif isinstance(node, str) and node.startswith(("{", "[")) and shortcode in node:
            try:
                stack.append((json.loads(node), depth + 1))
            except (ValueError, RecursionError):
                pass


def dash_streams(manifest):
    """Pick complete video/audio BaseURLs, never concatenate browser byte ranges."""
    if not manifest:
        return None
    try:
        root = ET.fromstring(manifest)
        video, audio = [], []
        for group in root.iter():
            if group.tag.rsplit("}", 1)[-1] != "AdaptationSet":
                continue
            for item in group:
                if item.tag.rsplit("}", 1)[-1] != "Representation":
                    continue
                base = next((child.text for child in item if child.tag.rsplit("}", 1)[-1] == "BaseURL"), None)
                if not base or not media_host(base):
                    continue
                mime = item.get("mimeType", group.get("mimeType", ""))
                bandwidth = int(item.get("bandwidth", "0"))
                if mime.startswith("video/"):
                    video.append((int(item.get("width", "0")) * int(item.get("height", "0")), bandwidth, base))
                elif mime.startswith("audio/"):
                    audio.append((bandwidth, base))
        if video and audio:
            return max(video)[-1], max(audio)[-1]
    except (ET.ParseError, ValueError, TypeError):
        pass
    return None


def post_media(post):
    carousel = post.get("carousel_media")
    if carousel is None:
        carousel = [edge.get("node", {}) for edge in post.get("edge_sidecar_to_children", {}).get("edges", [])]
    if carousel:
        return [media for item in carousel for media in post_media(item)]
    is_video = post.get("is_video") or post.get("media_type") == 2 or post.get("video_versions") or post.get("video_url")
    if is_video:
        streams = dash_streams(post.get("video_dash_manifest"))
        if streams:
            return [("video", streams)]
        versions = [item for item in post.get("video_versions", []) if media_host(item.get("url", ""))]
        url = max(versions, key=lambda item: item.get("width", 0) * item.get("height", 0))["url"] if versions else post.get("video_url", "")
        if media_host(url):
            return [("video", (url,))]
    else:
        versions = [item for item in post.get("image_versions2", {}).get("candidates", []) if media_host(item.get("url", ""))]
        url = max(versions, key=lambda item: item.get("width", 0) * item.get("height", 0))["url"] if versions else post.get("display_url", "")
        if media_host(url):
            return [("photo", (url,))]
    raise BrowserDownloadError("media", "Браузер не отримав повне медіа цього допису Instagram.")


def save_stream(url, destination, user_agent, referer):
    """Stream signed CDN media to disk without exporting Instagram account cookies."""
    if not media_host(url):
        raise BrowserDownloadError("media", "Instagram повернув непідтримуване посилання на медіа.")
    request = Request(url, headers={"User-Agent": user_agent, "Referer": referer})
    started = time.monotonic()
    size = 0
    with urlopen(request, timeout=30) as response, destination.open("wb") as output:
        if not media_host(response.url) or response.status != 200:
            raise BrowserDownloadError("media", "Не вдалося отримати повний медіафайл Instagram.")
        mime = response.headers.get("Content-Type", "").lower()
        if not mime.startswith(("video/", "audio/", "image/", "application/octet-stream")):
            raise BrowserDownloadError("media", "Instagram повернув сторінку замість медіафайлу.")
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            if size > 2 * 1024 ** 3 or time.monotonic() - started > 600:
                raise BrowserDownloadError("media", "Перевищено ліміт розміру або часу завантаження Instagram.")
            output.write(chunk)
        if not size:
            raise BrowserDownloadError("media", "Instagram повернув порожній медіафайл.")
        expected = response.headers.get("Content-Length")
        if expected is not None and size != int(expected):
            raise BrowserDownloadError("media", "Instagram передав неповний медіафайл. Спробуйте ще раз.")


def save_media(media, directory, user_agent, referer):
    files = []
    for index, (kind, urls) in enumerate(media, 1):
        target = directory / f"browser_{index:03d}{'.mp4' if kind == 'video' else '.jpg'}"
        if len(urls) == 1:
            save_stream(urls[0], target, user_agent, referer)
        else:
            video, audio = directory / f"video_{index}.part", directory / f"audio_{index}.part"
            save_stream(urls[0], video, user_agent, referer)
            save_stream(urls[1], audio, user_agent, referer)
            try:
                result = subprocess.run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                    "-c", "copy", "-movflags", "+faststart", str(target),
                ], capture_output=True, timeout=120)
                if result.returncode:
                    raise BrowserDownloadError("media", "Не вдалося об’єднати відео та звук Instagram.")
            finally:
                video.unlink(missing_ok=True)
                audio.unlink(missing_ok=True)
        files.append(target)
    return files


def download_with_browser(url, directory, *, anonymous=False):
    shortcode = shortcode_from_url(url)
    profile = profile_path()
    if not anonymous and ((profile / PAUSED_FILE).exists() or not (profile / READY_FILE).is_file()):
        raise BrowserDownloadError("login", "Для цього допису потрібен вхід в Instagram. Адміністратору потрібно оновити браузерну сесію бота.")
    with _BROWSER_LOCK:
        # Anonymous checks always use an isolated profile and never touch the saved login.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="instagram-anonymous-") as temporary:
            selected = Path(temporary) if anonymous else profile
            with profile_lock(selected), sync_playwright() as playwright:
                try:
                    context = launch_context(playwright, selected)
                except Exception:
                    raise BrowserDownloadError("launch", "Не вдалося запустити браузер Instagram. Перевірте встановлення Chromium і доступність профілю.") from None
                try:
                    if not anonymous and not has_session(context):
                        mark_paused(profile)
                        raise BrowserDownloadError("login", "Сесія браузера Instagram завершилася. Адміністратору потрібно повторити вхід.")
                    page = context.pages[0] if context.pages else context.new_page()
                    posts = []

                    def collect(request):
                        parts = urlsplit(request.url)
                        if parts.hostname not in {"www.instagram.com", "instagram.com", "i.instagram.com"} or not any(
                            part in parts.path for part in ("/graphql", "/api/v1/")
                        ):
                            return
                        try:
                            response = request.response()
                            if response and response.ok:
                                text = response.text()
                                if text.startswith("for (;;);"):
                                    text = text[9:]
                                if len(text) < 10 * 1024 ** 2:
                                    posts.extend(find_post(json.loads(text), shortcode))
                        except Exception:
                            # Never log response bodies, signed media URLs, or session cookies.
                            pass

                    page.on("requestfinished", collect)
                    navigation = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if navigation is not None and navigation.status == 429:
                        raise BrowserDownloadError("rate", "Instagram тимчасово обмежив запити. Спробуйте пізніше.")
                    problem = None
                    for _ in range(30):
                        page.wait_for_timeout(1000)
                        problem = page_problem(page)
                        if problem in {"challenge", "login", "access", "unavailable", "rate"}:
                            break
                        if not posts:
                            for text in page.locator('script[type="application/json"]').all_text_contents():
                                try:
                                    posts.extend(find_post(json.loads(text), shortcode))
                                except (ValueError, RecursionError):
                                    pass
                        if posts:
                            break
                    if problem in {"challenge", "login"}:
                        if not anonymous:
                            mark_paused(profile)
                        raise BrowserDownloadError(problem, "Instagram попросив перевірити акаунт або повторити вхід. Браузерні спроби призупинено до ручного входу.")
                    if problem == "access":
                        raise BrowserDownloadError("access", "Цей акаунт Instagram не має доступу до допису. Перевірте вікові обмеження або підписку на закритий профіль.")
                    if problem == "unavailable":
                        raise BrowserDownloadError("unavailable", "Допис Instagram недоступний цьому акаунту або видалений.")
                    if problem == "rate":
                        raise BrowserDownloadError("rate", "Instagram тимчасово обмежив запити. Спробуйте пізніше.")
                    candidates = []
                    for post in posts:
                        try:
                            candidates.append(post_media(post))
                        except BrowserDownloadError:
                            continue
                    if not candidates:
                        raise BrowserDownloadError("media", "Браузер не отримав медіа цього допису Instagram. Перевірте посилання після входу.")
                    # Prefer full carousels over smaller duplicate metadata objects.
                    media = max(candidates, key=len)
                    return save_media(media, directory, page.evaluate("navigator.userAgent"), url)
                except PlaywrightTimeout:
                    raise BrowserDownloadError("timeout", "Браузер Instagram не дочекався відповіді. Спробуйте пізніше.") from None
                except BrowserDownloadError:
                    raise
                except Exception:
                    raise BrowserDownloadError("media", "Не вдалося зберегти медіа з браузера Instagram. Спробуйте пізніше.") from None
                finally:
                    context.close()
