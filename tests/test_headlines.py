import json
import os
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from app import app
from bs4 import BeautifulSoup
from headlines.routes import _workflow_categories
from mailchimp.renderer import render_main_newsletter, render_main_newsletter_sections
from headlines.generator import (
    generate_event_headline_records,
    generate_headline_records,
    load_style_examples,
)
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
                    "link_text": "Announces",
                    "category": "Medicare",
                },
                {
                    "id": articles[1]["id"],
                    "headline": "Senate Finance Committee Holds Hearing",
                    "link_text": "Holds",
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
        self.assertEqual(generated[0]["link_text"], "Announces")
        self.assertEqual(generated[1]["category"], "Events")
        request_args = client.responses.create.call_args.kwargs
        self.assertEqual(request_args["text"]["format"]["type"], "json_schema")
        article_schema = request_args["text"]["format"]["schema"]["properties"][
            "articles"
        ]["items"]
        self.assertIn("link_text", article_schema["properties"])
        self.assertIn("link_text", article_schema["required"])
        self.assertFalse(request_args["store"])

    def test_w2w_headlines_are_simple_categorized_and_include_exact_schedule(self):
        events = [
            {
                "id": "event-1",
                "title": "Committee on Finance Hearing on Rural Health Care",
                "date_label": "Wed, Oct 28, 2026",
                "time_label": "10:00 AM EDT – 12:00 PM EDT",
                "location": "Room 215, Dirksen Senate Office Building",
            }
        ]
        response = Mock(
            output_text=json.dumps(
                {
                    "articles": [
                        {
                            "id": "event-1",
                            "headline": "Senate Finance Committee Hearing on Rural Health Care",
                            "category": "Medicare",
                        }
                    ]
                }
            )
        )
        client = Mock()
        client.responses.create.return_value = response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "headlines.generator.OpenAI", return_value=client
        ):
            generated = generate_event_headline_records(events)

        self.assertEqual(generated[0]["category"], "Medicare")
        self.assertEqual(
            generated[0]["headline"],
            "Senate Finance Committee Hearing on Rural Health Care — "
            "Wed, Oct 28, 2026 · 10:00 AM EDT – 12:00 PM EDT",
        )
        request_args = client.responses.create.call_args.kwargs
        self.assertNotIn(
            "Events", request_args["text"]["format"]["schema"]["properties"]
            ["articles"]["items"]["properties"]["category"]["enum"]
        )
        self.assertIn("simple, literal headlines", request_args["instructions"])


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
        self.assertIn("Main Newsletter — Finalize".encode(), response.data)
        self.assertNotIn(b">Generated Headlines<", response.data)
        self.assertIn(b"CMS Updates Medicare Policy", response.data)
        self.assertIn(b"Original: Original Medicare title", response.data)
        self.assertIn(b"Pharmaceuticals and Medical Devices", response.data)
        self.assertNotIn(b"Regenerate", response.data)
        self.assertNotIn(b"Save PDF", response.data)

        saved_page = self.client.get("/saved-articles")
        self.assertIn(b"View Generated Headlines", saved_page.data)
        self.assertNotIn(b"Generate Headlines", saved_page.data)

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
            self.assertEqual(
                workflow["items"][self.article_one["id"]]["link_text"],
                "Edited Medicare Headline",
            )
            self.assertNotIn(self.article_one["id"], workflow["index"]["Medicare"])
            self.assertEqual(workflow["index"]["Health Insurance"], [self.article_one["id"]])

    def test_only_newly_saved_articles_are_generated(self):
        self._generate()
        self.client.post(
            "/headlines/rename",
            json={"id": self.article_one["id"], "headline": "Keep This Edited Headline"},
        )
        self.client.post(
            "/headlines/move",
            json={
                "id": self.article_one["id"],
                "from_category": "Medicare",
                "to_category": "Health Insurance",
                "new_index": 0,
            },
        )

        new_article = prepare_article(
            {
                "title": "New Medicaid title",
                "url": "https://example.com/medicaid",
                "date": "2026-10-21",
            },
            "news",
            "HHS",
        )
        with self.client.session_transaction() as current_session:
            current_session["saved_articles"].append(new_article)

        saved_page = self.client.get("/saved-articles")
        self.assertIn(b"View Generated Headlines", saved_page.data)
        self.assertIn(b"Generate 1 New Headline", saved_page.data)

        generated = [
            {
                "id": new_article["id"],
                "headline": "HHS Announces Medicaid Update",
                "category": "Medicaid",
            }
        ]
        with patch(
            "headlines.routes.generate_headline_records", return_value=generated
        ) as generate_mock:
            response = self.client.post("/headlines/generate", follow_redirects=True)

        requested_articles = generate_mock.call_args.args[0]
        self.assertEqual([article["id"] for article in requested_articles], [new_article["id"]])
        self.assertIn(b"HHS Announces Medicaid Update", response.data)
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertEqual(
                workflow["items"][self.article_one["id"]]["headline"],
                "Keep This Edited Headline",
            )
            self.assertEqual(workflow["index"]["Health Insurance"], [self.article_one["id"]])
            self.assertEqual(workflow["index"]["Medicaid"], [new_article["id"]])

    def test_clear_saved_also_clears_generated_workflow(self):
        self._generate()

        response = self.client.post("/saved-articles/clear", follow_redirects=True)

        self.assertIn(b"No articles have been saved yet.", response.data)
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session["saved_articles"], [])
            self.assertNotIn("headline_workflow", current_session)

    def _attach(self):
        return self.client.post("/headlines/move", json={
            "id": self.article_two["id"], "parent_id": self.article_one["id"],
            "to_category": "Medicare", "new_index": 0,
        })

    def test_attach_preserves_records_and_renders_one_linked_bullet(self):
        self._generate()
        with self.client.session_transaction() as current_session:
            before = deepcopy(current_session["headline_workflow"])
        self.assertEqual(self._attach().get_json(), {"ok": True})
        response = self.client.get("/headlines")
        soup = BeautifulSoup(response.data, "html.parser")
        parent = soup.select_one(f'.headline-group[data-id="{self.article_one["id"]}"]')
        self.assertEqual(parent.select_one('.headline-children .article-title').text,
                         "House Committee Examines Drug Policy")
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertEqual(workflow["items"], before["items"])
            self.assertEqual(workflow["parents"], {self.article_two["id"]: self.article_one["id"]})
            categories = _workflow_categories(workflow)
        html, new_hash = render_main_newsletter(categories)
        self.assertNotEqual(new_hash, render_main_newsletter(_workflow_categories(before))[1])
        body = render_main_newsletter_sections(categories)["body"]
        self.assertIn(body, html)
        email = BeautifulSoup(body, "html.parser")
        self.assertEqual(len(email.select('li')), 1)
        self.assertEqual(email.li.get_text(strip=True), "House Committee Examines Drug Policy")
        self.assertEqual(email.li.a['href'], self.article_two['url'])
        self.assertIn('list-style-type:disc', email.ul['style'])
        self.assertEqual(len(email.select('p')), 1)

    def test_parent_moves_with_children_and_child_can_detach(self):
        self._generate()
        self._attach()
        self.client.post("/headlines/move", json={
            "id": self.article_one["id"], "to_category": "Health Insurance", "new_index": 0,
        })
        self.client.get("/headlines")
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertEqual(workflow['index']['Health Insurance'], [self.article_one['id'], self.article_two['id']])
            self.assertEqual(workflow['index']['Medicare'], [])
            self.assertEqual(workflow['parents'][self.article_two['id']], self.article_one['id'])
        self.client.post("/headlines/move", json={
            "id": self.article_two["id"], "to_category": "Medicaid", "new_index": 0,
        })
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertEqual(workflow['parents'], {})
            self.assertEqual(workflow['index']['Medicaid'], [self.article_two['id']])

    def test_invalid_nesting_does_not_change_workflow(self):
        self._generate()
        self._attach()
        with self.client.session_transaction() as current_session:
            before = deepcopy(current_session["headline_workflow"])
        for article, parent in [(self.article_one['id'], self.article_two['id']),
                                (self.article_one['id'], self.article_one['id']),
                                (self.article_two['id'], 'missing')]:
            response = self.client.post('/headlines/move', json={
                'id': article, 'parent_id': parent, 'to_category': 'Medicare', 'new_index': 0,
            })
            self.assertEqual(response.status_code, 400)
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session['headline_workflow'], before)

    def test_removing_parent_promotes_children_and_removing_child_cleans_attachment(self):
        for remove_parent in (True, False):
            with self.subTest(remove_parent=remove_parent):
                self.setUp()
                self._generate()
                self._attach()
                removed = self.article_one if remove_parent else self.article_two
                remaining = self.article_two if remove_parent else self.article_one
                self.client.post(f"/saved-articles/{removed['id']}/remove")
                self.client.get('/headlines')
                with self.client.session_transaction() as current_session:
                    workflow = current_session['headline_workflow']
                    self.assertEqual(workflow['parents'], {})
                    self.assertEqual(workflow['index']['Medicare'], [remaining['id']])

    def test_new_generation_keeps_attachments_and_subarticle_edits(self):
        self._generate()
        self._attach()
        self.client.post('/headlines/rename', json={'id': self.article_two['id'], 'headline': 'Edited child'})
        new_article = prepare_article({'title': 'Third', 'url': 'https://example.com/third'}, 'news', 'CMS')
        with self.client.session_transaction() as current_session:
            current_session['saved_articles'].append(new_article)
        with patch('headlines.routes.generate_headline_records', return_value=[{
            'id': new_article['id'], 'headline': 'New headline', 'category': 'Medicare',
        }]):
            self.client.post('/headlines/generate')
        with self.client.session_transaction() as current_session:
            workflow = current_session['headline_workflow']
            self.assertEqual(workflow['parents'], {self.article_two['id']: self.article_one['id']})
            self.assertEqual(workflow['items'][self.article_two['id']]['headline'], 'Edited child')

    def test_multiple_children_reorder_and_detach_at_root_position(self):
        self._generate()
        third = prepare_article({'title': 'Third', 'url': 'https://example.com/third'}, 'news', 'CMS')
        with self.client.session_transaction() as current_session:
            current_session['saved_articles'].append(third)
            workflow = current_session['headline_workflow']
            workflow['items'][third['id']] = {**third, 'headline': 'Third headline'}
            workflow['index']['Medicare'].append(third['id'])
        self._attach()
        self.client.post('/headlines/move', json={
            'id': third['id'], 'parent_id': self.article_one['id'], 'to_category': 'Medicare', 'new_index': 0,
        })
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session['headline_workflow']['index']['Medicare'],
                             [self.article_one['id'], third['id'], self.article_two['id']])
        self.client.post('/headlines/move', json={
            'id': third['id'], 'to_category': 'Medicare', 'new_index': 1,
        })
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session['headline_workflow']['index']['Medicare'],
                             [self.article_one['id'], self.article_two['id'], third['id']])

    def test_removing_saved_article_prunes_only_its_generated_headline(self):
        self._generate()

        self.client.post(f"/saved-articles/{self.article_one['id']}/remove")

        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            self.assertNotIn(self.article_one["id"], workflow["items"])
            self.assertIn(self.article_two["id"], workflow["items"])
            self.assertNotIn(self.article_one["id"], workflow["index"]["Medicare"])
            self.assertEqual(
                workflow["index"]["Pharmaceuticals and Medical Devices"],
                [self.article_two["id"]],
            )


if __name__ == "__main__":
    unittest.main()
