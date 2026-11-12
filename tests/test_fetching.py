import unittest
from unittest.mock import Mock, patch

from sources.fetching import fetch_response


class FetchingTests(unittest.TestCase):
    @patch("sources.fetching.requests.get")
    def test_fetches_page_directly(self, get):
        get.return_value = Mock(status_code=200)

        response = fetch_response(
            "https://committee.senate.gov/news",
            headers={"Accept-Language": "en-US"},
            timeout=20,
        )

        self.assertEqual(response.status_code, 200)
        get.assert_called_once()
        call = get.call_args
        self.assertEqual(call.args[0], "https://committee.senate.gov/news")
        self.assertEqual(call.kwargs["headers"]["Accept-Language"], "en-US")
        self.assertEqual(call.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
