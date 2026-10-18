"""사용법:
  python -m briefing collect            소스 수집 → .cache/raw.json 버퍼에 누적
  python -m briefing day [YYYY-MM-DD]   버퍼에서 그 날짜(기본: KST 어제) 브리핑 JSON 생성
  python -m briefing site               data/*.json → site/ 정적 HTML
  python -m briefing verify             소스별 동작 여부와 KST 어제 기사 수 점검 (버퍼 안 건드림)
  python -m briefing clusters [날짜]     요약 없이 분야별 상위 클러스터 출력 (임계값 확인용)
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date

from .common import TOP_ISSUES, day_window, kst_yesterday, load_config


def _date_arg(args: list[str]) -> date:
    return date.fromisoformat(args[0]) if args else kst_yesterday()


def verify() -> int:
    from .collect import Skipped, fetch_source

    start, end = day_window(kst_yesterday())
    s, e = start.isoformat(), end.isoformat()
    cfg = load_config()
    per_cat: Counter = Counter()
    bad = 0
    for src in cfg["sources"]:
        try:
            items = fetch_source(src)
        except Skipped as ex:
            print(f"SKIP {src['id']:<20} {ex}")
            continue
        except Exception as ex:  # noqa: BLE001
            bad += 1
            print(f"FAIL {src['id']:<20} {type(ex).__name__}: {str(ex)[:150]}")
            continue
        times = sorted(it.published for it in items)
        y = sum(1 for t in times if s <= t < e)
        if y:
            per_cat[src["category"]] += 1
        span = f"{times[0][:16]} ~ {times[-1][:16]}" if times else "-"
        print(f"OK   {src['id']:<20} 전체 {len(items):>3}건, 어제 {y:>3}건, 범위(UTC) {span}")
    print("\n분야별 '어제 기사 있는' 소스 수:")
    for cat in cfg["categories"]:
        print(f"  {cat['name']}: {per_cat[cat['key']]}")
    return 1 if bad else 0


def show_clusters(d: date) -> None:
    from .cluster import cluster_items
    from .collect import BUFFER_FILE, items_in_window
    from .common import read_json

    buf = read_json(BUFFER_FILE, {"items": {}, "status": {}})
    items = items_in_window(buf, *day_window(d))
    for cat in load_config()["categories"]:
        cs = cluster_items([it for it in items if it.category == cat["key"]])
        print(f"\n===== {cat['name']} (기사 {sum(len(c.items) for c in cs)}, 클러스터 {len(cs)}) =====")
        for c in cs[: TOP_ISSUES + 3]:
            print(f"  [score {c.score:.1f} / {len(c.items)}건 / {len(c.sources)}곳]")
            for it in c.items[:6]:
                print(f"     - ({it.source}) {it.title}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "collect":
        from .collect import collect
        collect()
    elif cmd == "day":
        from .pipeline import build_day
        build_day(_date_arg(args))
    elif cmd == "site":
        from .build import build_site
        build_site()
    elif cmd == "verify":
        return verify()
    elif cmd == "clusters":
        show_clusters(_date_arg(args))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
