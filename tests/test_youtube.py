"""Regressions for authenticated YouTube downloads and anonymous retries."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from yt_dlp.utils import DownloadError

from downloaders.youtube import YouTubeDownloader


COOKIE_PATH = "/var/www/ytdl-cookies.txt"
URL = "https://www.youtube.com/watch?v=c7s9eKDQn9c"


class YouTubeRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.download_dir = Path(self.directory.name)
        self.source_file = self.download_dir / "sample.webm"
        self.audio_file = self.download_dir / "sample.mp3"
        self.audio_file.write_bytes(b"converted audio")

        self.enterContext(
            patch("downloaders.youtube.os.path.exists", return_value=True)
        )
        self.enterContext(patch("downloaders.youtube.os.path.getsize", return_value=200))
        self.enterContext(
            patch("builtins.open", mock_open(read_data="# Netscape HTTP Cookie File\n"))
        )
        self.youtube_dl = self.enterContext(patch("downloaders.youtube.yt_dlp.YoutubeDL"))

    def attempt(self, error=None):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        if error is not None:
            downloader.extract_info.side_effect = error
        else:
            downloader.extract_info.return_value = {"title": "sample", "ext": "webm"}
        downloader.prepare_filename.return_value = str(self.source_file)
        return downloader

    async def test_cookie_reload_error_retries_default_client_without_cookies(self):
        authenticated = self.attempt(DownloadError("The page needs to be reloaded."))
        anonymous = self.attempt()
        self.youtube_dl.side_effect = [authenticated, anonymous]

        output, media_type = await YouTubeDownloader().download(URL, self.download_dir)

        self.assertEqual(output, self.audio_file)
        self.assertEqual(media_type, "audio")
        self.assertEqual(self.youtube_dl.call_count, 2)
        authenticated_opts, anonymous_opts = [
            call.args[0] for call in self.youtube_dl.call_args_list
        ]
        self.assertEqual(authenticated_opts["cookiefile"], COOKIE_PATH)
        self.assertNotIn("cookiefile", anonymous_opts)
        self.assertNotIn(
            "player_client", anonymous_opts.get("extractor_args", {}).get("youtube", {})
        )
        anonymous.extract_info.assert_called_once_with(URL, download=True)

    async def test_android_retry_never_receives_account_cookies(self):
        authenticated = self.attempt(DownloadError("The page needs to be reloaded."))
        anonymous = self.attempt(DownloadError("Requested format is not available."))
        android = self.attempt()
        self.youtube_dl.side_effect = [authenticated, anonymous, android]

        output, media_type = await YouTubeDownloader().download(URL, self.download_dir)

        self.assertEqual((output, media_type), (self.audio_file, "audio"))
        self.assertEqual(self.youtube_dl.call_count, 3)
        retry_opts = [call.args[0] for call in self.youtube_dl.call_args_list]
        self.assertNotIn("cookiefile", retry_opts[1])
        self.assertNotIn("cookiefile", retry_opts[2])
        self.assertEqual(
            retry_opts[2]["extractor_args"]["youtube"]["player_client"], ["android"]
        )

    async def test_authenticated_success_keeps_converted_mp3_and_skips_retries(self):
        authenticated = self.attempt()
        self.youtube_dl.return_value = authenticated

        output, media_type = await YouTubeDownloader().download(URL, self.download_dir)

        self.assertEqual((output, media_type), (self.audio_file, "audio"))
        self.youtube_dl.assert_called_once()
        self.assertEqual(self.youtube_dl.call_args.args[0]["cookiefile"], COOKIE_PATH)
        self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
