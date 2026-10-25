"""Regressions for Instagram retries, authentication, and media isolation."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from downloaders.instagram import InstagramDownloader, InstagramDownloadError
from downloaders.instagram_browser import BrowserDownloadError


URL = "https://www.instagram.com/reel/DcRNIyUxZCS/?srtk=tracking#fragment"
CLEAN_URL = "https://www.instagram.com/reel/DcRNIyUxZCS/"
RESTRICTED = "This content isn't available to everyone: It can't be seen by certain audiences."


class InstagramDownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "downloads"
        self.directory.mkdir()
        self.cookies = self.root / "cookies.txt"
        self.enterContext(patch.dict(os.environ, {"INSTAGRAM_COOKIES_FILE": str(self.cookies)}))
        self.ytdlp = self.enterContext(patch("downloaders.instagram.yt_dlp.YoutubeDL"))
        self.gallery = self.enterContext(patch("downloaders.instagram.subprocess.run"))
        self.instaloader = self.enterContext(patch("downloaders.instagram.instaloader"))
        self.browser = self.enterContext(patch(
            "downloaders.instagram.download_with_browser",
            side_effect=BrowserDownloadError("login", "Для цього допису потрібен вхід у браузері Instagram."),
        ))

    def write_cookies(self, session=True, expires=None):
        expiry = int(time.time()) + 3600 if expires is None else expires
        lines = ["# Netscape HTTP Cookie File\n",
                 ".youtube.com\tTRUE\t/\tTRUE\t0\tSSID\tyoutube-secret\n",
                 ".instagram.com\tTRUE\t/\tTRUE\t0\tcsrftoken\tcsrf\n"]
        if session:
            lines.append(f"#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t{expiry}\tsessionid\tinstagram-secret\n")
        self.cookies.write_text("".join(lines))

    def yt_success(self, opts):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        self.last_ytdlp = downloader

        def extract(url, download):
            # No vcodec key, as observed in production for an actual Reel.
            path = Path(opts["outtmpl"]).parent / "reel.mp4"
            path.write_bytes(b"video")
            return {"id": "reel", "ext": "mp4"}

        downloader.extract_info.side_effect = extract
        return downloader

    def yt_failure(self, opts):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.side_effect = RuntimeError(RESTRICTED)
        return downloader

    async def test_mp4_without_codec_is_video_and_url_is_cleaned(self):
        self.ytdlp.side_effect = self.yt_success
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "video")
        self.assertEqual([file.read_bytes() for file in files], [b"video"])
        self.assertEqual(files[0].parent, self.directory)
        self.last_ytdlp.extract_info.assert_called_once_with(CLEAN_URL, download=True)
        self.gallery.assert_not_called()
        self.browser.assert_not_called()
        self.assertFalse(list(self.directory.glob(".instagram-*")))

    async def test_authenticated_gallery_retry_uses_private_cookie_copy(self):
        self.write_cookies()
        original_cookies = self.cookies.read_bytes()
        self.ytdlp.side_effect = self.yt_failure
        unrelated = self.directory / "other-user.mp4"
        unrelated.write_bytes(b"unrelated")

        def gallery(cmd, **kwargs):
            self.assertNotIn("--no-check-certificate", cmd)
            self.assertEqual(cmd[-1], CLEAN_URL)
            cookie_copy = Path(cmd[cmd.index("--cookies") + 1])
            self.assertNotEqual(cookie_copy, self.cookies)
            self.assertIn("sessionid", cookie_copy.read_text())
            self.assertNotIn("youtube-secret", cookie_copy.read_text())
            destination = Path(cmd[cmd.index("-D") + 1])
            (destination / "post_2.jpg").write_bytes(b"second")
            (destination / "post_10.mp4").write_bytes(b"tenth")
            (destination / "post_11.mp4.part").write_bytes(b"partial")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self.gallery.side_effect = gallery
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(self.ytdlp.call_count, 2)
        self.assertNotIn("cookiefile", self.ytdlp.call_args_list[0].args[0])
        cookie_copy = Path(self.ytdlp.call_args_list[1].args[0]["cookiefile"])
        self.assertNotEqual(cookie_copy, self.cookies)
        self.assertFalse(cookie_copy.exists())
        self.assertEqual(media_type, "mixed_album")
        self.assertEqual([file.read_bytes() for file in files], [b"second", b"tenth"])
        self.assertEqual(unrelated.read_bytes(), b"unrelated")
        self.assertEqual(self.cookies.read_bytes(), original_cookies)
        self.gallery.assert_called_once()
        self.instaloader.Instaloader.assert_not_called()

    async def test_empty_ytdlp_result_continues_to_gallery(self):
        self.ytdlp.return_value.__enter__.return_value.extract_info.return_value = {"entries": []}

        def gallery(cmd, **kwargs):
            self.assertNotIn("--cookies", cmd)
            destination = Path(cmd[cmd.index("-D") + 1])
            (destination / "photo.webp").write_bytes(b"photo")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self.gallery.side_effect = gallery
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "photo")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].suffix, ".webp")

    async def test_stale_session_can_fall_back_to_anonymous_gallery(self):
        self.write_cookies()
        self.ytdlp.side_effect = self.yt_failure

        def gallery(cmd, **kwargs):
            if "--cookies" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "[instagram][error] login required")
            destination = Path(cmd[cmd.index("-D") + 1])
            (destination / "video.mp4").write_bytes(b"video")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self.gallery.side_effect = gallery
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "video")
        self.assertEqual(len(files), 1)
        self.assertEqual(self.gallery.call_count, 2)
        self.instaloader.Instaloader.assert_not_called()

    async def test_authenticated_ytdlp_success_skips_other_downloaders(self):
        self.write_cookies()
        self.ytdlp.side_effect = lambda opts: self.yt_success(opts) if "cookiefile" in opts else self.yt_failure(opts)
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "video")
        self.assertEqual(len(files), 1)
        self.assertEqual(self.ytdlp.call_count, 2)
        self.gallery.assert_not_called()

    def test_instaloader_sets_authenticated_context_from_cookies(self):
        self.write_cookies()
        loader = self.instaloader.Instaloader.return_value
        loader.context._session.headers = {}
        loader.test_login.return_value = "test_account"
        InstagramDownloader()._download_instaloader(CLEAN_URL, self.directory, self.cookies)
        self.assertEqual(loader.context.username, "test_account")
        self.assertEqual(loader.context._session.headers["X-CSRFToken"], "csrf")
        self.assertTrue(loader.context.raise_all_errors)
        loader.close.assert_called_once()

    async def test_guest_cookies_skip_auth_retries_and_keep_access_error_after_timeout(self):
        self.write_cookies(session=False)
        self.ytdlp.side_effect = self.yt_failure
        self.gallery.side_effect = subprocess.TimeoutExpired("gallery-dl", 120)
        self.instaloader.Post.from_shortcode.side_effect = RuntimeError("login required")
        with self.assertRaisesRegex(InstagramDownloadError, "потрібен вхід") as error:
            await InstagramDownloader().download(URL, self.directory)
        self.assertNotIn("Command", str(error.exception))
        self.assertNotIn("InsecureRequestWarning", str(error.exception))
        self.ytdlp.assert_called_once()
        self.gallery.assert_called_once()
        self.assertNotIn("--cookies", self.gallery.call_args.args[0])
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_failed_gallery_partial_files_are_not_returned_by_instaloader(self):
        self.ytdlp.side_effect = self.yt_failure

        def gallery(cmd, **kwargs):
            destination = Path(cmd[cmd.index("-D") + 1])
            (destination / "partial.mp4").write_bytes(b"incomplete album")
            return subprocess.CompletedProcess(cmd, 1, "", "[instagram][error] login required")

        def loader(**kwargs):
            instance = MagicMock()

            def download(post, target):
                directory = Path(kwargs["dirname_pattern"])
                (directory / "shortcode_1.jpg").write_bytes(b"first")
                (directory / "shortcode_2.mp4").write_bytes(b"second")
                return True

            instance.download_post.side_effect = download
            return instance

        self.gallery.side_effect = gallery
        self.instaloader.Instaloader.side_effect = loader
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "mixed_album")
        self.assertEqual([file.read_bytes() for file in files], [b"first", b"second"])
        self.assertTrue(self.instaloader.Instaloader.call_args.kwargs["download_videos"])

    async def test_instaloader_failure_never_returns_partial_post(self):
        self.ytdlp.side_effect = self.yt_failure
        self.gallery.return_value = subprocess.CompletedProcess([], 1, "", "[instagram][error] login required")
        self.instaloader.Instaloader.return_value.download_post.return_value = False
        with self.assertRaises(InstagramDownloadError):
            await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_browser_runs_last_and_returns_video_after_all_extractors_fail(self):
        self.ytdlp.side_effect = self.yt_failure
        self.gallery.return_value = subprocess.CompletedProcess([], 1, "", "[instagram][error] login required")
        self.instaloader.Post.from_shortcode.side_effect = RuntimeError("login required")

        def browser(url, directory):
            self.assertEqual(url, CLEAN_URL)
            self.ytdlp.assert_called_once()
            self.gallery.assert_called_once()
            self.instaloader.Post.from_shortcode.assert_called_once()
            (directory / "browser_001.mp4").write_bytes(b"browser video")

        self.browser.side_effect = browser
        files, media_type = await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(media_type, "video")
        self.assertEqual([file.read_bytes() for file in files], [b"browser video"])
        self.browser.assert_called_once()
        self.assertFalse(list(self.directory.glob(".instagram-*")))

    async def test_browser_challenge_message_is_not_hidden_by_previous_login_errors(self):
        self.ytdlp.side_effect = self.yt_failure
        self.gallery.return_value = subprocess.CompletedProcess([], 1, "", "[instagram][error] login required")
        self.instaloader.Post.from_shortcode.side_effect = RuntimeError("login required")
        message = "Instagram попросив перевірити акаунт. Браузерні спроби призупинено."
        self.browser.side_effect = BrowserDownloadError("challenge", message)
        with self.assertRaises(InstagramDownloadError) as error:
            await InstagramDownloader().download(URL, self.directory)
        self.assertEqual(str(error.exception), message)

    def test_expired_session_and_other_domains_do_not_enable_authentication(self):
        self.write_cookies(expires=int(time.time()) - 3600)
        jar = InstagramDownloader._cookies()
        self.assertEqual([cookie.name for cookie in jar], ["csrftoken"])

    def test_session_cookie_with_zero_expiry_is_usable(self):
        self.write_cookies(expires=0)
        jar = InstagramDownloader._cookies()
        session = next(cookie for cookie in jar if cookie.name == "sessionid")
        self.assertIsNone(session.expires)

    def test_malformed_cookie_file_does_not_expose_cookie_values(self):
        self.cookies.write_text("invalid-format-secret")
        with self.assertLogs("ytbot", level="WARNING") as logs:
            self.assertEqual(list(InstagramDownloader._cookies()), [])
        self.assertNotIn("invalid-format-secret", " ".join(logs.output))

    def test_gallery_reports_extractor_error_instead_of_tls_warning(self):
        self.gallery.return_value = subprocess.CompletedProcess(
            [], 1, "", "InsecureRequestWarning: warning\n  warnings.warn(\n"
            "[instagram][error] HTTP redirect to login page\n"
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP redirect to login page") as error:
            InstagramDownloader()._download_gallery(CLEAN_URL, self.directory, None)
        self.assertNotIn("InsecureRequestWarning", str(error.exception))

    def test_error_messages_distinguish_rate_limits_timeouts_and_deleted_posts(self):
        for details, message in [
            ("429 Too many requests", "обмежив запити"),
            ("gallery-dl timed out after 120 seconds", "не відповів вчасно"),
            ("404 Not Found", "не знайдено"),
            (RESTRICTED, "Оновіть вхід"),
        ]:
            with self.subTest(details=details):
                self.assertIn(message, str(InstagramDownloader._public_error([details], True)))


class InstagramBotErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_shows_complete_actionable_error_without_sending_media(self):
        import app

        status = MagicMock(edit_text=AsyncMock())
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=status)
        update = MagicMock()
        message = "Для цього допису потрібен вхід в Instagram. " + "Оновіть cookies. " * 10
        with patch.object(app, "InstagramDownloader") as downloader, patch.object(app, "cleanup_old_files"):
            downloader.return_value.download = AsyncMock(side_effect=InstagramDownloadError(message))
            await app.download_instagram(update, context, URL)
        status.edit_text.assert_awaited_once_with(f"❌ {message}")
        context.bot.send_video.assert_not_called()
        context.bot.send_photo.assert_not_called()


class InstagramCookieRefreshTests(unittest.TestCase):
    def test_guest_cookies_warn_without_exposing_values(self):
        from cookie_refresher import warn_if_instagram_logged_out

        with self.assertLogs("cookie_refresher", level="WARNING") as logs:
            warn_if_instagram_logged_out([
                {"domain": ".instagram.com", "name": "csrftoken", "value": "secret"}
            ])
        self.assertIn("no valid sessionid", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    def test_authenticated_session_does_not_warn(self):
        from cookie_refresher import warn_if_instagram_logged_out

        with patch("cookie_refresher.log.warning") as warning:
            warn_if_instagram_logged_out([
                {"domain": ".instagram.com", "name": "sessionid", "value": "secret", "expires": -1}
            ])
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
