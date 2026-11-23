import unittest
from copy import deepcopy
from unittest.mock import patch

from bs4 import BeautifulSoup

from app import app
from features.calendar import EventImportError
from headlines.routes import _workflow_categories
from headlines.state import ALL_CATEGORIES
from mailchimp.renderer import render_main_newsletter
from routes.saved_articles import prepare_article


class HeadlineCalendarTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='headline-calendar-test')
        self.client = app.test_client()
        self.hearing = prepare_article({
            'title': 'Original hearing',
            'url': 'https://www.congress.gov/event/119th-congress/senate-event/338824',
            'date': '2026-11-18T11:00:00',
        }, 'senate', 'Finance', 'hearing')
        self.news = prepare_article({
            'title': 'News article', 'url': 'https://example.com/news', 'date': '2026-11-18',
        }, 'news', 'CMS')
        self.workflow = {
            'built_at': '2026-11-18T09:00:00',
            'items': {item['id']: {**item, 'headline': 'Edited ' + item['title'],
                                  'original_title': item['title']} for item in (self.hearing, self.news)},
            'index': {category: [] for category in ALL_CATEGORIES},
            'parents': {},
            'mailchimp_draft': {'id': 'existing-draft', 'content_hash': 'original-hash'},
        }
        self.workflow['index']['Events'] = [self.hearing['id'], self.news['id']]
        with self.client.session_transaction() as state:
            state['saved_articles'] = [self.hearing, self.news]
            state['headline_workflow'] = deepcopy(self.workflow)

    def test_review_offers_button_only_for_hearings_and_does_not_import_on_load(self):
        with patch('headlines.routes.event_from_url') as fetch:
            response = self.client.get('/headlines')
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.data, 'html.parser')
        buttons = soup.select('.headline-calendar-button')
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]['data-article-id'], self.hearing['id'])
        self.assertEqual(buttons[0]['data-import-url'], '/headlines/add-to-calendar')
        self.assertEqual(buttons[0]['type'], 'button')
        fetch.assert_not_called()

    def test_nested_hearing_gets_its_own_button(self):
        with self.client.session_transaction() as state:
            state['headline_workflow']['parents'] = {self.hearing['id']: self.news['id']}
        soup = BeautifulSoup(self.client.get('/headlines').data, 'html.parser')
        self.assertEqual(soup.select_one('.headline-children .headline-calendar-button')['data-article-id'], self.hearing['id'])

    def test_import_uses_saved_link_and_preserves_entire_workflow_and_newsletter(self):
        parsed = {'title': 'Official title', 'description': self.hearing['url']}
        before_email = render_main_newsletter(_workflow_categories(self.workflow))
        for deduped in (False, True):
            with self.subTest(deduped=deduped), patch('headlines.routes.event_from_url', return_value=parsed) as extract, patch('headlines.routes.create_event_addevent', return_value={'id': 'event-1', 'deduped': deduped}) as create:
                response = self.client.post('/headlines/add-to-calendar', json={
                    'id': self.hearing['id'], 'url': 'https://example.com/untrusted-override',
                })
                self.assertEqual(response.get_json(), {'ok': True, 'deduped': deduped})
                extract.assert_called_once_with(self.hearing['url'])
                create.assert_called_once_with(parsed)
            with self.client.session_transaction() as state:
                self.assertEqual(state['headline_workflow'], self.workflow)
                self.assertEqual(state['saved_articles'], [self.hearing, self.news])
                self.assertEqual(render_main_newsletter(_workflow_categories(state['headline_workflow'])), before_email)

    def test_rejects_non_hearings_missing_ids_and_malformed_payloads(self):
        with patch('headlines.routes.event_from_url') as extract:
            for payload, status in (({'id': self.news['id']}, 400), ({'id': 'missing'}, 404), ({}, 400), ([], 400)):
                with self.subTest(payload=payload):
                    response = self.client.post('/headlines/add-to-calendar', json=payload)
                    self.assertEqual(response.status_code, status)
                    self.assertFalse(response.get_json()['ok'])
            extract.assert_not_called()

    def test_rejects_hearing_moved_out_of_events(self):
        with self.client.session_transaction() as state:
            workflow = state['headline_workflow']
            workflow['index']['Events'].remove(self.hearing['id'])
            workflow['index']['Medicare'].append(self.hearing['id'])
        with patch('headlines.routes.event_from_url') as extract:
            response = self.client.post('/headlines/add-to-calendar', json={'id': self.hearing['id']})
            self.assertEqual(response.status_code, 400)
            extract.assert_not_called()

    def test_removed_hearing_cannot_be_imported_from_stale_page(self):
        with self.client.session_transaction() as state:
            state['saved_articles'] = [self.news]
        with patch('headlines.routes.event_from_url') as extract:
            self.assertEqual(self.client.post('/headlines/add-to-calendar', json={'id': self.hearing['id']}).status_code, 404)
            extract.assert_not_called()

    def test_requires_generated_workflow(self):
        with self.client.session_transaction() as state:
            state.pop('headline_workflow')
        with patch('headlines.routes.event_from_url') as extract:
            self.assertEqual(self.client.post('/headlines/add-to-calendar', json={'id': self.hearing['id']}).status_code, 409)
            extract.assert_not_called()

    def test_import_failure_preserves_workflow_and_returns_actionable_error(self):
        with patch('headlines.routes.event_from_url', side_effect=EventImportError('Could not load the House event page.')), patch('headlines.routes.create_event_addevent') as create:
            response = self.client.post('/headlines/add-to-calendar', json={'id': self.hearing['id']})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()['error'], 'Could not load the House event page.')
            create.assert_not_called()
        with self.client.session_transaction() as state:
            self.assertEqual(state['headline_workflow'], self.workflow)

    def test_add_event_failure_does_not_change_draft(self):
        with patch('headlines.routes.event_from_url', return_value={}), patch('headlines.routes.create_event_addevent', side_effect=EventImportError('AddEvent did not confirm creation.')):
            response = self.client.post('/headlines/add-to-calendar', json={'id': self.hearing['id']})
            self.assertFalse(response.get_json()['ok'])
        with self.client.session_transaction() as state:
            self.assertEqual(state['headline_workflow'], self.workflow)

    def test_w2w_review_has_no_calendar_import_action(self):
        event = {'id': 'w2w-event', 'title': 'Calendar event', 'url': self.hearing['url'],
                 'section': 'hearing', 'headline': 'Calendar headline'}
        index = {category: [] for category in ALL_CATEGORIES if category != 'Events'}
        index['Medicare'] = [event['id']]
        with self.client.session_transaction() as state:
            state['addevent_pulled'] = [event]
            state['addevent_categories_cache'] = {'items': {event['id']: event}, 'index': index}
        response = self.client.get('/add-event-pull/review')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'headline-calendar-button', response.data)
        self.assertNotIn(b'headline-calendar.js', response.data)


if __name__ == '__main__':
    unittest.main()
