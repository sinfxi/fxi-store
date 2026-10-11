import unittest
from study_sources import _trusted, _unwrap_url

class StudySourceTests(unittest.TestCase):
    def test_trusted_education_domains(self):
        self.assertTrue(_trusted("https://openstax.org/books/algebra"))
        self.assertTrue(_trusted("https://fa.wikipedia.org/?curid=1"))
        self.assertTrue(_trusted("https://www.roshd.ir/lesson"))
    def test_untrusted_domains_rejected(self):
        self.assertFalse(_trusted("https://example.com/lesson"))
        self.assertFalse(_trusted("javascript:alert(1)"))
    def test_duckduckgo_redirect_is_unwrapped(self):
        self.assertEqual(
            _unwrap_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fopenstax.org%2F"),
            "https://openstax.org/"
        )
    def test_non_http_url_rejected(self):
        self.assertEqual(_unwrap_url("javascript:alert(1)"), "")

if __name__ == "__main__":
    unittest.main()
