import json
from datetime import date

import pytest
import requests

import briefing.build as build
import briefing.collect as collect
import briefing.pipeline as pipeline
from briefing.collect import is_music
from briefing.common import Item
from briefing.summarize import Summarizer, _validate, _validate_triage

# KST 2026-10-17 = UTC 2026-10-16T15:00 ~ 2026-10-17T15:00
ARTICLES = [
    # (제목, 매체, 시각)
    ("뉴진스 정규 2집 컴백 확정…11월 발매", "연합뉴스", "2026-10-17T01:00:00+00:00"),
    ("뉴진스, 정규 2집으로 11월 컴백", "스포츠서울", "2026-10-17T01:30:00+00:00"),
    ("NewJeans confirm November comeback with second album", "Soompi", "2026-10-17T02:00:00+00:00"),
    ("배우 김OO 드라마 주연 확정", "연합뉴스", "2026-10-17T03:00:00+00:00"),
    ("오아시스 투어 오프닝 밴드 발표", "NME", "2026-10-17T04:00:00+00:00"),
    ("창 밖 기사 <script>", "한겨레", "2026-10-17T16:00:00+00:00"),
]


def _setup(tmp_path, monkeypatch):
    data, site = tmp_path / "data", tmp_path / "site"
    buf_file = tmp_path / "raw.json"
    for mod in (pipeline, build):
        monkeypatch.setattr(mod, "DATA_DIR", data, raising=False)
    monkeypatch.setattr(build, "SITE_DIR", site)
    monkeypatch.setattr(pipeline, "BUFFER_FILE", buf_file)
    monkeypatch.setattr("briefing.summarize.time.sleep", lambda s: None)
    items = {
        str(i): dict(title=t, url=f"https://x.example/{i}", source=s, source_id="yna-ent",
                     category="music", published=ts, description="설명문은 게시되면 안 됨", weight=1.0)
        for i, (t, s, ts) in enumerate(ARTICLES)
    }
    status = {"yna-ent": {"last_ok": "2026-10-17T20:00:00+00:00"}}
    buf_file.write_text(json.dumps({"items": items, "status": status}))
    return data, site


def _llm(monkeypatch, handler):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def fake_call(self, system, user):
        calls.append((system, user))
        return handler(system, user)

    monkeypatch.setattr(Summarizer, "_call", fake_call)
    return calls


def _music(result):
    return next(c for c in result["categories"] if c["key"] == "music")


def test_day_and_site_without_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "none")
    data, site = _setup(tmp_path, monkeypatch)
    result = pipeline.build_day(date(2026, 10, 17))
    music = _music(result)
    assert music["collected"] == 5
    top = music["issues"][0]
    assert top["ai"] is False and top["summary"] is None
    assert "뉴진스" in top["title"]
    assert "설명문" not in (data / "2026-10-17.json").read_text()
    failed_ids = {s["id"] for s in result["failed_sources"]}
    assert "yna-ent" not in failed_ids and "pitchfork" in failed_ids

    build.build_site()
    index = (site / "index.html").read_text()
    assert "뉴진스" in index and "AI 요약</span>" not in index and "API 키 미설정" in index
    assert 'class="tabs"' not in index  # 분야가 하나면 탭을 그리지 않는다
    assert 'href="../style.css"' in (site / "2026-10-17" / "index.html").read_text()
    assert (site / "sources" / "index.html").exists()


def _ids(user):
    return [line.split("]")[0].split(":")[-1].strip().lstrip("[") for line in user.splitlines()
            if line.startswith("[")]


def test_triage_merges_filters_and_orders(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def handler(system, user):
        if "편집장" in system:  # 선별: 후보 제목으로 판정
            ids = {}
            for line in user.splitlines():
                ids[line.split("|", 1)[1]] = line[1:line.index("]")]
            find = lambda word: next(cid for title, cid in ids.items() if word in title)  # noqa: E731
            # 드라마 기사는 order 에서 빼고, 영어 NewJeans 기사는 뉴진스 이슈로 합치고, 오아시스를 맨 위로
            return {"order": [find("오아시스"), find("뉴진스")], "merge": {find("NewJeans"): find("뉴진스")},
                    "titles": {find("오아시스"): "오아시스, 투어 오프닝 밴드 공개"}}
        return {"issues": [{"id": cid, "title": f"요약 제목 {cid}", "summary": "요약했다."}
                           for cid in _ids(user)]}

    calls = _llm(monkeypatch, handler)
    issues = _music(pipeline.build_day(date(2026, 10, 17)))["issues"]
    assert len(issues) == 2
    assert "오아시스" in issues[0]["links"][0]["title"]
    assert issues[1]["article_count"] == 3 and issues[1]["source_count"] == 3
    assert all(i["ai"] for i in issues)
    assert len(calls) == 2  # 선별 1회 + 요약 1회


def test_triage_title_used_when_summary_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def handler(system, user):
        if "편집장" in system:
            cid = next(line[1:line.index("]")] for line in user.splitlines() if "Oasis" in line or "오아시스" in line)
            return {"order": [cid], "merge": {}, "titles": {cid: "오아시스, 투어 오프닝 밴드 공개"}}
        return {"issues": []}

    _llm(monkeypatch, handler)
    issue = _music(pipeline.build_day(date(2026, 10, 17)))["issues"][0]
    assert issue["title"] == "오아시스, 투어 오프닝 밴드 공개" and issue["ai"] is False


def test_summaries_go_top_down_and_stop_on_rate_limit(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("briefing.summarize.SUMMARY_BATCH", 1)
    summary_calls = []

    def handler(system, user):
        if "편집장" in system:
            return {"order": []}  # 선별 결과 없음 → 코드 순위 그대로
        ids = _ids(user)
        summary_calls.append(ids)
        if len(summary_calls) >= 2:
            resp = requests.Response()
            resp.status_code = 429
            raise requests.HTTPError(response=resp)
        return {"issues": [{"id": cid, "title": "제목", "summary": "요약했다."} for cid in ids]}

    _llm(monkeypatch, handler)
    result = pipeline.build_day(date(2026, 10, 17))
    issues = _music(result)["issues"]
    # 위에서부터, 429 면 한 번 기다렸다 재시도하고 또 429 면 더 부르지 않음
    assert summary_calls == [["c0"], ["c1"], ["c1"]]
    assert issues[0]["ai"] is True
    assert all(not i["ai"] and i["links"] for i in issues[1:])
    assert result["llm_errors"]


def test_llm_failure_retries_once_then_falls_back(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = _llm(monkeypatch, lambda system, user: {"order": []} if "편집장" in system else {"issues": []})
    result = pipeline.build_day(date(2026, 10, 17))
    issue = _music(result)["issues"][0]
    assert issue["ai"] is False and issue["summary"] is None
    assert issue["title"] and issue["links"]
    assert len([c for c in calls if "편집장" not in c[0]]) >= 2  # 첫 묶음 요약 1회 재시도
    assert result["llm_errors"]


def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = Summarizer()
    assert not s.enabled and s.label == "none"


def test_validate_rejects_unknown_ids_and_non_korean():
    out = _validate({"issues": [{"id": "c9", "summary": "요약"}, {"id": "c0", "summary": " "},
                                {"id": "c1", "title": "한은 금리 동결", "summary": "동결했다."},
                                {"id": "c2", "title": "Fed holds rates", "summary": "연준이 동결했다."},
                                {"id": "c3", "title": "제목", "summary": "Fed held rates."}]},
                    {"c0", "c1", "c2", "c3"})
    assert out == {"c1": {"title": "한은 금리 동결", "summary": "동결했다."},
                   "c2": {"title": "", "summary": "연준이 동결했다."}}


def test_validate_triage_ignores_bad_refs():
    ids = {"c0", "c1", "c2"}
    out = _validate_triage({"order": ["c1", "c9", "c1", "c0"],
                            "merge": {"c2": "c1", "c0": "c1", "c7": "c0", "c2x": "c1"}}, ids)
    assert out == {"order": ["c1", "c0"], "merge": {"c2": "c1"}, "titles": {}}
    assert _validate_triage({"order": []}, ids) is None
    assert _validate_triage({"items": []}, ids) is None


@pytest.mark.parametrize("title,expected", [
    ("뉴진스 컴백 확정", True), ("방탄소년단 월드투어 매진", True),
    ("Liam Gallagher says Fontaines D.C. are not good enough for Oasis tour", True),
    ("KBS 사장 후보 3명 압축", False), ("배우 김OO 드라마 캐스팅", False), ("삼성그룹 인사", False),
])
def test_music_keyword_filter(title, expected):
    assert is_music(Item(title, "u", "s", "s", "music", "2026")) is expected


def test_normalize_url():
    assert collect.normalize_url("http://www.a.com/x/?utm_source=y&id=1") == "https://a.com/x?id=1"
