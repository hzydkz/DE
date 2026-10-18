"""소스별 수집 → 공통 형식 Item. 수집 결과는 .cache/raw.json 버퍼에 누적한다.

RSS 피드는 최근 N건만 보여 주므로 하루 한 번 새벽 수집으로는 전날 0~24시를
다 덮지 못한다. 그래서 하루 여러 번 수집해 버퍼에 합치고, 빌드 때 전날 창으로 자른다.
버퍼는 레포가 아니라 Actions 캐시에 둔다(설명문 = 기사 일부라 공개 저장하지 않음).
"""

from __future__ import annotations

import calendar
import html
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from .common import CACHE_DIR, Item, load_config, read_json, write_json

BUFFER_FILE = CACHE_DIR / "raw.json"
BUFFER_KEEP = timedelta(days=3)
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; DailyBriefingBot/1.0; +https://github.com/hzydkz/DE)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ref$|from$|cmpid$)", re.I)


def clean_text(s: str | None, limit: int = 300) -> str:
    s = html.unescape(_TAG_RE.sub(" ", s or ""))
    s = _WS_RE.sub(" ", s).strip()
    return s[:limit]


def normalize_url(url: str) -> str:
    """중복 제거용 URL 정규화: 스킴·www·추적 파라미터·끝 슬래시 제거."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    return urlunsplit(("https", host, parts.path.rstrip("/"), query, ""))


def _struct_to_iso(st) -> str | None:
    if not st:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), timezone.utc).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _parse_feed(url: str):
    feed = feedparser.parse(_get(url).content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"피드 파싱 실패: {feed.bozo_exception}")
    return feed


def fetch_rss(src: dict) -> list[Item]:
    items = []
    for e in _parse_feed(src["url"]).entries:
        published = _struct_to_iso(e.get("published_parsed") or e.get("updated_parsed"))
        if not published or not e.get("link") or not e.get("title"):
            continue
        items.append(Item(
            title=clean_text(e.title, 200),
            url=e.link,
            source=src["name"],
            source_id=src["id"],
            category=src["category"],
            published=published,
            description=clean_text(e.get("summary") or e.get("description")),
        ))
    return items


def fetch_gnews(src: dict) -> list[Item]:
    """Google 뉴스: 제목이 '기사 제목 - 매체명' 형태라 매체명을 떼어 출처로 쓴다."""
    items = []
    for e in _parse_feed(src["url"]).entries:
        published = _struct_to_iso(e.get("published_parsed"))
        if not published or not e.get("link"):
            continue
        outlet = (e.get("source") or {}).get("title") or ""
        title = e.title
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3]
        items.append(Item(
            title=clean_text(title, 200),
            url=e.link,
            source=outlet or src["name"],
            source_id=src["id"],
            category=src["category"],
            published=published,
            # Google 뉴스 설명문은 관련 기사 제목 목록(HTML)이라 그대로 쓰면 잡음이 많다
            description="",
        ))
    return items


def _traffic(s: str) -> int:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else 0


def fetch_trends(src: dict) -> list[Item]:
    items = []
    for e in _parse_feed(src["url"]).entries:
        keyword = clean_text(e.get("title"), 100)
        if not keyword:
            continue
        news_title = clean_text(e.get("ht_news_item_title"), 200)
        news_url = e.get("ht_news_item_url")
        traffic = _traffic(e.get("ht_approx_traffic", ""))
        items.append(Item(
            title=f"{keyword} — {news_title}" if news_title else keyword,
            url=news_url or f"https://www.google.com/search?q={quote_plus(keyword)}",
            source=clean_text(e.get("ht_news_item_source"), 50) or src["name"],
            source_id=src["id"],
            category=src["category"],
            published=_struct_to_iso(e.get("published_parsed")) or _now_iso(),
            description=f"검색량 약 {traffic:,}회 이상" if traffic else "",
            weight=1 + math.log10(traffic) / 2 if traffic > 1 else 1.0,
        ))
    return items


def fetch_hn(src: dict) -> list[Item]:
    since = int(time.time()) - 2 * 86400
    r = _get("https://hn.algolia.com/api/v1/search", params={
        "tags": "story",
        "numericFilters": f"created_at_i>{since},points>={src.get('min_points', 150)}",
        "hitsPerPage": 50,
    })
    items = []
    for h in r.json().get("hits", []):
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append(Item(
            title=clean_text(h.get("title"), 200),
            url=h.get("url") or hn_url,
            source=src["name"],
            source_id=src["id"],
            category=src["category"],
            published=datetime.fromtimestamp(h["created_at_i"], timezone.utc).isoformat(),
            description=f"HN {h.get('points', 0)}점, 댓글 {h.get('num_comments', 0)}개",
            weight=1 + math.log10(max(h.get("points", 1), 1)) / 2,
        ))
    return items


class Skipped(Exception):
    """설정 부족 등으로 의도적으로 건너뛴 소스 (실패로 치지 않음)."""


def fetch_youtube(src: dict) -> list[Item]:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise Skipped("YOUTUBE_API_KEY 없음")
    params = {"part": "snippet,statistics", "chart": "mostPopular",
              "regionCode": src.get("region", "KR"), "maxResults": 25, "key": key}
    if src.get("video_category"):
        params["videoCategoryId"] = src["video_category"]
    r = _get("https://www.googleapis.com/youtube/v3/videos", params=params)
    observed = _now_iso()  # 게시 시각이 아니라 '그 시점에 인기였다'는 관측 시각으로 날짜를 매긴다
    items = []
    for v in r.json().get("items", []):
        views = int(v.get("statistics", {}).get("viewCount", 0))
        sn = v["snippet"]
        items.append(Item(
            title=clean_text(sn.get("title"), 200),
            url=f"https://www.youtube.com/watch?v={v['id']}",
            source=f"YouTube · {clean_text(sn.get('channelTitle'), 40)}",
            source_id=src["id"],
            category=src["category"],
            published=observed,
            description=clean_text(sn.get("description"), 200),
            weight=1 + math.log10(max(views, 1)) / 3,
        ))
    return items


FETCHERS = {"rss": fetch_rss, "gnews": fetch_gnews, "trends": fetch_trends,
            "hn": fetch_hn, "youtube": fetch_youtube}


def fetch_source(src: dict) -> list[Item]:
    return FETCHERS[src["type"]](src)


def collect() -> dict:
    """모든 소스를 수집해 버퍼에 합친다. 소스 하나가 실패해도 계속 진행."""
    cfg = load_config()
    buf = read_json(BUFFER_FILE, {"items": {}, "status": {}})
    now = datetime.now(timezone.utc)

    for src in cfg["sources"]:
        st = buf["status"].setdefault(src["id"], {})
        st["last_try"] = now.isoformat()
        try:
            items = fetch_source(src)
        except Skipped as e:
            st.update(skipped=str(e))
            print(f"[skip] {src['id']}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 다음 소스로 넘어간다
            st.update(last_error=f"{type(e).__name__}: {e}"[:300])
            print(f"[fail] {src['id']}: {st['last_error']}", file=sys.stderr)
            continue
        st.pop("skipped", None)
        st.update(last_ok=now.isoformat(), last_count=len(items))
        for it in items:
            # 같은 URL 은 최신 수집값(가중치 갱신)으로 덮되 처음 본 게시 시각은 유지
            key = normalize_url(it.url)
            prev = buf["items"].get(key)
            d = it.to_dict()
            if prev:
                d["published"] = prev["published"]
            buf["items"][key] = d
        print(f"[ok]   {src['id']}: {len(items)}건")

    cutoff = (now - BUFFER_KEEP).isoformat()
    buf["items"] = {k: v for k, v in buf["items"].items() if v["published"] >= cutoff}
    write_json(BUFFER_FILE, buf)
    print(f"버퍼: {len(buf['items'])}건")
    return buf


def items_in_window(buf: dict, start: datetime, end: datetime) -> list[Item]:
    s, e = start.isoformat(), end.isoformat()
    return [Item(**v) for v in buf["items"].values() if s <= v["published"] < e]
