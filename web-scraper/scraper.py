#!/usr/bin/env python3
"""
Books to Scrape スクレイパー

スクレイピング練習用サイト https://books.toscrape.com/ から
全カテゴリの本の情報（書名・カテゴリ・価格・評価・在庫・URL・画像URL）を集め、
CSV と JSON に保存します。

使い方:
    python scraper.py                       # 全カテゴリを取得
    python scraper.py --max-categories 3    # 動作確認用に3カテゴリだけ
    python scraper.py --delay 1.0 --output-dir output
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = "BooksScraperPortfolio/1.0 (+educational use)"

# サイト上の評価はクラス名（"star-rating Three" など）で表されているので数値に変換する
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

log = logging.getLogger("scraper")


@dataclass
class Book:
    title: str
    category: str
    price: float
    rating: int
    in_stock: bool
    url: str
    image_url: str


# ---------------------------------------------------------------------------
# HTML の解析（ネットワークに依存しないので単体テストしやすい）
# ---------------------------------------------------------------------------

def parse_categories(html: str, page_url: str) -> list[tuple[str, str]]:
    """トップページのサイドバーから (カテゴリ名, URL) の一覧を返す。

    先頭の「Books」は全体をまとめた親カテゴリなので除外する。
    """
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("div.side_categories ul li ul li a")
    return [(a.get_text(strip=True), urljoin(page_url, a["href"])) for a in links]


def parse_books(html: str, page_url: str, category: str) -> list[Book]:
    """一覧ページから本の情報を取り出す。"""
    soup = BeautifulSoup(html, "html.parser")
    books: list[Book] = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        price_text = pod.select_one("p.price_color").get_text(strip=True)
        rating_el = pod.select_one("p.star-rating")
        rating_word = next(
            (c for c in rating_el.get("class", []) if c in RATING_WORDS), None
        )
        stock_text = pod.select_one("p.availability").get_text(strip=True)
        img = pod.select_one("img")
        books.append(
            Book(
                # 一覧では書名が「...」で省略されるため、省略のない title 属性を使う
                title=link.get("title", link.get_text(strip=True)),
                category=category,
                price=parse_price(price_text),
                rating=RATING_WORDS.get(rating_word, 0),
                in_stock="in stock" in stock_text.lower(),
                url=urljoin(page_url, link["href"]),
                image_url=urljoin(page_url, img["src"]) if img else "",
            )
        )
    return books


def parse_next_page(html: str, page_url: str) -> str | None:
    """「next」リンクがあれば次ページの URL を、なければ None を返す。"""
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("li.next a")
    return urljoin(page_url, nxt["href"]) if nxt else None


def parse_price(text: str) -> float:
    """'£51.77' のような文字列から数値だけを取り出す。"""
    digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not digits:
        raise ValueError(f"価格を読み取れません: {text!r}")
    return float(digits)


# ---------------------------------------------------------------------------
# 取得処理
# ---------------------------------------------------------------------------

class Scraper:
    def __init__(self, base_url: str = BASE_URL, delay: float = 0.5, timeout: float = 15):
        self.base_url = base_url
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        # 一時的なエラー（接続失敗・5xx・429）は間隔を空けて最大3回まで再挑戦する
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.robots = self._load_robots()
        self._last_request = 0.0

    def _load_robots(self) -> urllib.robotparser.RobotFileParser:
        """robots.txt（サイトが決めた自動アクセスのルール）を読み込む。"""
        rp = urllib.robotparser.RobotFileParser()
        robots_url = urljoin(self.base_url, "robots.txt")
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                # robots.txt が存在しない場合は制限なしとして扱う（一般的な解釈）
                rp.parse([])
        except requests.RequestException as exc:
            log.warning("robots.txt を取得できませんでした (%s)。制限なしとして続行します", exc)
            rp.parse([])
        return rp

    def fetch(self, url: str) -> str:
        if not self.robots.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt により禁止されています: {url}")
        # サーバーに負担をかけないよう、前回のアクセスから delay 秒以上空ける
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        log.debug("GET %s", url)
        resp = self.session.get(url, timeout=self.timeout)
        self._last_request = time.monotonic()
        resp.raise_for_status()
        resp.encoding = "utf-8"  # サイトは UTF-8 だが、ヘッダーで指定されないことがあるため明示
        return resp.text

    def scrape(self, max_categories: int | None = None) -> list[Book]:
        home = self.fetch(self.base_url)
        categories = parse_categories(home, self.base_url)
        if max_categories is not None:
            categories = categories[:max_categories]
        log.info("%d カテゴリを取得します", len(categories))

        books: list[Book] = []
        failed: list[str] = []
        for i, (name, url) in enumerate(categories, 1):
            try:
                found = self._scrape_category(name, url)
            except (requests.RequestException, PermissionError) as exc:
                # 1カテゴリの失敗で全体を止めず、記録して次へ進む
                log.error("[%d/%d] %s: 失敗しました (%s)", i, len(categories), name, exc)
                failed.append(name)
                continue
            log.info("[%d/%d] %s: %d 冊", i, len(categories), name, len(found))
            books.extend(found)

        if failed:
            log.warning("取得に失敗したカテゴリ: %s", ", ".join(failed))
        return books

    def _scrape_category(self, name: str, url: str | None) -> list[Book]:
        books: list[Book] = []
        while url:
            html = self.fetch(url)
            books.extend(parse_books(html, url, name))
            url = parse_next_page(html, url)
        return books


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def save_csv(books: list[Book], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig にすると Excel で開いても文字化けしにくい
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[fld.name for fld in fields(Book)])
        writer.writeheader()
        writer.writerows(asdict(b) for b in books)


def save_json(books: list[Book], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": BASE_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(books),
        "books": [asdict(b) for b in books],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="books.toscrape.com から本の情報を集めて CSV/JSON に保存します")
    parser.add_argument("--output-dir", default="output", help="保存先フォルダ（既定: output）")
    parser.add_argument("--delay", type=float, default=0.5, help="アクセス間隔の秒数（既定: 0.5）")
    parser.add_argument("--max-categories", type=int, default=None, help="取得するカテゴリ数の上限（動作確認用）")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳しいログを表示")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    started = time.monotonic()
    books = Scraper(delay=args.delay).scrape(max_categories=args.max_categories)
    if not books:
        log.error("1冊も取得できませんでした")
        return 1

    out = Path(args.output_dir)
    save_csv(books, out / "books.csv")
    save_json(books, out / "books.json")
    log.info(
        "完了: %d 冊 / %.1f 秒 → %s, %s",
        len(books), time.monotonic() - started, out / "books.csv", out / "books.json",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
