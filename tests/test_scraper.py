import unittest
from datetime import date
from scraper import discover_leaflets, is_current_leaflet, match_score, match_shopping_list, parse_flyer, parse_money

class DiscoveryTests(unittest.TestCase):
    def test_discovers_weekly_and_weekend_leaflets_only(self):
        markup = '<a href="/l/folders/hah-wk35-2026/ar/0">Week</a><a href="/l/folders/hah-wk35-weekenddeals-2026/ar/0">Weekend</a><a href="/l/folders/non-food-wk35-2026/ar/0">Other</a>'
        found = discover_leaflets(markup)
        self.assertEqual([row["kind"] for row in found], ["weekly", "weekenddeals"])
    def test_future_leaflet_is_not_current(self):
        self.assertFalse(is_current_leaflet({"valid_from":"2026-08-31","valid_until":"2026-09-06"}, date(2026,8,28)))
        self.assertTrue(is_current_leaflet({"valid_from":"2026-08-24","valid_until":"2026-08-30"}, date(2026,8,28)))

class ParserTests(unittest.TestCase):
    def setUp(self): self.source = {"url": "https://www.lidl.nl/l/folders/hah-wk35-2026/ar/0", "kind": "weekly"}
    def test_extracts_only_verified_complete_products(self):
        payload = {"success": True, "flyer": {"offerStartDate": "2026-08-24", "offerEndDate": "2026-08-30", "products": {
            "a": {"productId": "1", "title": "Milbona melk", "price": "1.19", "image": "https://img.example/melk.jpg", "url": "https://www.lidl.nl/p/melk/p1"},
            "b": {"title": "Geen prijs", "image": "https://img.example/x.jpg", "url": "https://www.lidl.nl/p/x/p2"},
            "c": {"title": "Onbetrouwbaar", "price": "9.99", "image": "https://img.example/y.jpg", "url": "https://example.com/p/3"}}}}
        meta, offers = parse_flyer(payload, self.source)
        self.assertEqual(meta["products"], 1); self.assertEqual(offers[0]["price"], 1.19); self.assertIsNone(offers[0]["old_price"])
    def test_rejects_failed_api_response(self):
        with self.assertRaises(ValueError): parse_flyer({"success": False}, self.source)
    def test_money_parser(self): self.assertEqual(parse_money("€ 2,49"), 2.49); self.assertIsNone(parse_money("goedkoop"))

class MatchingTests(unittest.TestCase):
    def test_alias_match(self): self.assertGreater(match_score({"name": "kipfilet", "aliases": ["kipfiletblokjes"]}, {"name": "Verse kipfiletblokjes 400 gram", "brand": None}), .68)
    def test_unrelated_product_does_not_match(self):
        row = match_shopping_list([{"name": "melk", "aliases": ["halfvolle melk"], "qty": 2}], [{"name": "Accu boormachine", "brand": "PARKSIDE"}])[0]
        self.assertFalse(row["matched"]); self.assertIsNone(row["deal"])

if __name__ == "__main__": unittest.main()
