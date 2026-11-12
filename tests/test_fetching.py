import unittest
from unittest.mock import Mock, patch

from config import Config
from sources import fetching
from sources.fetching import fetch_response


class FetchingTests(unittest.TestCase):
    def setUp(self):
        fetching._TRANSPORT_BLOCKED_UNTIL.clear()

    @patch("sources.fetching.requests.get")
    def test_blocked_page_uses_configured_transport_without_javascript(self, get):
        blocked = Mock(status_code=403)
        proxied = Mock(status_code=200, text="official page")
        get.side_effect = [blocked, proxied]

        with patch.object(Config, "SCRAPINGBEE_API_KEY", "test-key"):
            response = fetch_response(
                "https://committee.senate.gov/news",
                proxy_on_block=True,
            )

        self.assertIs(response, proxied)
        self.assertEqual(response.url, "https://committee.senate.gov/news")
        proxy_call = get.call_args_list[1]
        self.assertEqual(proxy_call.args[0], "https://app.scrapingbee.com/api/v1")
        self.assertEqual(proxy_call.kwargs["params"]["render_js"], "false")
        self.assertEqual(
            proxy_call.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )

    @patch("sources.fetching.requests.get")
    def test_successful_direct_page_does_not_use_transport(self, get):
        get.return_value = Mock(status_code=200)

        response = fetch_response(
            "https://committee.senate.gov/news",
            proxy_on_block=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get.call_count, 1)

    @patch("sources.fetching.requests.get")
    def test_access_denial_opens_circuit_and_prevents_repeat_credit_use(self, get):
        first_direct = Mock(status_code=403)
        proxy_denied = Mock(
            status_code=403,
            text="Access Denied",
            headers={"Spb-initial-status-code": "403"},
        )
        second_direct = Mock(status_code=403)
        get.side_effect = [first_direct, proxy_denied, second_direct]

        with patch.object(Config, "SCRAPINGBEE_API_KEY", "test-key"):
            fetch_response("https://aging.senate.gov/news", proxy_on_block=True)
            response = fetch_response(
                "https://finance.senate.gov/news",
                proxy_on_block=True,
            )

        self.assertIs(response, second_direct)
        self.assertEqual(get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
