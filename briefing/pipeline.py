"""버퍼 → 전날 창 필터 → 묶기·코드 순위 → LLM 선별(음악인 이슈만, 같은 사건 병합,
중요한 순서) → 위에서부터 요약 → data/YYYY-MM-DD.json."""

from __future__ import annotations

from datetime import date, datetime, timezone

from .cluster import cluster_items, pick_links
from .collect import BUFFER_FILE, items_in_window
from .common import (DATA_DIR, MAX_LINKS, TOP_ISSUES, Cluster, day_window, load_config, read_json,
                     write_json)
from .summarize import Summarizer


def failed_sources(cfg: dict, status: dict, start: datetime) -> list[dict]:
    """창 시작 이후 한 번도 성공하지 못한 소스 = 이번 브리핑에서 통째로 빠진 소스.

    하루 중 일부 수집만 실패한 경우는 잡음이 많아 표시하지 않는다.
    """
    out = []
    for src in cfg["sources"]:
        st = status.get(src["id"], {})
        if st.get("skipped"):
            continue
        if not st.get("last_ok") or st["last_ok"] < start.isoformat():
            out.append({"id": src["id"], "name": src["name"], "error": st.get("last_error", "수집 기록 없음")})
    return out


TRIAGE_CANDIDATES = 40  # 선별에 보여 줄 코드 순위 상위 후보 수


def rank_issues(clusters: list[Cluster], summarizer: Summarizer) -> list[tuple[Cluster, str | None]]:
    """(클러스터, 선별 단계의 한국어 제목)을 LLM 선별 순서대로(음악인 이슈만, 같은 사건 병합).

    선별이 실패하면 코드 점수 순 그대로.
    """
    candidates = clusters[:TRIAGE_CANDIDATES]
    tri = summarizer.triage(candidates)
    if not tri:
        return [(c, None) for c in candidates]
    by_id = {f"c{i}": c for i, c in enumerate(candidates)}
    ranked = {cid: Cluster(items=list(by_id[cid].items), score=by_id[cid].score) for cid in tri["order"]}
    for src, dst in tri["merge"].items():
        ranked[dst].items.extend(by_id[src].items)
        ranked[dst].score += by_id[src].score
    return [(ranked[cid], tri["titles"].get(cid)) for cid in tri["order"]]


def build_day(d: date) -> dict:
    cfg = load_config()
    buf = read_json(BUFFER_FILE, {"items": {}, "status": {}})
    start, end = day_window(d)
    items = items_in_window(buf, start, end)
    summarizer = Summarizer()

    categories = []
    for cat in cfg["categories"]:
        cat_items = [it for it in items if it.category == cat["key"]]
        ranked = rank_issues(cluster_items(cat_items), summarizer)[:TOP_ISSUES]
        summaries = summarizer.summarize([c for c, _ in ranked])
        issues = []
        for i, (c, triage_title) in enumerate(ranked):
            s = summaries.get(f"c{i}")
            issues.append({
                # 요약 제목 → 선별 단계 한국어 제목 → 대표 헤드라인 순으로
                "title": (s and s["title"]) or triage_title or c.items[0].title,
                "summary": s["summary"] if s else None,
                "ai": bool(s),
                "article_count": len(c.items),
                "source_count": len(c.sources),
                # 기사 제목·링크·매체명만 게시한다. 설명문(기사 일부)은 저장하지 않는다.
                "links": [{"title": it.title, "url": it.url, "source": it.source}
                          for it in pick_links(c, MAX_LINKS)],
            })
        categories.append({"key": cat["key"], "name": cat["name"],
                           "collected": len(cat_items), "issues": issues})
        print(f"{cat['name']}: 기사 {len(cat_items)}건 → 이슈 {len(issues)}개, 요약 {len(summaries)}개")
        for n, it in enumerate(issues, 1):  # 실행 로그로 품질 확인용 (자체 요약만, 기사 설명문 아님)
            print(f"  {n:>2}. ({it['article_count']}건) {it['title']} — {(it['summary'] or '(요약 없음)')[:150]}")

    result = {
        "date": d.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": summarizer.label,
        "llm_calls": summarizer.calls,
        "llm_errors": summarizer.errors,
        "failed_sources": failed_sources(cfg, buf["status"], start),
        "categories": categories,
    }
    write_json(DATA_DIR / f"{d.isoformat()}.json", result)
    print(f"LLM 호출 {summarizer.calls}회 ({summarizer.label}), 실패 소스 {len(result['failed_sources'])}개")
    return result
