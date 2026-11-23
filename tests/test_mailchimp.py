from collections import OrderedDict
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from app import app
from config import Config
from headlines.state import ALL_CATEGORIES
from mailchimp.client import MailchimpAPIError, MailchimpClient
from mailchimp.renderer import render_main_newsletter, render_main_newsletter_sections
from routes.saved_articles import prepare_article


class MailchimpRendererTests(unittest.TestCase):
    def test_template_sections_match_full_newsletter_content(self):
        categories = {"Medicare": [{
            "headline": "CMS & HHS Update", "link_text": "Update",
            "url": "https://example.com/?a=1&b=2",
        }]}
        html, _ = render_main_newsletter(categories)
        soup = BeautifulSoup(html, "html.parser")
        sections = render_main_newsletter_sections(categories)
        self.assertEqual(set(sections), {"greeting", "body", "footnote"})
        for name, content in sections.items():
            with self.subTest(section=name):
                self.assertIn(content, html)
                self.assertEqual(
                    str(BeautifulSoup(content, "html.parser")),
                    soup.find(attrs={"mc:edit": name}).decode_contents(),
                )
        self.assertIn("CMS &amp; HHS", sections["body"])
        self.assertNotIn("<html", sections["body"])
        self.assertIn("[Add quote and attribution in Mailchimp]", sections["footnote"])

    def test_render_uses_policycrush_layout_content_links_and_merge_tags(self):
        categories = OrderedDict(
            [
                (
                    "Events",
                    [
                        {
                            "headline": "Finance Committee Holds Rural Health Hearing",
                            "link_text": "Holds",
                            "url": "https://example.com/hearing",
                            "date": "2026-10-28T10:00:00",
                        }
                    ],
                ),
                (
                    "Medicare",
                    [
                        {
                            "headline": "CMS Announces Medicare Update",
                            "link_text": "Announces",
                            "url": "https://example.com/medicare",
                        }
                    ],
                ),
                ("Medicaid", []),
            ]
        )

        html, content_hash = render_main_newsletter(categories)

        self.assertIn(">Calendar<", html)
        self.assertIn("<strong>10:00AM</strong> -", html)
        self.assertIn(
            'CMS <a href="https://example.com/medicare" target="_blank" '
            'style="color:#0d92da;text-decoration:none;">Announces</a> Medicare Update',
            html,
        )
        self.assertNotIn(">Medicaid<", html)
        self.assertIn("[Add quote and attribution in Mailchimp]", html)
        self.assertIn("*|UNSUB|*", html)
        self.assertIn("*|LIST:ADDRESS|*", html)
        self.assertIn("5006abcd-2000-4934-bfd2-919dc85b5a7f.gif", html)
        self.assertNotIn("list-manage.com/unsubscribe?", html)
        self.assertEqual(len(content_hash), 64)

    def test_invalid_link_text_falls_back_to_linking_the_full_escaped_headline(self):
        html, _ = render_main_newsletter(
            OrderedDict(
                [
                    (
                        "Medicare",
                        [
                            {
                                "headline": "CMS & HHS Update",
                                "link_text": "Missing",
                                "url": "https://example.com/?a=1&b=2",
                            }
                        ],
                    )
                ]
            )
        )

        self.assertIn(
            'href="https://example.com/?a=1&amp;b=2"',
            html,
        )
        self.assertIn(">CMS &amp; HHS Update</a>", html)


class MailchimpClientTests(unittest.TestCase):
    def setUp(self):
        template_patch = patch.object(Config, "MAILCHIMP_TEMPLATE_ID", "1234")
        template_patch.start()
        self.addCleanup(template_patch.stop)

    @patch("mailchimp.client.requests.request")
    def test_create_campaign_leaves_campaign_fields_blank(self, request_mock):
        response = Mock(ok=True, content=b"{}")
        response.json.return_value = {"id": "campaign-1", "web_id": 123}
        request_mock.return_value = response

        client = MailchimpClient("secret-us4")
        result = client.create_campaign()

        self.assertEqual(result["id"], "campaign-1")
        request_mock.assert_called_once_with(
            "POST",
            "https://us4.api.mailchimp.com/3.0/campaigns",
            headers={
                "Authorization": "Bearer secret-us4",
                "Content-Type": "application/json",
            },
            json={"type": "regular", "content_type": "template", "settings": {"template_id": 1234}},
            timeout=Config.HTTP_TIMEOUT_SECONDS,
        )

    def test_api_key_requires_data_center_suffix(self):
        with self.assertRaisesRegex(MailchimpAPIError, "data center suffix"):
            MailchimpClient("invalid-key-")

    def test_template_id_must_be_positive(self):
        for template_id in ("", "no-id", "0", "-1"):
            with self.subTest(template_id=template_id):
                with self.assertRaisesRegex(MailchimpAPIError, "positive template ID"):
                    MailchimpClient("secret-us4", template_id=template_id)

    @patch("mailchimp.client.requests.request")
    def test_upload_uses_template_sections_instead_of_raw_html(self, request_mock):
        response = Mock(ok=True, content=b"{}")
        response.json.return_value = {}
        request_mock.return_value = response
        sections = {"body": "<p>Headline</p>", "greeting": "Hello", "footnote": "Quote"}
        MailchimpClient("secret-us4").set_campaign_content("campaign-1", sections)
        self.assertEqual(request_mock.call_args.args, (
            "PUT", "https://us4.api.mailchimp.com/3.0/campaigns/campaign-1/content",
        ))
        self.assertEqual(request_mock.call_args.kwargs["json"], {
            "template": {"id": 1234, "sections": sections},
        })

    @patch.object(MailchimpClient, "_request")
    def test_template_validation_requires_all_editable_regions(self, request_mock):
        request_mock.return_value = {"sections": {"body": ""}}
        with self.assertRaisesRegex(MailchimpAPIError, "footnote, greeting"):
            MailchimpClient("secret-us4").validate_template()
        request_mock.assert_called_once_with("GET", "/templates/1234/default-content")
        request_mock.return_value = {"sections": {"body": "", "greeting": "", "footnote": ""}}
        MailchimpClient("secret-us4").validate_template()


class MailchimpWorkflowTests(unittest.TestCase):
    def setUp(self):
        template_patch = patch.object(Config, "MAILCHIMP_TEMPLATE_ID", "1234")
        template_patch.start()
        self.addCleanup(template_patch.stop)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()
        self.article = prepare_article(
            {
                "title": "Original Medicare title",
                "url": "https://example.com/medicare",
                "date": "2026-10-27",
            },
            "news",
            "CMS",
        )
        item = {
            **self.article,
            "original_title": self.article["title"],
            "headline": "CMS Announces Medicare Update",
            "link_text": "Announces",
        }
        index = {category: [] for category in ALL_CATEGORIES}
        index["Medicare"] = [self.article["id"]]
        with self.client.session_transaction() as current_session:
            current_session["saved_articles"] = [self.article]
            current_session["headline_workflow"] = {
                "built_at": "2026-10-27T09:00:00",
                "items": {self.article["id"]: item},
                "index": index,
            }

    def test_create_draft_uploads_sections_stores_state_and_redirects_to_editor(self):
        mailchimp = Mock()
        mailchimp.create_campaign.return_value = {
            "id": "campaign-1",
            "web_id": 123,
        }
        mailchimp.editor_url.return_value = (
            "https://us4.admin.mailchimp.com/campaigns/show/?id=123"
        )

        with patch.object(Config, "MAILCHIMP_API_KEY", "secret-us4"), patch(
            "headlines.routes.MailchimpClient", return_value=mailchimp
        ):
            response = self.client.post("/headlines/mailchimp")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location,
            "https://us4.admin.mailchimp.com/campaigns/show/?id=123",
        )
        mailchimp.create_campaign.assert_called_once_with()
        mailchimp.validate_template.assert_called_once_with()
        mailchimp.set_campaign_content.assert_called_once()
        campaign_id, sections = mailchimp.set_campaign_content.call_args.args
        self.assertEqual(campaign_id, "campaign-1")
        self.assertIn(">Announces</a> Medicare Update", sections["body"])
        self.assertIn("[Add quote and attribution in Mailchimp]", sections["footnote"])

        with self.client.session_transaction() as current_session:
            draft = current_session["headline_workflow"]["mailchimp_draft"]
        self.assertEqual(draft["campaign_id"], "campaign-1")
        self.assertEqual(draft["template_id"], "1234")
        self.assertEqual(len(draft["content_hash"]), 64)
        self.assertFalse(draft["incomplete"])

    def test_edited_content_updates_same_saved_draft_after_confirmation(self):
        create_client = Mock()
        create_client.create_campaign.return_value = {
            "id": "campaign-1",
            "web_id": 123,
        }
        create_client.editor_url.return_value = (
            "https://us4.admin.mailchimp.com/campaigns/show/?id=123"
        )
        with patch.object(Config, "MAILCHIMP_API_KEY", "secret-us4"), patch(
            "headlines.routes.MailchimpClient", return_value=create_client
        ):
            self.client.post("/headlines/mailchimp")

        self.client.post(
            "/headlines/rename",
            json={"id": self.article["id"], "headline": "Edited Medicare Headline"},
        )

        with patch.object(Config, "MAILCHIMP_API_KEY", "secret-us4"):
            review = self.client.get("/headlines")
        self.assertIn(b"Update Mailchimp Draft", review.data)

        update_client = Mock()
        update_client.get_campaign.return_value = {"status": "save"}
        with patch.object(Config, "MAILCHIMP_API_KEY", "secret-us4"), patch(
            "headlines.routes.MailchimpClient", return_value=update_client
        ):
            response = self.client.post(
                "/headlines/mailchimp",
                data={"confirm": "1"},
            )

        self.assertEqual(response.status_code, 302)
        update_client.get_campaign.assert_called_once_with("campaign-1")
        update_client.create_campaign.assert_not_called()
        update_client.set_campaign_content.assert_called_once()
        self.assertIn(
            "Edited Medicare Headline",
            update_client.set_campaign_content.call_args.args[1]["body"],
        )

    def _seed_existing_draft(self, template_id=None):
        with self.client.session_transaction() as current_session:
            workflow = current_session["headline_workflow"]
            _, content_hash = render_main_newsletter({
                "Medicare": [workflow["items"][self.article["id"]]],
            })
            workflow["mailchimp_draft"] = {
                "campaign_id": "campaign-1", "content_hash": content_hash,
                "editor_url": "https://us4.admin.mailchimp.com/campaigns/show/?id=123",
                "template_id": template_id,
            }
            current_session["headline_workflow"] = workflow

    @patch("headlines.routes.MailchimpClient")
    def test_legacy_html_draft_needs_confirmation_to_become_editable(self, client_class):
        self._seed_existing_draft()
        self.assertIn(b"Update Mailchimp Draft", self.client.get("/headlines").data)
        client = client_class.return_value
        self.client.post("/headlines/mailchimp")
        client.set_campaign_content.assert_not_called()
        client.get_campaign.return_value = {"status": "save"}
        self.client.post("/headlines/mailchimp", data={"confirm": "1"})
        client.create_campaign.assert_not_called()
        client.set_campaign_content.assert_called_once()
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session["headline_workflow"]["mailchimp_draft"]["template_id"], "1234")

    @patch("headlines.routes.MailchimpClient")
    def test_unchanged_draft_does_not_overwrite_mailchimp_edits(self, client_class):
        self._seed_existing_draft(template_id="1234")
        client = client_class.return_value
        client.get_campaign.return_value = {"status": "save"}
        response = self.client.post("/headlines/mailchimp")
        self.assertIn("admin.mailchimp.com", response.location)
        client.set_campaign_content.assert_not_called()

    @patch("headlines.routes.MailchimpClient")
    def test_scheduled_campaign_cannot_be_overwritten(self, client_class):
        self._seed_existing_draft()
        client = client_class.return_value
        client.get_campaign.return_value = {"status": "schedule"}
        self.client.post("/headlines/mailchimp", data={"confirm": "1"})
        client.set_campaign_content.assert_not_called()

    @patch("headlines.routes.MailchimpClient")
    def test_invalid_template_does_not_create_empty_campaign(self, client_class):
        client = client_class.return_value
        client.validate_template.side_effect = MailchimpAPIError("Missing editable sections")
        self.client.post("/headlines/mailchimp")
        client.create_campaign.assert_not_called()
        client.set_campaign_content.assert_not_called()

    @patch("headlines.routes.MailchimpClient")
    def test_failed_upload_can_retry_same_draft(self, client_class):
        client = client_class.return_value
        client.create_campaign.return_value = {"id": "campaign-1"}
        client.set_campaign_content.side_effect = MailchimpAPIError("Upload failed")
        self.client.post("/headlines/mailchimp")
        with self.client.session_transaction() as current_session:
            self.assertTrue(current_session["headline_workflow"]["mailchimp_draft"]["incomplete"])
        client.get_campaign.return_value = {"status": "save"}
        client.set_campaign_content.side_effect = None
        self.client.post("/headlines/mailchimp", data={"confirm": "1"})
        client.create_campaign.assert_called_once()
        with self.client.session_transaction() as current_session:
            self.assertFalse(current_session["headline_workflow"]["mailchimp_draft"]["incomplete"])

    def test_missing_template_disables_draft_action(self):
        with patch.object(Config, "MAILCHIMP_API_KEY", "secret-us4"), patch.object(Config, "MAILCHIMP_TEMPLATE_ID", ""):
            response = self.client.get("/headlines")
        self.assertIn(b"Mailchimp Not Configured", response.data)

    def test_unconfigured_account_disables_draft_action(self):
        with patch.object(Config, "MAILCHIMP_API_KEY", ""):
            response = self.client.get("/headlines")

        self.assertIn(b"Mailchimp Not Configured", response.data)
        self.assertNotIn(b"Create Mailchimp Draft", response.data)


if __name__ == "__main__":
    unittest.main()
