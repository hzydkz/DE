from datetime import datetime, timedelta, timezone

from briefing.cluster import cluster_items, normalize_title, pick_links
from briefing.common import Item

T0 = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)


def item(title, source, minutes=0, category="general"):
    return Item(title=title, url=f"https://{source}.example/{abs(hash(title))}", source=source,
                source_id=source, category=category, published=(T0 + timedelta(minutes=minutes)).isoformat())


def test_normalize_strips_tags():
    assert normalize_title("[속보] 한은, 기준금리 동결…(종합)") == "한은 기준금리 동결"


def test_same_event_grouped_and_different_events_split():
    items = [
        item("한국은행, 기준금리 연 2.50%로 동결", "연합뉴스"),
        item("한은 기준금리 2.50% 동결…3연속", "한겨레", 5),
        item("[속보] 한국은행 기준금리 동결 결정", "조선일보", 7),
        item("기준금리 동결한 한은 \"추가 인하 신중\"", "동아일보", 9),
        item("서울 아파트값 상승폭 3주 연속 확대", "한겨레", 11),
        item("서울 아파트 매매가 상승폭 확대…3주째", "경향신문", 13),
        item("프로야구 한국시리즈 1차전 우천 취소", "연합뉴스", 15),
    ]
    clusters = cluster_items(items)
    sizes = sorted((len(c.items) for c in clusters), reverse=True)
    assert sizes == [4, 2, 1]
    top = clusters[0]
    assert all("금리" in it.title for it in top.items)
    assert len(top.sources) == 4


def test_same_source_near_duplicate_dropped():
    items = [
        item("[속보] 한국은행 기준금리 동결", "연합뉴스"),
        item("한국은행 기준금리 동결(종합)", "연합뉴스", 30),
    ]
    clusters = cluster_items(items)
    assert sum(len(c.items) for c in clusters) == 1


def test_pick_links_prefers_distinct_sources():
    items = [item(f"한국은행 기준금리 동결 {i}", s, i) for i, s in enumerate(["A", "A", "B", "C"])]
    from briefing.common import Cluster
    links = pick_links(Cluster(items=items), 3)
    assert [l.source for l in links] == ["A", "B", "C"]
