import json
from datetime import date

import briefing.build as build
import briefing.collect as collect
import briefing.common as common
import briefing.pipeline as pipeline
from briefing.summarize import Summarizer, _validate


def _setup(tmp_path, monkeypatch):
    data, site = tmp_path / "data", tmp_path / "site"
    buf_file = tmp_path / "raw.json"
    for mod in (pipeline, build):
        monkeypatch.setattr(mod, "DATA_DIR", data, raising=False)
    monkeypatch.setattr(build, "SITE_DIR", site)
    monkeypatch.setattr(pipeline, "BUFFER_FILE", buf_file)
    items = {}
    # KST 2026-10-17 = UTC 2026-10-16T15:00 ~ 2026-10-17T15:00
    for i, (t, s, ts) in enumerate([
        ("한국은행 기준금리 연 2.50%로 동결", "연합뉴스", "2026-10-17T01:00:00+00:00"),
        ("한은 기준금리 2.50% 동결", "한겨레", "2026-10-17T02:00:00+00:00"),
        ("창 밖 기사 <script>", "한겨레", "2026-10-17T16:00:00+00:00"),
    ]):
        items[str(i)] = dict(title=t, url=f"https://x.example/{i}", source=s, source_id="yna-all",
                             category="general", published=ts, description="설명문은 게시되면 안 됨",
                             weight=1.0)
    buf_file.write_text(json.dumps({"items": items, "status": {"yna-all": {"last_ok": "2026-10-17T20:00:00+00:00"}}}))
    return data, site


def test_day_and_site_without_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "none")
    data, site = _setup(tmp_path, monkeypatch)
    result = pipeline.build_day(date(2026, 10, 17))
    general = next(c for c in result["categories"] if c["key"] == "general")
    assert general["collected"] == 2
    assert general["issues"][0]["ai"] is False and general["issues"][0]["summary"] is None
    assert "설명문" not in (data / "2026-10-17.json").read_text()
    # yna-all 은 성공 기록이 있고, 나머지 소스는 기록이 없으므로 실패로 표시
    failed_ids = {s["id"] for s in result["failed_sources"]}
    assert "yna-all" not in failed_ids and "bbc-world" in failed_ids

    build.build_site()
    index = (site / "index.html").read_text()
    assert "기준금리" in index and "AI 요약</span>" not in index
    assert (site / "2026-10-17" / "index.html").exists()
    assert 'href="../style.css"' in (site / "2026-10-17" / "index.html").read_text()
    assert (site / "sources" / "index.html").exists()


def test_llm_summary_used_and_fallback_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    _setup(tmp_path, monkeypatch)
    calls = []

    def fake_call(self, user):
        calls.append(user)
        return {"issues": [{"id": "c0", "title": "한은 금리 동결", "summary": "한은이 금리를 동결했다."}]}

    monkeypatch.setattr(Summarizer, "_call", fake_call)
    monkeypatch.setattr("briefing.summarize.time.sleep", lambda s: None)
    result = pipeline.build_day(date(2026, 10, 17))
    general = next(c for c in result["categories"] if c["key"] == "general")
    assert general["issues"][0]["ai"] is True
    assert general["issues"][0]["title"] == "한은 금리 동결"
    # 빈 분야는 호출하지 않는다 → 기사가 있는 '종합' 1회뿐
    assert len(calls) == 1


def test_llm_failure_retries_once_then_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    _setup(tmp_path, monkeypatch)
    calls = []

    def fake_call(self, user):
        calls.append(user)
        return {"issues": []}  # 스키마는 맞지만 쓸 요약이 없음

    monkeypatch.setattr(Summarizer, "_call", fake_call)
    monkeypatch.setattr("briefing.summarize.time.sleep", lambda s: None)
    result = pipeline.build_day(date(2026, 10, 17))
    issue = next(c for c in result["categories"] if c["key"] == "general")["issues"][0]
    assert len(calls) == 2
    assert issue["ai"] is False and issue["summary"] is None
    assert issue["title"] and issue["links"]
    assert result["llm_errors"]


def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.setenv("BRIEFING_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = Summarizer()
    assert not s.enabled and s.label == "none"


def test_validate_rejects_unknown_ids_and_empty():
    out = _validate({"issues": [{"id": "c9", "summary": "x"}, {"id": "c0", "summary": " "},
                                {"id": "c1", "title": "t", "summary": "ok"}]}, {"c0", "c1"})
    assert out == {"c1": {"title": "t", "summary": "ok"}}


def test_normalize_url():
    assert collect.normalize_url("http://www.a.com/x/?utm_source=y&id=1") == "https://a.com/x?id=1"
