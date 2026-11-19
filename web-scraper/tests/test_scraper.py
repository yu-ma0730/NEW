"""scraper.py の単体テスト（ネットワークに接続せずに実行できます）

実行方法（web-scraper フォルダで）:
    python -m unittest discover -s tests -v
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scraper  # noqa: E402

HOME_HTML = """
<div class="side_categories"><ul class="nav nav-list"><li>
  <a href="catalogue/category/books_1/index.html">Books</a>
  <ul>
    <li><a href="catalogue/category/books/travel_2/index.html"> Travel </a></li>
    <li><a href="catalogue/category/books/mystery_3/index.html">Mystery</a></li>
  </ul>
</li></ul></div>
"""

LIST_HTML = """
<article class="product_pod">
  <div class="image_container"><a href="../../../a-light-in-the-attic_1000/index.html">
    <img src="../../../../media/cache/2c/da/x.jpg" alt="A Light in the Attic"></a></div>
  <p class="star-rating Three"></p>
  <h3><a href="../../../a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light in the ...</a></h3>
  <div class="product_price"><p class="price_color">£51.77</p>
    <p class="instock availability"><i class="icon-ok"></i> In stock </p></div>
</article>
<article class="product_pod">
  <p class="star-rating Five"></p>
  <h3><a href="../../../other_1/index.html" title="Other">Other</a></h3>
  <div class="product_price"><p class="price_color">Â£10.00</p>
    <p class="availability"> Out of stock </p></div>
</article>
<ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
"""

PAGE_URL = "https://books.toscrape.com/catalogue/category/books/poetry_23/index.html"


class ParseTests(unittest.TestCase):
    def test_categories_skip_parent_and_resolve_urls(self):
        cats = scraper.parse_categories(HOME_HTML, "https://books.toscrape.com/")
        self.assertEqual(
            cats,
            [
                ("Travel", "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"),
                ("Mystery", "https://books.toscrape.com/catalogue/category/books/mystery_3/index.html"),
            ],
        )

    def test_books_fields(self):
        books = scraper.parse_books(LIST_HTML, PAGE_URL, "Poetry")
        self.assertEqual(len(books), 2)
        b = books[0]
        self.assertEqual(b.title, "A Light in the Attic")  # 省略されていない書名
        self.assertEqual(b.category, "Poetry")
        self.assertEqual(b.price, 51.77)
        self.assertEqual(b.rating, 3)
        self.assertTrue(b.in_stock)
        self.assertEqual(b.url, "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html")
        self.assertEqual(b.image_url, "https://books.toscrape.com/media/cache/2c/da/x.jpg")

    def test_out_of_stock_and_missing_image(self):
        b = scraper.parse_books(LIST_HTML, PAGE_URL, "Poetry")[1]
        self.assertFalse(b.in_stock)
        self.assertEqual(b.rating, 5)
        self.assertEqual(b.image_url, "")
        # 文字化けした通貨記号（Â£）が付いていても価格を読み取れること
        self.assertEqual(b.price, 10.0)

    def test_next_page(self):
        self.assertEqual(
            scraper.parse_next_page(LIST_HTML, PAGE_URL),
            "https://books.toscrape.com/catalogue/category/books/poetry_23/page-2.html",
        )
        self.assertIsNone(scraper.parse_next_page("<html></html>", PAGE_URL))

    def test_price_error(self):
        with self.assertRaises(ValueError):
            scraper.parse_price("free")


class SaveTests(unittest.TestCase):
    def test_csv_and_json(self):
        books = scraper.parse_books(LIST_HTML, PAGE_URL, "Poetry")
        with tempfile.TemporaryDirectory() as d:
            scraper.save_csv(books, Path(d) / "books.csv")
            scraper.save_json(books, Path(d) / "books.json")
            with open(Path(d) / "books.csv", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["title"], "A Light in the Attic")
            self.assertEqual(rows[1]["in_stock"], "False")
            data = json.loads((Path(d) / "books.json").read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 2)
            self.assertEqual(data["books"][0]["price"], 51.77)


if __name__ == "__main__":
    unittest.main()
