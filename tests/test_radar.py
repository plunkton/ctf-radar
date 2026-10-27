import unittest
from src.radar import category_matches, is_online, normalize_event

CONFIG = {
    "categories": ["osint", "steganography"],
    "require_online": True,
    "keywords": {
        "osint": ["osint", "geolocation", "open source intelligence"],
        "steganography": ["steganography", "stego", "hidden message"],
    },
}


class RadarTests(unittest.TestCase):
    def test_osint_match(self):
        event = {"title": "Global OSINT Challenge", "description": ""}
        self.assertEqual(category_matches(event, CONFIG), ["osint"])

    def test_stego_match(self):
        event = {"title": "Image Stego CTF", "description": ""}
        self.assertEqual(category_matches(event, CONFIG), ["steganography"])

    def test_both_categories(self):
        event = {"title": "OSINT and Steganography CTF", "description": ""}
        self.assertEqual(category_matches(event, CONFIG), ["osint", "steganography"])

    def test_online_boolean(self):
        self.assertTrue(is_online({"onsite": False}))
        self.assertFalse(is_online({"onsite": True}))

    def test_unknown_online_status_is_excluded(self):
        self.assertFalse(is_online({}))

    def test_normalize_requires_match_and_online(self):
        event = {"id": 1, "title": "OSINT CTF", "onsite": False, "url": "https://example.com"}
        normalized = normalize_event(event, CONFIG)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["categories"], ["osint"])
        self.assertTrue(normalized["online"])


if __name__ == "__main__":
    unittest.main()
