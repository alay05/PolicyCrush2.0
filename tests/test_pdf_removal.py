import unittest

from app import app


class PdfRemovalTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pdf_export_routes_are_not_registered(self):
        self.assertEqual(self.client.get("/add-event-pull/export").status_code, 404)
        self.assertEqual(self.client.get("/production/export-categories-pdf").status_code, 404)


if __name__ == "__main__":
    unittest.main()
