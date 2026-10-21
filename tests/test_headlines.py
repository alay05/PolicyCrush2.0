import json
import os
import unittest
from unittest.mock import Mock, patch

from app import app
from headlines.generator import generate_headline_records, load_style_examples
from routes.saved_articles import prepare_article


class HeadlineGeneratorTests(unittest.TestCase):
    def test_stored_headlines_are_loaded_as_style_examples(self):
        examples = load_style_examples()

        self.assertGreater(len(examples), 50)
        self.assertIn("HHS Launches Kidney Care National Plan", examples)

    def test_structured_response_is_normalized_and_hearings_are_events(self):
        articles = [
            prepare_article(
                {
                    "title": "CMS original title",
                    "url": "https://example.com/cms",
                    "date": "2026-10-20",
                },
                "news",
                "CMS",
            ),
            prepare_article(
                {
                    "title": "Finance hearing original",
                    "url": "https://example.com/hearing",
                    "date": "2026-10-21T10:00:00",
                },
                "senate",
                "Finance",
                "hearing",
            ),
        ]
        api_payload = {
            "articles": [
                {
                    "id": articles[0]["id"],
                    "headline": "CMS Announces Policy Update",
                    "category": "Medicare",
                },
                {
                    "id": articles[1]["id"],
                    "headline": "Senate Finance Committee Holds Hearing",
                    "category": "Quality and Innovation",
                },
            ]
        }
        response = Mock(output_text=json.dumps(api_payload))
        client = Mock()
        client.responses.create.return_value = response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "headlines.generator.OpenAI", return_value=client
        ):
            generated = generate_headline_records(articles)

        self.assertEqual(generated[0]["category"], "Medicare")
        self.assertEqual(generated[1]["category"], "Events")
        request_args = client.responses.create.call_args.kwargs
        self.assertEqual(request_args["text"]["format"]["type"], "json_schema")
        self.assertFalse(request_args["store"])


class HeadlineWorkflowTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()
        self.article_one = prepare_article(
            {
                "title": "Original Medicare title",
                "url": "https://example.com/medicare",
                "date": "2026-10-20",
            },
            "news",
            "CMS",
        )
        self.article_two = prepare_article(
            {
                "title": "Original drug title",
                "url": "https://example.com/drug",
                "date": "2026-10-19",
            },
            "house",
            "Energy and Commerce",
            "majority",
        )
        with self.client.session_transaction() as current_session:
            current_session["saved_articles"] = [self.article_one, self.article_two]

    def _generate(self):
        generated = [
            {
                "id": self.article_one["id"],
                "headline": "CMS Updates Medicare Policy",
                "category": "Medicare",
            },
            {
                "id": self.article_two["id"],
                "headline": "House Committee Examines Drug Policy",
                "category": "Pharmaceuticals and Medical Devices",
            },
        ]
        with patch("headlines.routes.generate_headline_records", return_value=generated):
            return self.client.post("/headlines/generate", follow_redirects=True)

    def test_generate_renders_categorized_headlines_and_originals(self):
        response = self._generate()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Generated Headlines", response.data)
        self.assertIn(b"CMS Updates Medicare Policy", response.data)
        self.assertIn(b"Original: Original Medicare title", response.data)
        self.assertIn(b"Pharmaceuticals and Medical Devices", response.data)

    def test_headline_can_be_renamed_and_moved(self):
        self._generate()

        renamed = self.client.post(
            "/headlines/rename",
            json={"id": self.article_one["id"], "headline": "Edited Medicare Headline"},
        )
        moved = self.client.post(
            "/headlines/move",
            json={
                "id": self.article_one["id"],
                "from_category": "Medicare",
                "to_category": "Health Insurance",
                "new_index": 0,
            },
        )

        self.assertEqual(renamed.get_json(), {"ok": True})
        self.assertEqual(moved.get_json(), {"ok": True})
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertEqual(
                workflow["items"][self.article_one["id"]]["headline"],
                "Edited Medicare Headline",
            )
            self.assertNotIn(self.article_one["id"], workflow["index"]["Medicare"])
            self.assertEqual(workflow["index"]["Health Insurance"], [self.article_one["id"]])

    def test_clear_saved_also_clears_generated_workflow(self):
        self._generate()

        response = self.client.post("/saved-articles/clear", follow_redirects=True)

        self.assertIn(b"No articles have been saved yet.", response.data)
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session["saved_articles"], [])
            self.assertNotIn("headline_workflow", current_session)


if __name__ == "__main__":
    unittest.main()
