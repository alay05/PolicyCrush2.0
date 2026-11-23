import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from app import app
from config import Config
from features.calendar_pull import _shape_event
from mailchimp.client import MailchimpAPIError
from mailchimp.renderer import render_w2w4_newsletter, render_w2w4_newsletter_sections
from routes.add_event_pull import _event_minimal


def event_record():
    return _event_minimal(_shape_event({
        "id": "evt-1", "title": "CMS & HHS <Update>",
        "datetime_start": "2026-07-15 09:30:00",
        "datetime_end": "2026-07-15 10:30:00",
        "timezone": "America/Los_Angeles",
        "description": "https://example.com/details?a=1&b=2",
        "event_url": "https://www.addevent.com/event/example?a=1&b=2",
    }))


class W2W4RendererTests(unittest.TestCase):
    def test_shared_shell_editable_sections_and_distinct_event_links(self):
        event = event_record()
        event["headline"] = f'{event["title"]} — {event["date_label"]} · {event["time_label"]}'
        categories = {"Medicare": [event], "Medicaid": []}
        html, content_hash = render_w2w4_newsletter(categories)
        soup = BeautifulSoup(html, "html.parser")
        sections = render_w2w4_newsletter_sections(categories)
        self.assertEqual(set(sections), {"greeting", "body", "footnote"})
        for name, content in sections.items():
            self.assertEqual(
                str(BeautifulSoup(content, "html.parser")),
                soup.find(attrs={"mc:edit": name}).decode_contents(),
            )
        body = BeautifulSoup(sections["body"], "html.parser")
        links = body.find_all("a")
        self.assertEqual(links[0]["href"], event["url"])
        self.assertEqual(links[0].text, event["title"])
        self.assertEqual(links[1]["href"], "https://www.addevent.com/event/example+outlook?a=1&b=2")
        self.assertEqual(links[1].text, "Add to Calendar")
        self.assertEqual(body.get_text().count("12:30PM EDT"), 1)
        self.assertNotIn("1:30", body.get_text())
        self.assertEqual(body.get_text().count("7/15 -"), 1)
        self.assertNotIn("Wed, Jul 15, 2026", body.get_text())
        self.assertIsNone(body.find("update"))
        self.assertNotIn("Medicaid", body.get_text())
        self.assertIn("Here’s a look at the next week’s health related events...",
                      BeautifulSoup(sections["greeting"], "html.parser").get_text())
        self.assertNotIn("QUOTE OF THE DAY", html)
        self.assertNotIn("[Add quote", html)
        self.assertEqual(BeautifulSoup(sections["footnote"], "html.parser").get_text().strip(), "")
        self.assertIn("table#policycrush-email tr.footnote td", sections["footnote"])
        self.assertIn("display:none !important", sections["footnote"])
        self.assertIn("padding:0 !important", sections["footnote"])
        self.assertIn("*|UNSUB|*", html)
        self.assertIn("*|LIST:ADDRESS|*", html)
        self.assertIsNotNone(soup.select_one("#policycrush-logo"))
        self.assertEqual(len(content_hash), 64)

    def test_all_day_and_overnight_events_display_start_time(self):
        for raw, expected in [
            ({"datetime_start": "2026-01-21", "all_day_event": True}, "All day"),
            ({"datetime_start": "2026-01-21 23:00:00", "datetime_end": "2026-01-22 01:00:00"},
             "11:00PM EST"),
        ]:
            with self.subTest(expected=expected):
                event = _event_minimal(_shape_event({
                    "id": "evt-2", "title": "Policy event", "timezone": "America/New_York", **raw,
                }))
                event["headline"] = "Edited Event"
                sections = render_w2w4_newsletter_sections({"Medicare": [event]})
                self.assertIn(expected, sections["body"])
                self.assertIn("Edited Event", sections["body"])

    def test_calendar_link_changes_content_hash(self):
        event = {**event_record(), "headline": "Briefing"}
        _, before = render_w2w4_newsletter({"Medicare": [event]})
        event["addevent_url"] = "https://www.addevent.com/event/updated"
        _, after = render_w2w4_newsletter({"Medicare": [event]})
        self.assertNotEqual(before, after)

    def test_reference_format_and_spacing_for_multiple_events(self):
        events = []
        for headline, day, time, slug in (
            ("Senate Judiciary Committee Hearing on Drug Costs", 17, "10:00", "pdt1f2dyqpcb"),
            ("Senate HELP Committee Meeting to Vote on FDA Commissioner", 18, "09:45", "xx4kz8fbk7yr"),
            ("PYA Webinar on CY27 Final Rules", 18, "11:00", "rpwfxt8x7sjx"),
        ):
            event = _event_minimal(_shape_event({
                "id": slug, "title": headline,
                "datetime_start": f"2026-11-{day} {time}:00",
                "timezone": "America/New_York",
                "description": "https://example.com/details",
                "event_url": f"https://www.addevent.com/event/{slug}",
            }))
            event["headline"] = f'{headline} — {event["date_label"]} · {event["time_label"]}'
            events.append(event)
        sections = render_w2w4_newsletter_sections({"Congress and the Administration": events})
        body = BeautifulSoup(sections["body"], "html.parser")
        self.assertEqual(len(body.find_all("p")), 1)
        self.assertEqual([tag.get_text() for tag in body.find_all("strong")], [
            "11/17 - Senate Judiciary Committee Hrg on Drug Costs",
            "11/18 - Senate HELP Committee Mtg to Vote on FDA Commissioner",
            "11/18 - PYA Webinar on CY27 Final Rules",
        ])
        self.assertEqual([tag.get_text() for tag in body.select("strong a")], ["Hrg", "Mtg", "Webinar"])
        for strong in body.find_all("strong"):
            self.assertEqual(strong.find_next_sibling().name, "br")
            self.assertEqual(strong.find_next_sibling().find_next_sibling().name, "br")
        for time in ("10:00AM EST", "9:45AM EST", "11:00AM EST"):
            self.assertIn(time + " - ", body.get_text())
        self.assertTrue(all(a["href"].endswith("+outlook") for a in body.find_all("a", string="Add to Calendar")))

    def test_calendar_suffix_preserves_query_fragment_and_other_urls(self):
        for url, expected in (
            ("https://www.addevent.com/event/abc+outlook", "https://www.addevent.com/event/abc+outlook"),
            ("https://addevent.com/event/abc+google/?x=1#details", "https://addevent.com/event/abc+outlook?x=1#details"),
            ("https://example.com/event/abc", "https://example.com/event/abc"),
            ("https://example.com/evt-1.ics", "https://example.com/evt-1.ics"),
        ):
            with self.subTest(url=url):
                event = {**event_record(), "headline": "Briefing", "addevent_url": url}
                sections = render_w2w4_newsletter_sections({"Medicare": [event]})
                link = BeautifulSoup(sections["body"], "html.parser").find("a", string="Add to Calendar")
                self.assertEqual(link["href"], expected)

    def test_long_registration_link_survives_saving_and_rendering(self):
        url = "https://example.com/register?eid=77217&token=" + "a" * 400
        event = _event_minimal(_shape_event({
            "id": "evt-long", "title": "AHIP Webinar", "description": url,
            "datetime_start": "2026-11-17 12:00:00", "timezone": "America/New_York",
        }))
        event["headline"] = "AHIP Webinar on Scaling AI Adoption"
        sections = render_w2w4_newsletter_sections({"Health Tech": [event]})
        link = BeautifulSoup(sections["body"], "html.parser").select_one("strong a")
        self.assertEqual(link["href"], url)
        self.assertEqual(link.get_text(), "Webinar")

    def test_missing_schedule_and_existing_link_text_are_preserved(self):
        sections = render_w2w4_newsletter_sections({"Medicare": [{
            "headline": "CMS Announces a Webinar", "link_text": "Announces",
            "url": "https://example.com", "date_label": "Date unavailable",
            "time_label": "Time unavailable",
        }]})
        body = BeautifulSoup(sections["body"], "html.parser")
        self.assertEqual(body.select_one("strong a").text, "Announces")
        self.assertIn("Date unavailable", body.get_text())
        self.assertIn("Time unavailable", body.get_text())


class W2W4MailchimpWorkflowTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="w2w4-mailchimp-test")
        self.client = app.test_client()
        self.event = event_record()
        for name, value in (("MAILCHIMP_API_KEY", "secret-us4"), ("MAILCHIMP_TEMPLATE_ID", "1234")):
            patcher = patch.object(Config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("routes.add_event_pull.MailchimpClient")
        self.mailchimp = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.mailchimp.create_campaign.return_value = {"id": "w2w4-campaign", "web_id": 123}
        self.mailchimp.editor_url.return_value = "https://us4.admin.mailchimp.com/campaigns/show/?id=123"
        self.mailchimp.get_campaign.return_value = {"status": "save"}
        with self.client.session_transaction() as state:
            state["addevent_pulled"] = [self.event]
            state["addevent_categories_cache"] = {
                "items": {"evt-1": {**self.event, "headline": "CMS Briefing"}},
                "index": {"Medicare": ["evt-1"]},
            }
            state["headline_workflow"] = {"mailchimp_draft": {"campaign_id": "main-campaign"}}

    def draft(self):
        with self.client.session_transaction() as state:
            return state["addevent_categories_cache"]["mailchimp_draft"]

    def create(self, **data):
        return self.client.post("/add-event-pull/mailchimp", data=data)

    def test_create_editable_draft_keeps_main_workflow_separate(self):
        review = self.client.get("/add-event-pull/review")
        self.assertIn(b"Create Mailchimp Draft", review.data)
        self.assertIn(b'action="/add-event-pull/mailchimp"', review.data)
        response = self.create()
        self.assertEqual(response.location, self.mailchimp.editor_url.return_value)
        self.mailchimp.create_campaign.assert_called_once_with()
        self.mailchimp.validate_template.assert_called_once_with()
        campaign_id, sections = self.mailchimp.set_campaign_content.call_args.args
        self.assertEqual(campaign_id, "w2w4-campaign")
        self.assertEqual(set(sections), {"greeting", "body", "footnote"})
        self.assertIn("Add to Calendar", sections["body"])
        self.assertEqual(self.draft()["template_id"], "1234")
        self.assertFalse(self.draft()["incomplete"])
        with self.client.session_transaction() as state:
            self.assertEqual(state["headline_workflow"]["mailchimp_draft"], {"campaign_id": "main-campaign"})

    def test_unchanged_draft_opens_without_overwriting_mailchimp_edits(self):
        self.create()
        response = self.create()
        self.assertEqual(response.location, self.mailchimp.editor_url.return_value)
        self.mailchimp.create_campaign.assert_called_once()
        self.mailchimp.set_campaign_content.assert_called_once()

    def test_rename_and_move_require_confirmation_then_update_same_draft(self):
        self.create()
        self.client.post("/add-event-pull/rename-headline", json={"id": "evt-1", "headline": "Edited Briefing"})
        self.client.post("/add-event-pull/move-article", json={
            "id": "evt-1", "from_category": "Medicare", "to_category": "Medicaid", "new_index": 0,
        })
        self.create()
        self.mailchimp.set_campaign_content.assert_called_once()
        self.create(confirm="1")
        self.mailchimp.create_campaign.assert_called_once()
        self.assertEqual(self.mailchimp.set_campaign_content.call_count, 2)
        body = self.mailchimp.set_campaign_content.call_args.args[1]["body"]
        self.assertIn("Edited Briefing", BeautifulSoup(body, "html.parser").get_text())
        self.assertIn("<h1>Medicaid</h1>", body)
        self.assertNotIn("<h1>Medicare</h1>", body)

    def test_new_headlines_preserve_draft_and_pending_events_block_upload(self):
        self.create()
        with self.client.session_transaction() as state:
            state["addevent_pulled"].append({**self.event, "id": "evt-2"})
        self.create()
        self.mailchimp.set_campaign_content.assert_called_once()
        self.assertNotIn(b"Create Mailchimp Draft", self.client.get("/add-event-pull/review").data)
        with patch("routes.add_event_pull.generate_event_headline_records", return_value=[{
            "id": "evt-2", "headline": "Second Briefing", "category": "Medicaid",
        }]):
            self.client.post("/add-event-pull/generate-headlines")
        self.assertEqual(self.draft()["campaign_id"], "w2w4-campaign")
        self.create(confirm="1")
        self.mailchimp.create_campaign.assert_called_once()
        body = self.mailchimp.set_campaign_content.call_args.args[1]["body"]
        self.assertIn("Second Briefing", BeautifulSoup(body, "html.parser").get_text())

    def test_no_generated_events_blocks_draft_creation(self):
        with self.client.session_transaction() as state:
            state.pop("addevent_categories_cache")
        self.assertEqual(self.create().location, "/add-event-pull")
        self.mailchimp.create_campaign.assert_not_called()

    def test_failed_content_upload_retries_same_campaign(self):
        self.mailchimp.set_campaign_content.side_effect = MailchimpAPIError("Upload failed")
        self.create()
        self.assertTrue(self.draft()["incomplete"])
        self.mailchimp.set_campaign_content.side_effect = None
        self.create(confirm="1")
        self.mailchimp.create_campaign.assert_called_once()
        self.assertFalse(self.draft()["incomplete"])

    def test_non_drafts_and_deleted_campaigns_require_explicit_replacement(self):
        self.create()
        for status in ("sent", "schedule", "deleted"):
            with self.subTest(status=status):
                self.mailchimp.get_campaign.return_value = {"status": status}
                self.mailchimp.get_campaign.side_effect = (
                    MailchimpAPIError("Missing", status_code=404) if status == "deleted" else None
                )
                uploads = self.mailchimp.set_campaign_content.call_count
                creates = self.mailchimp.create_campaign.call_count
                self.create()
                self.assertTrue(self.draft()["unavailable"])
                self.create()
                self.assertEqual(self.mailchimp.set_campaign_content.call_count, uploads)
                self.assertEqual(self.mailchimp.create_campaign.call_count, creates)
                self.create(create_replacement="1")
                self.assertEqual(self.mailchimp.create_campaign.call_count, creates + 1)
                self.assertFalse(self.draft()["unavailable"])

    def test_missing_config_disables_button(self):
        with patch.object(Config, "MAILCHIMP_API_KEY", ""):
            self.assertIn(b"Mailchimp Not Configured", self.client.get("/add-event-pull/review").data)

    def test_missing_calendar_landing_page_uses_absolute_ics_link(self):
        with self.client.session_transaction() as state:
            state["addevent_pulled"][0].pop("addevent_url")
            state["addevent_categories_cache"]["items"]["evt-1"].pop("addevent_url")
        self.create()
        body = self.mailchimp.set_campaign_content.call_args.args[1]["body"]
        self.assertIn('href="http://localhost/add-event-pull/ics/evt-1.ics"', body)


if __name__ == "__main__":
    unittest.main()
