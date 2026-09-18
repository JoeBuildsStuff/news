"""Regression tests for hub chat news_search matching."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.db import connect
from backend.services.chat_tools import news_search, parse_news_search_query


def _seed_hub(db_path: Path) -> None:
    conn = connect(db_path, seed=False)
    conn.execute(
        "INSERT INTO feeds (id, name, url) VALUES (?, ?, ?)",
        ("openai", "OpenAI News", "https://openai.com/news/rss.xml"),
    )
    conn.execute(
        """INSERT INTO items (
               feed_id, guid, title, link, summary, published_at, fetched_at,
               body_markdown, body_status
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "openai",
            "navier",
            "On the Navier–Stokes Millennium Prize Problem",
            "https://openai.com/index/navier-stokes-solution",
            "We're sharing an AI-generated solution to the Navier-Stokes problem.",
            "2026-09-08T10:00:00+00:00",
            "2026-09-08T12:00:00+00:00",
            (
                "The Millennium Prize Problems represent some of the deepest "
                "questions at the frontier of mathematics. An AI model produced "
                "a proof that fluid motion can develop a singularity."
            ),
            "ok",
        ),
    )
    conn.execute(
        """INSERT INTO items (
               feed_id, guid, title, link, summary, published_at, fetched_at,
               body_markdown, body_status
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "openai",
            "other",
            "Introducing ChatGPT Images 2.5",
            "https://openai.com/index/introducing-chatgpt-images-2-5",
            "New image generation in ChatGPT.",
            "2026-09-08T11:30:00+00:00",
            "2026-09-08T12:00:00+00:00",
            "An AI product update with no mathematics.",
            "ok",
        ),
    )
    conn.commit()
    conn.close()


class ParseNewsSearchQueryTests(unittest.TestCase):
    def test_quoted_title_strips_quotes_and_stopwords_from_extras(self) -> None:
        phrases, terms = parse_news_search_query(
            '"On the Navier–Stokes Millennium Prize Problem" '
            "Navier Stokes Millennium Prize Problem"
        )
        self.assertEqual(
            phrases, ["On the Navier–Stokes Millennium Prize Problem"]
        )
        self.assertIn("Navier", terms)
        self.assertNotIn("On", terms)
        self.assertNotIn("the", terms)
        self.assertFalse(any(term.startswith('"') or term.endswith('"') for term in phrases + terms))


class NewsSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "feeds.db"
        _seed_hub(self.db_path)
        self.ctx = {"db_path": str(self.db_path)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _titles(self, query: str) -> list[str]:
        result = news_search({"query": query, "limit": 10}, self.ctx)
        self.assertTrue(result["success"], result)
        return [item["title"] for item in result["data"]["items"]]

    def test_keyword_stuffed_query_finds_stored_article(self) -> None:
        titles = self._titles(
            "AI solved frontier mathematics recent theorem proof mathematical discovery"
        )
        self.assertIn("On the Navier–Stokes Millennium Prize Problem", titles)

    def test_quoted_title_finds_stored_article(self) -> None:
        titles = self._titles(
            '"On the Navier–Stokes Millennium Prize Problem" '
            "Navier Stokes Millennium Prize Problem"
        )
        self.assertEqual(
            titles, ["On the Navier–Stokes Millennium Prize Problem"]
        )

    def test_hyphen_matches_en_dash_title(self) -> None:
        titles = self._titles("Navier-Stokes")
        self.assertIn("On the Navier–Stokes Millennium Prize Problem", titles)

    def test_short_query_still_requires_all_terms(self) -> None:
        titles = self._titles("Navier Images")
        self.assertEqual(titles, [])


if __name__ == "__main__":
    unittest.main()
