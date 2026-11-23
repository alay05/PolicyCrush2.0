import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup
from flask import Flask

from features.calendar import EventImportError, _parse_dt_minute, create_event_addevent, event_from_url
from features.calendar_pull import _shape_event, resolve_calendar_id
from routes.add_event import add_event

SAMPLES = json.loads((Path(__file__).parent / 'fixtures/add_event_sources.json').read_text())
SENATE_URL = 'https://www.congress.gov/event/119th-congress/senate-event/338824'
HOUSE_URL = 'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=119594'
EVENT = {
    'title': 'Social Security hearing', 'datetime_start': '2026-11-18 11:00',
    'datetime_end': '2026-11-18 12:00', 'description': SENATE_URL,
    'location': '608 Dirksen', 'timezone': 'America/New_York',
}


def response(payload):
    return Mock(json=Mock(return_value=payload))


class EventSourceTests(unittest.TestCase):
    def test_all_three_senate_examples_use_api_and_eastern_time(self):
        expected = {'338824': '2026-11-18 11:00', '338823': '2026-11-18 15:30', '338880': '2026-12-02 15:30'}
        for event_id, start in expected.items():
            with self.subTest(event_id=event_id), patch('features.calendar._fetch_detail', return_value=SAMPLES[event_id]) as fetch:
                event = event_from_url(f'https://www.congress.gov/event/119th-Congress/senate-event/{event_id}')
                fetch.assert_called_once_with(119, 'senate', event_id)
                self.assertEqual(event['datetime_start'], start)
                self.assertEqual(event['title'], SAMPLES[event_id]['title'])
                self.assertEqual(event['timezone'], 'America/New_York')
                self.assertIn(SAMPLES[event_id]['location']['building'], event['location'])

    def test_all_three_house_examples_use_event_fields_not_document_dates(self):
        expected = {'119594': '2026-11-18 14:00', '119589': '2026-11-18 10:00', '119590': '2026-11-11 10:15'}
        for event_id, start in expected.items():
            html = '<p>Posted November 1, 2026 at 8:00 AM</p>' + SAMPLES[event_id]
            with self.subTest(event_id=event_id), patch('features.calendar.fetch_response', return_value=Mock(text=html)):
                event = event_from_url(f'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={event_id}')
                self.assertEqual(event['datetime_start'], start)
                self.assertNotIn('Committee on', event['title'])
                self.assertNotIn('[AUTO-TEST]', event['title'])
                self.assertIn('Washington, D.C.', event['location'])
                self.assertEqual((datetime.fromisoformat(event['datetime_end']) - datetime.fromisoformat(start)).total_seconds(), 3600)

    def test_daylight_saving_conversion(self):
        with patch('features.calendar._fetch_detail', return_value={**SAMPLES['338824'], 'date': '2026-07-01T14:00:00Z'}):
            self.assertEqual(event_from_url(SENATE_URL)['datetime_start'], '2026-07-01 10:00')

    def test_missing_or_cancelled_schedule_is_not_guessed(self):
        for change in ({'date': ''}, {'date': '2026-11-18'}, {'date': '2026-11-18T11:00:00'}, {'meetingStatus': 'Cancelled'}):
            with self.subTest(change=change), patch('features.calendar._fetch_detail', return_value={**SAMPLES['338824'], **change}):
                with self.assertRaises(EventImportError):
                    event_from_url(SENATE_URL)
        with patch('features.calendar.fetch_response', return_value=Mock(text=SAMPLES['119594'].replace('2:00 PM', 'TBD'))):
            with self.assertRaises(EventImportError):
                event_from_url(HOUSE_URL)

    def test_unsupported_links_are_rejected_before_fetch(self):
        with patch('features.calendar._fetch_detail') as api, patch('features.calendar.fetch_response') as fetch:
            for url in ('https://example.com', 'http://localhost', SENATE_URL.replace('www.congress.gov', 'www.congress.gov.example.com'), HOUSE_URL.replace('119594', 'bad')):
                with self.subTest(url=url), self.assertRaises(EventImportError):
                    event_from_url(url)
            api.assert_not_called()
            fetch.assert_not_called()


class AddEventWriteTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.__enter__ = Mock(return_value=self.session)
        self.session.__exit__ = Mock(return_value=False)
        patcher = patch('features.calendar._api_session', return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_datetime_with_seconds_is_parsed_without_truncation(self):
        self.assertEqual(_parse_dt_minute('2026-11-18 11:00:00'), datetime(2026, 11, 18, 11))

    def test_creation_specifies_calendar_and_correct_search_parameters(self):
        self.session.get.return_value = response({'events': []})
        self.session.post.return_value = response({'id': 'new'})
        with patch.dict('os.environ', {'ADDEVENT_CALENDAR_ID': ''}), patch('features.calendar.resolve_calendar_id', return_value='target'):
            saved = create_event_addevent(EVENT)
        self.assertFalse(saved['deduped'])
        self.assertEqual(self.session.post.call_args.kwargs['json'], {
            **EVENT, 'calendar_id': 'target',
            'description': f'<a href="{SENATE_URL}">{SENATE_URL}</a>',
        })
        params = self.session.get.call_args.kwargs['params']
        self.assertEqual(params['calendar_ids'], 'target')
        self.assertEqual(params['datetime_min'], '2026-11-18 08:00:00')
        self.assertNotIn('starts_after', params)

    def test_clickable_source_survives_calendar_pull_and_duplicate_detection(self):
        for source in (SENATE_URL, HOUSE_URL):
            with self.subTest(source=source):
                event = {**EVENT, 'description': source}
                self.session.get.return_value = response({'events': []})
                self.session.post.return_value = response({'id': 'new'})
                create_event_addevent(event, calendar_id='target')
                payload = self.session.post.call_args.kwargs['json']
                anchor = BeautifulSoup(payload['description'], 'html.parser').find('a')
                self.assertIsNotNone(anchor)
                self.assertEqual(anchor['href'], source)
                self.assertEqual(anchor.get_text(), source)
                self.assertEqual(_shape_event(payload)['original_link'], source)
                self.assertEqual(event['description'], source)

                self.session.post.reset_mock()
                self.session.get.return_value = response({'events': [{**payload, 'id': 'existing'}]})
                self.assertTrue(create_event_addevent(event, calendar_id='target')['deduped'])
                self.session.post.assert_not_called()

    def test_duplicate_on_later_page_with_uppercase_congress_is_reused(self):
        existing = {**EVENT, 'id': 'existing', 'calendar_id': 'target', 'datetime_start': '2026-11-18 11:00:00', 'description': SENATE_URL.replace('congress/senate', 'Congress/senate')}
        self.session.get.side_effect = [response({'events': [{**existing, 'calendar_id': 'other'}] * 20}), response({'events': [existing]})]
        saved = create_event_addevent(EVENT, calendar_id='target')
        self.assertTrue(saved['deduped'])
        self.assertEqual(saved['id'], 'existing')
        self.session.post.assert_not_called()
        self.assertEqual(self.session.get.call_count, 2)

    def test_lookup_failure_never_creates(self):
        self.session.get.side_effect = requests.ConnectionError('unavailable')
        with self.assertRaisesRegex(EventImportError, 'Nothing was added'):
            create_event_addevent(EVENT, calendar_id='target')
        self.session.post.assert_not_called()

    def test_missing_calendar_never_creates(self):
        with patch.dict('os.environ', {'ADDEVENT_CALENDAR_ID': ''}), patch('features.calendar.resolve_calendar_id', return_value=None):
            with self.assertRaisesRegex(EventImportError, 'Could not find'):
                create_event_addevent(EVENT)
        self.session.post.assert_not_called()

    def test_unconfirmed_creation_is_not_success(self):
        self.session.get.return_value = response({'events': []})
        self.session.post.return_value = response({'message': 'invalid'})
        with self.assertRaisesRegex(EventImportError, 'did not confirm'):
            create_event_addevent(EVENT, calendar_id='target')

    def test_calendar_resolution_requires_exact_match_across_pages(self):
        self.session.get.side_effect = [response({'calendars': [{'id': 'wrong', 'unique_key': 'other'}] * 20}), response({'calendars': [{'id': 'target', 'unique_key': 'GT179952'}]})]
        self.assertEqual(resolve_calendar_id(self.session, 'GT179952'), 'target')
        self.session.get.side_effect = None
        self.session.get.return_value = response({'calendars': [{'id': 'wrong', 'unique_key': 'other'}]})
        self.assertIsNone(resolve_calendar_id(self.session, 'GT179952'))


class ImportRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        app.config['TESTING'] = True
        app.register_blueprint(add_event)
        self.client = app.test_client()

    def test_route_sends_parsed_event_and_reports_duplicate(self):
        with patch('routes.add_event.event_from_url', return_value=EVENT), patch('routes.add_event.create_event_addevent', return_value={'id': 'existing', 'deduped': True}) as create, patch('routes.add_event.render_template', return_value='rendered') as render:
            self.assertEqual(self.client.post('/add-event', data={'event-url': SENATE_URL}).status_code, 200)
            create.assert_called_once_with(EVENT)
            self.assertTrue(render.call_args.kwargs['result']['deduped'])

    def test_route_preserves_url_and_shows_actionable_error(self):
        with patch('routes.add_event.event_from_url', side_effect=EventImportError('Could not load event')), patch('routes.add_event.create_event_addevent') as create, patch('routes.add_event.render_template', return_value='rendered') as render:
            self.client.post('/add-event', data={'event-url': SENATE_URL})
            create.assert_not_called()
            self.assertEqual(render.call_args.kwargs['error'], 'Could not load event')
            self.assertEqual(render.call_args.kwargs['event_url'], SENATE_URL)


if __name__ == '__main__':
    unittest.main()
