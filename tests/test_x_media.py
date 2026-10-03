"""X media mapping: animated GIFs stay playable silent videos."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.ingest.x import post_media_list
from backend.main import app
from backend.services.link_previews import allowed_twimg_video_url


def _media(*, media_type: str, url: str, bit_rate: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        type=media_type,
        media_key="16_1",
        alt_text="leaderboard",
        preview_image_url="https://pbs.twimg.com/tweet_video_thumb/x.jpg",
        url=None,
        variants=[
            SimpleNamespace(
                content_type="video/mp4",
                bit_rate=bit_rate,
                url=url,
            )
        ],
    )


def _post() -> SimpleNamespace:
    return SimpleNamespace(
        attachments=SimpleNamespace(media_keys=["16_1"]),
        entities=SimpleNamespace(urls=[]),
    )


class XMediaTests(unittest.TestCase):
    def test_animated_gif_is_flagged(self) -> None:
        media = _media(
            media_type="animated_gif",
            url="https://video.twimg.com/tweet_video/HTqhiUfaUAArFbQ.mp4",
        )
        out = post_media_list(_post(), {"16_1": media})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "video")
        self.assertTrue(out[0]["gif"])
        self.assertEqual(
            out[0]["url"],
            "https://video.twimg.com/tweet_video/HTqhiUfaUAArFbQ.mp4",
        )

    def test_real_video_is_not_a_gif(self) -> None:
        media = _media(
            media_type="video",
            url="https://video.twimg.com/amplify_video/1/vid/avc1/1.mp4",
            bit_rate=832000,
        )
        out = post_media_list(_post(), {"16_1": media})
        self.assertEqual(out[0]["kind"], "video")
        self.assertNotIn("gif", out[0])


class TwimgVideoUrlTests(unittest.TestCase):
    def test_allows_gif_and_amplify_mp4(self) -> None:
        gif = "https://video.twimg.com/tweet_video/HTqhiUfaUAArFbQ.mp4"
        amplify = (
            "https://video.twimg.com/amplify_video/1/vid/avc1/960x576/abc.mp4"
        )
        self.assertEqual(allowed_twimg_video_url(gif), gif)
        self.assertEqual(allowed_twimg_video_url(amplify), amplify)

    def test_rejects_other_targets(self) -> None:
        rejected = [
            "https://evil.example/tweet_video/a.mp4",
            "http://video.twimg.com/tweet_video/a.mp4",
            "https://video.twimg.com.evil.example/tweet_video/a.mp4",
            "https://user:pass@video.twimg.com/tweet_video/a.mp4",
            "https://video.twimg.com/tweet_video/../secret",
            "https://pbs.twimg.com/media/abc.jpg",
            "https://video.twimg.com/tweet_video/a.m3u8",
        ]
        for url in rejected:
            self.assertIsNone(allowed_twimg_video_url(url), url)

    def test_proxy_rejects_unsupported_host(self) -> None:
        client = TestClient(app)
        response = client.get(
            "/api/media/video",
            params={"url": "https://evil.example/a.mp4"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
