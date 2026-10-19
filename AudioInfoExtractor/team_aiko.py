"""Team aikoの一覧ページに記載された公開日を取得する。"""

import re
import unicodedata
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


SITE = "https://sp.aiko.pcan.us"
LIST_PATH = "/contents/messagemovielist.php"
DATE_HINT = "公開日を取得できませんでした。サイトで確認し、--broadcast-date YYYY-MM-DD を指定してください。"


class TeamAikoDateError(RuntimeError):
    """公開日をサイト上の情報から特定できない。"""


def normalize_publication_date(value: str) -> str:
    """サイト表示・手動指定の日付をYYYYMMDDにそろえる。推測はしない。"""
    value = value.strip()
    if not re.fullmatch(r"[0-9]{8}|[0-9]{4}([./-])[0-9]{1,2}\1[0-9]{1,2}", value):
        raise ValueError("公開日はYYYY-MM-DD形式で指定してください。")
    for format_string in ("%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, format_string).strftime("%Y%m%d")
        except ValueError:
            pass
    raise ValueError("公開日は実在する日付をYYYY-MM-DD形式で指定してください。")


def _listing_url(url: str, category: str | None = None) -> bool:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "sp.aiko.pcan.us"
            or parsed.path != LIST_PATH or parsed.username or parsed.password):
        return False
    return category is None or parse_qs(parsed.query).get("mc_id") == [category]


def _title_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _find_date(soup: BeautifulSoup, title: str, episode_query: dict[str, list[str]]) -> str:
    dates = set()
    for anchor in soup.select("a[href]"):
        parsed = urlsplit(urljoin(SITE + "/contents/", str(anchor["href"])))
        if parsed.hostname != "sp.aiko.pcan.us" or parsed.path != "/contents/messagemovie.php":
            continue
        query = parse_qs(parsed.query)
        if episode_query.get("msg_movie_id"):
            # URLが分かる場合、同じ見出しの別記事にはフォールバックしない。
            if query.get("msg_movie_id") != episode_query["msg_movie_id"]:
                continue
            if episode_query.get("mc_id") and query.get("mc_id") != episode_query["mc_id"]:
                continue
        else:
            label = anchor.select_one(".movie_title .bold, .movie_title .large")
            if label is None or _title_key(label.get_text(" ", strip=True)) != _title_key(title):
                continue
        time = anchor.select_one("time")
        if time is None:
            raise TeamAikoDateError(DATE_HINT)
        try:
            dates.add(normalize_publication_date(str(time.get("datetime") or time.get_text(strip=True))))
        except ValueError:
            raise TeamAikoDateError(DATE_HINT) from None
    if len(dates) > 1:
        raise TeamAikoDateError("公開日を一意に特定できませんでした。" + DATE_HINT)
    return next(iter(dates), "")


def _next_page(soup: BeautifulSoup, current_url: str, category: str) -> str:
    for anchor in soup.select("a[href]"):
        text = anchor.get_text(" ", strip=True).upper()
        if text not in ("NEXT", "次へ", "次") and "next" not in (anchor.get("rel") or []):
            continue
        candidate = urljoin(current_url, str(anchor["href"]))
        if _listing_url(candidate, category):
            return candidate
    return ""


def resolve_team_aiko_publish_date(
    html_content: str, episode_title: str, *, page_url: str = "", session=None,
) -> str:
    """詳細ページのLISTリンクをたどり、対象回の公開日だけを取得する。"""
    if session is None:
        with requests.Session() as owned_session:
            return resolve_team_aiko_publish_date(
                html_content, episode_title, page_url=page_url, session=owned_session,
            )

    base_url = page_url or SITE + "/contents/messagemovie.php"
    episode_query = parse_qs(urlsplit(page_url).query)
    detail = BeautifulSoup(html_content, "html.parser")
    url = ""
    for anchor in detail.select("a[href]"):
        candidate = urljoin(base_url, str(anchor["href"]))
        if _listing_url(candidate):
            url = candidate
            break
    if not url:
        url = SITE + LIST_PATH + "?mc_id=8"
    category = parse_qs(urlsplit(url).query).get("mc_id", ["8"])[0]

    # 古い回もページ送りで探す。循環・異常なページ数では打ち切る。
    visited = set()
    for _ in range(100):
        if not url or url in visited:
            break
        visited.add(url)
        try:
            response = session.get(url, headers={"Referer": base_url}, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            raise TeamAikoDateError(DATE_HINT) from None
        soup = BeautifulSoup(response.content, "html.parser")
        date = _find_date(soup, episode_title, episode_query)
        if date:
            return date
        url = _next_page(soup, url, category)
    raise TeamAikoDateError(DATE_HINT)
