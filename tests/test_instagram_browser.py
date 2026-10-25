"""Browser metadata selection, profile protection, and login behavior."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from downloaders import instagram_browser as browser


CODE = "DcRNIyUxZCS"
URL = f"https://www.instagram.com/reel/{CODE}/"
VIDEO = "https://scontent.cdninstagram.com/video.mp4?token=private"
AUDIO = "https://video.xx.fbcdn.net/audio.m4a?token=private"
PHOTO = "https://scontent.cdninstagram.com/photo.jpg"


class BrowserMetadataTests(unittest.TestCase):
    def test_only_requested_post_is_selected_from_recommendations(self):
        expected = {"code": CODE, "video_versions": [{"url": VIDEO}]}
        recommendations = {"code": "DifferentPost", "video_versions": [{"url": VIDEO}]}
        document = {"data": [recommendations, {"items": [expected]}]}
        self.assertEqual(list(browser.find_post(document, CODE)), [expected])

    def test_numeric_media_id_and_nested_json_are_supported(self):
        post = {"pk": browser.media_id(CODE), "video_url": VIDEO}
        self.assertEqual(list(browser.find_post({"data": post}, CODE)), [post])
        encoded = json.dumps({"data": {"shortcode": CODE, "video_url": VIDEO}})
        self.assertEqual(len(list(browser.find_post({"payload": encoded}, CODE))), 1)

    def test_mixed_carousel_preserves_order_and_highest_resolution(self):
        post = {"carousel_media": [
            {"media_type": 1, "image_versions2": {"candidates": [{"url": PHOTO, "width": 1080, "height": 1080}]}},
            {"media_type": 2, "video_versions": [
                {"url": VIDEO + "&low", "width": 320, "height": 320},
                {"url": VIDEO, "width": 1080, "height": 1920},
            ]},
        ]}
        self.assertEqual(browser.post_media(post), [("photo", (PHOTO,)), ("video", (VIDEO,))])

    def test_graphql_carousel_uses_original_images_and_videos(self):
        post = {"edge_sidecar_to_children": {"edges": [
            {"node": {"is_video": False, "display_url": PHOTO}},
            {"node": {"is_video": True, "video_url": VIDEO, "display_url": PHOTO}},
        ]}}
        self.assertEqual(browser.post_media(post), [("photo", (PHOTO,)), ("video", (VIDEO,))])

    def test_incomplete_carousel_is_not_returned_as_success(self):
        with self.assertRaises(browser.BrowserDownloadError):
            browser.post_media({"carousel_media": [{"display_url": PHOTO}, {"is_video": True}]})

    def test_dash_selects_video_and_audio_instead_of_silent_video(self):
        manifest = f'''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
          <AdaptationSet mimeType="video/mp4">
            <Representation width="320" height="240" bandwidth="100"><BaseURL>{VIDEO}&amp;low</BaseURL></Representation>
            <Representation width="1080" height="1920" bandwidth="1000"><BaseURL>{VIDEO}</BaseURL></Representation>
          </AdaptationSet>
          <AdaptationSet mimeType="audio/mp4"><Representation bandwidth="128000"><BaseURL>{AUDIO}</BaseURL></Representation></AdaptationSet>
        </Period></MPD>'''
        self.assertEqual(browser.post_media({"is_video": True, "video_dash_manifest": manifest}), [("video", (VIDEO, AUDIO))])

    def test_media_hosts_reject_unrelated_urls_and_non_https(self):
        for url in ["https://cdninstagram.com.evil.test/video.mp4", "http://scontent.cdninstagram.com/v.mp4", "file:///tmp/video.mp4"]:
            with self.subTest(url=url):
                self.assertFalse(browser.media_host(url))


class BrowserProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.profile = self.directory / "profile"
        self.output = self.directory / "output"
        self.output.mkdir()
        self.enterContext(patch.dict(os.environ, {"INSTAGRAM_BROWSER_PROFILE": str(self.profile)}))
        self.playwright = self.enterContext(patch.object(browser, "sync_playwright"))
        self.launch = self.enterContext(patch.object(browser, "launch_context"))
        self.context = self.launch.return_value
        self.context.pages[0].locator.return_value.count.return_value = 0

    def ready(self):
        self.profile.mkdir()
        (self.profile / browser.READY_FILE).touch()

    def test_browser_is_not_launched_without_manual_login(self):
        with self.assertRaises(browser.BrowserDownloadError) as error:
            browser.download_with_browser(URL, self.output)
        self.assertEqual(error.exception.kind, "login")
        self.playwright.assert_not_called()

    def test_profile_lock_also_excludes_a_separate_file_descriptor(self):
        with browser.profile_lock(self.profile):
            with self.assertRaises(browser.BrowserDownloadError) as error:
                with browser.profile_lock(self.profile):
                    self.fail("The same profile was opened twice")
            self.assertEqual(error.exception.kind, "busy")
        with browser.profile_lock(self.profile):
            pass

    def test_expired_session_pauses_browser_and_closes_context(self):
        self.ready()
        self.context.cookies.return_value = []
        with self.assertRaises(browser.BrowserDownloadError) as error:
            browser.download_with_browser(URL, self.output)
        self.assertEqual(error.exception.kind, "login")
        self.assertTrue((self.profile / browser.PAUSED_FILE).exists())
        self.context.close.assert_called_once()

    def test_challenge_pauses_further_browser_attempts(self):
        self.ready()
        self.context.cookies.return_value = [{"name": "sessionid", "value": "not-logged", "expires": -1}]
        page = self.context.pages[0]
        page.url = "https://www.instagram.com/challenge/"
        page.locator.return_value.inner_text.return_value = "Confirm it's you"
        with self.assertRaises(browser.BrowserDownloadError) as error:
            browser.download_with_browser(URL, self.output)
        self.assertEqual(error.exception.kind, "challenge")
        with self.assertRaises(browser.BrowserDownloadError):
            browser.download_with_browser(URL, self.output)
        self.launch.assert_called_once()

    def test_browser_collects_requested_post_and_downloads_only_its_media(self):
        self.ready()
        self.context.cookies.return_value = [{"name": "sessionid", "value": "not-logged", "expires": -1}]
        page = self.context.pages[0]
        page.url = URL
        page.locator.return_value.inner_text.return_value = "A public post"
        post = {"code": CODE, "video_url": VIDEO}
        page.locator.return_value.all_text_contents.return_value = [json.dumps({"data": post})]
        page.evaluate.return_value = "Test Chromium"
        with patch.object(browser, "save_media", return_value=[self.output / "video.mp4"]) as save:
            browser.download_with_browser(URL, self.output)
        save.assert_called_once_with([("video", (VIDEO,))], self.output, "Test Chromium", URL)
        self.context.close.assert_called_once()

    def test_anonymous_check_uses_a_different_profile(self):
        self.ready()
        page = self.context.pages[0]
        page.url = URL
        page.locator.return_value.inner_text.return_value = "Age-restricted content"
        with self.assertRaises(browser.BrowserDownloadError) as error:
            browser.download_with_browser(URL, self.output, anonymous=True)
        self.assertEqual(error.exception.kind, "access")
        self.assertNotEqual(self.launch.call_args.args[1], self.profile)
        self.assertFalse((self.profile / browser.PAUSED_FILE).exists())

    def test_rate_limit_stops_browser_without_invalidating_saved_login(self):
        self.ready()
        self.context.cookies.return_value = [{"name": "sessionid", "value": "fixture", "expires": -1}]
        page = self.context.pages[0]
        page.goto.return_value.status = 429
        with self.assertRaises(browser.BrowserDownloadError) as error:
            browser.download_with_browser(URL, self.output)
        self.assertEqual(error.exception.kind, "rate")
        self.assertFalse((self.profile / browser.PAUSED_FILE).exists())
        page.wait_for_timeout.assert_not_called()


class BrowserSavingTests(unittest.TestCase):
    def test_separate_video_and_audio_are_muxed_and_temporary_streams_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def download(url, destination, *args):
                destination.write_bytes(b"stream")

            def mux(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"combined")
                self.assertIn("0:v:0", cmd)
                self.assertIn("1:a:0", cmd)
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(browser, "save_stream", side_effect=download), patch.object(browser.subprocess, "run", side_effect=mux):
                files = browser.save_media([("video", (VIDEO, AUDIO))], root, "Chromium", URL)
            self.assertEqual([file.read_bytes() for file in files], [b"combined"])
            self.assertFalse(list(root.glob("*.part")))

    def test_cdn_download_does_not_send_instagram_cookies(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.url = VIDEO
        response.status = 200
        response.headers = {"Content-Type": "video/mp4", "Content-Length": "5"}
        response.read.side_effect = [b"video", b""]
        with tempfile.TemporaryDirectory() as directory, patch.object(browser, "urlopen", return_value=response) as request:
            target = Path(directory) / "video.mp4"
            browser.save_stream(VIDEO, target, "Chromium", URL)
            self.assertEqual(target.read_bytes(), b"video")
        headers = request.call_args.args[0].headers
        self.assertNotIn("Cookie", headers)
        self.assertEqual(headers["Referer"], URL)

    def test_truncated_cdn_file_is_rejected(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.url = VIDEO
        response.status = 200
        response.headers = {"Content-Type": "video/mp4", "Content-Length": "100"}
        response.read.side_effect = [b"partial", b""]
        with tempfile.TemporaryDirectory() as directory, patch.object(browser, "urlopen", return_value=response):
            with self.assertRaisesRegex(browser.BrowserDownloadError, "неповний"):
                browser.save_stream(VIDEO, Path(directory) / "video.mp4", "Chromium", URL)


class BrowserLoginTests(unittest.TestCase):
    def test_manual_login_saves_marker_and_resumes_paused_profile(self):
        import instagram_browser as cli

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / browser.PAUSED_FILE).touch()
            with patch.object(cli, "profile_path", return_value=profile), patch.object(cli, "sync_playwright"), patch.object(cli, "launch_context") as launch, patch("builtins.input", return_value=""), patch.object(cli, "has_session", return_value=True), patch.object(cli, "page_problem", return_value=None):
                cli.login()
            self.assertTrue((profile / browser.READY_FILE).is_file())
            self.assertFalse((profile / browser.PAUSED_FILE).exists())
            launch.assert_called_once()
            self.assertFalse(launch.call_args.kwargs["headless"])
            launch.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
