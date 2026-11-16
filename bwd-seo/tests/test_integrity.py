import datetime as dt
import os
import sys
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE, "scripts"))
from seo_integrity import SEOParser, parse_robots, robots_allows, inspect, read_baseline, read_scheduled

ROBOTS = """User-agent: *
Allow: /
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /*?set_currency=
Disallow: /locations/countries/*/*/
"""

class SEOIntegrityTests(unittest.TestCase):
    def test_robot_directives(self):
        rules = parse_robots(ROBOTS)
        self.assertTrue(robots_allows("https://bestwebdeveloper.org/services/web-development/", rules))
        self.assertFalse(robots_allows("https://bestwebdeveloper.org/wp-admin/", rules))
        self.assertTrue(robots_allows("https://bestwebdeveloper.org/wp-admin/admin-ajax.php", rules))
        self.assertFalse(robots_allows("https://bestwebdeveloper.org/locations/countries/france-fr/abitain/", rules))
        self.assertFalse(robots_allows("https://bestwebdeveloper.org/?set_currency=USD", rules))

    def test_seo_parser(self):
        html = ('<html lang="en"><head><title>Useful FAQ</title>'
                '<meta name="description" content="Helpful answer">'
                '<link rel="canonical" href="https://bestwebdeveloper.org/faq/">'
                '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
                '</head><body><h1>FAQ</h1></body></html>')
        h = SEOParser()
        h.feed(html)
        self.assertEqual(h.title, "Useful FAQ")
        self.assertEqual(h.desc, "Helpful answer")
        self.assertEqual(h.canonical, ["https://bestwebdeveloper.org/faq/"])
        self.assertEqual(h.h1, 1)
        self.assertEqual(h.jsonld, 1)

    def test_future_article_not_fetched(self):
        future = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)
        url = "https://bestwebdeveloper.org/duplicate-content-across-regions/"
        report = inspect(url, {"404"}, parse_robots(ROBOTS),
                         {"duplicate-content-across-regions": future})
        self.assertEqual(report["outcome"], "SCHEDULED_FUTURE_ARTICLE")
        self.assertEqual(report["google_index_status"], "NOT_VERIFIED")

    def test_complete_historical_baseline(self):
        baseline, rows = read_baseline(os.path.join(BASE, "data", "gsc-baseline.csv"))
        self.assertEqual(rows, 1769)
        self.assertGreater(len(baseline), 1000)
        future = read_scheduled(os.path.join(BASE, "data", "scheduled-future-posts.csv"))
        self.assertEqual(len(future), 50)

if __name__ == "__main__":
    unittest.main()
