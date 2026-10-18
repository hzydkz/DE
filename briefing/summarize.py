"""AI 요약. 제공자는 환경변수로 교체하고, 실패하면 None 을 돌려 제목+링크만 쓰게 한다.

BRIEFING_LLM_PROVIDER:
  gemini (기본) - Google Gemini API 무료 티어(OpenAI 호환 엔드포인트). GEMINI_API_KEY 필요
  custom        - 다른 OpenAI 호환 무료 API (Groq, OpenRouter 등).
                  BRIEFING_LLM_URL, BRIEFING_LLM_API_KEY, BRIEFING_LLM_MODEL 필요
  none          - 요약 안 함
BRIEFING_LLM_MODEL: 모델 이름 (제공자 기본값을 덮어씀)

호출은 두 종류다.
  1) 선별(triage) 1회: 상위 후보 제목만 보고 음악인 이슈인지, 중요도(1~5), 같은 사건끼리 묶음을 판단
  2) 요약: 중요도순 정렬 후 맨 위부터 SUMMARY_BATCH 개씩. 한도에 걸리면 아래쪽만 요약 없이 남는다
키가 없으면 호출하지 않고 제목+링크만 쓴다. 무료 한도는 자주 바뀌므로 호출 사이 간격과 하루 상한을 둔다.
(GitHub Models 는 2026-07-30 종료되어 제거했다.)
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

from .common import Cluster

PROVIDERS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        # 최신 Flash 를 가리키는 별칭. 특정 버전이 필요하면 BRIEFING_LLM_MODEL 로 고정
        "model": "gemini-flash-latest",
    },
    "custom": {
        "url": os.environ.get("BRIEFING_LLM_URL", ""),
        "key_env": "BRIEFING_LLM_API_KEY",
        "model": "",
    },
}

DAILY_CALL_LIMIT = int(os.environ.get("BRIEFING_LLM_CALL_LIMIT", "15"))
MAX_INPUT_CHARS = int(os.environ.get("BRIEFING_LLM_MAX_INPUT_CHARS", "9000"))
# 무료 티어 분당 요청 한도(대개 10 RPM 안팎)를 넘지 않게 호출 사이 최소 간격(초)
MIN_CALL_INTERVAL = float(os.environ.get("BRIEFING_LLM_MIN_INTERVAL", "7"))
SUMMARY_BATCH = 4  # 한 번에 요약할 이슈 수. 작을수록 위쪽 이슈가 먼저 확실히 요약된다
HEADLINES_PER_CLUSTER = 8
DESCRIPTION_CHARS = 250

TRIAGE_PROMPT = """너는 음악 뉴스 편집장이다. 어제 수집된 기사 묶음 후보 목록을 보고 각 후보를 판정한다.
- music: 가수·아이돌·래퍼·밴드·프로듀서·작곡가·DJ 등 음악인, 또는 그들의 음악 활동(발매, 공연·투어, 차트,
  수상, 계약·소속사, 논란, 사건사고, 별세 등)에 관한 이슈면 true. 배우·드라마·영화·예능, 방송사 경영,
  음악과 무관한 사회·경제 뉴스면 false. 음악인이 주인공이면 예능 출연이어도 true.
- importance: 1~5 정수.
  5 = 업계 전체가 주목할 사건 (대형 아티스트의 사망·은퇴·해체·법적 문제, 역대 기록, 대형 투어·컴백 발표)
  4 = 유명 아티스트의 주요 발매·수상·차트 성과·논란
  3 = 일반적인 발매·공연·활동 소식
  2 = 소소한 근황
  1 = 홍보성 기사, 가십
  보도량(기사·매체 수)도 참고하되 그것만으로 정하지 마라.
- same_as: 다른 후보와 같은 사건·같은 인물의 같은 이슈면 그 후보 id(번호가 더 작은 쪽), 아니면 null.
  언어가 달라도(한국어 기사와 영어 기사) 같은 사건이면 묶는다.
반드시 아래 JSON 형식으로만, 모든 후보에 대해 답하라:
{"items": [{"id": "c0", "music": true, "importance": 3, "same_as": null}]}"""

SUMMARY_PROMPT = """너는 음악 뉴스 브리핑 편집자다. 각 이슈마다 여러 매체의 헤드라인과 짧은 설명이 주어진다.
규칙:
- 입력에 없는 사실을 추가하지 마라. 추측·배경지식 보충 금지.
- 수치, 인명, 곡·앨범명, 날짜, 장소는 입력에 적힌 그대로 쓴다.
- 의견·평가·감정 표현 없이 사실만 쓴다.
- 영어 등 외국어 입력이어도 title 과 summary 는 반드시 한국어로 쓴다(인명·곡명은 원어 병기 가능).
- title: 여러 헤드라인을 종합해 사건의 핵심을 담은 한국어 제목 한 줄(40자 이내).
  입력 헤드라인 하나를 그대로 베끼지 말고, "누가 무엇을 했다" 식으로 새로 쓴다.
  [속보]·[단독] 같은 말머리, 따옴표 인용 위주의 낚시성 표현은 쓰지 않는다.
- summary: 4~6문장으로 구체적으로 쓴다. 순서는
  ① 누가 무엇을 했는지(핵심 한 문장) → ② 날짜·수치·곡명·장소·관계자 등 구체적 사실 →
  ③ 입력에 있을 때만 배경, 이유, 반응, 향후 일정.
  여러 매체가 서로 다른 세부를 전하면 모두 모아서 쓴다. 입력이 빈약하면 확인되는 만큼만 짧게 쓴다.
반드시 아래 JSON 형식으로만 답하라:
{"issues": [{"id": "<입력 id 그대로>", "title": "...", "summary": "..."}]}"""


class Summarizer:
    def __init__(self):
        self.provider = os.environ.get("BRIEFING_LLM_PROVIDER", "gemini").lower()
        self.calls = 0
        self.exhausted = False  # 한도 초과(429) 이후로는 더 부르지 않는다
        self._last_call = 0.0
        self.errors: list[str] = []
        conf = PROVIDERS.get(self.provider)
        self.key = os.environ.get(conf["key_env"]) if conf else None
        self.conf = conf
        self.model = os.environ.get("BRIEFING_LLM_MODEL") or (conf["model"] if conf else None)

    @property
    def enabled(self) -> bool:
        return bool(self.conf and self.key and self.conf["url"] and self.model)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.enabled else "none"

    def triage(self, clusters: list[Cluster]) -> dict[str, dict]:
        """{"c0": {"music", "importance", "same_as"}}. 실패하면 {} (호출 측이 코드 순위를 그대로 쓴다)."""
        if not self.enabled or not clusters:
            return {}
        ids = {f"c{i}" for i in range(len(clusters))}
        lines = []
        for i, c in enumerate(clusters):
            heads = " / ".join(it.title[:90] for it in c.items[:3])
            lines.append(f"[c{i}] 보도 {len(c.items)}건·매체 {len(c.sources)}곳 | {heads}")
        user = "\n".join(lines)[:MAX_INPUT_CHARS * 2]
        return self._ask(TRIAGE_PROMPT, user, lambda p: _validate_triage(p, ids), "선별") or {}

    def summarize(self, clusters: list[Cluster]) -> dict[str, dict]:
        """{cluster_id: {"title", "summary"}}. 순서대로(맨 위부터) 부르고, 실패한 묶음은 결과에 없다."""
        if not self.enabled or not clusters:
            return {}
        result: dict[str, dict] = {}
        for batch in _batches(clusters):
            if self.exhausted:
                break
            ids = {cid for cid, _ in batch}
            user = "\n\n".join(block for _, block in batch)
            label = f"요약 {batch[0][0]}~{batch[-1][0]}"
            result.update(self._ask(SUMMARY_PROMPT, user, lambda p: _validate(p, ids), label) or {})
        return result

    def _ask(self, system: str, user: str, validate, label: str):
        for attempt in range(2):  # JSON 파싱·검증 실패 시 1회 재시도
            if self.exhausted:
                return None
            if self.calls >= DAILY_CALL_LIMIT:
                self.errors.append("일일 호출 상한 도달")
                self.exhausted = True
                return None
            try:
                out = validate(self._call(system, user))
                if out:
                    return out
                raise ValueError("유효한 결과 없음")
            except Exception as e:  # noqa: BLE001
                msg = f"{label} 실패({attempt + 1}회차): {type(e).__name__}: {e}"[:300]
                print(msg, file=sys.stderr)
                self.errors.append(msg)
                if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 429:
                    self.exhausted = True  # 한도 초과는 재시도해도 소용없다
                    return None
                time.sleep(3)
        return None

    def _call(self, system: str, user: str) -> dict:
        wait = self._last_call + MIN_CALL_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.calls += 1
        self._last_call = time.monotonic()
        r = requests.post(
            self.conf["url"],
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                     "Accept": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": 0.2,
                "max_tokens": 8000,  # 사고(thinking) 토큰을 쓰는 모델도 본문이 잘리지 않게
                "response_format": {"type": "json_object"},
            },
            timeout=120,
            allow_redirects=False,  # 리다이렉트를 따라가면 POST 가 GET 으로 바뀌어 엉뚱한 응답을 받는다
        )
        if r.is_redirect:
            raise ValueError(f"HTTP {r.status_code} 리다이렉트 → {r.headers.get('location')}")
        r.raise_for_status()
        try:
            choice = r.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("출력 토큰 한도에서 잘림")
            content = choice["message"]["content"]
            return json.loads(_strip_fence(content or ""))
        except (ValueError, KeyError, IndexError, TypeError) as e:
            # 원인 파악용: 응답 앞부분만 남긴다 (입력 기사 내용은 남기지 않음)
            ctype = r.headers.get("content-type", "")
            raise ValueError(f"{type(e).__name__}; HTTP {r.status_code} {ctype}; body={r.text[:300]!r}") from e


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s


def _validate(parsed: dict, ids: set[str]) -> dict[str, dict]:
    out = {}
    for row in parsed.get("issues", []) if isinstance(parsed, dict) else []:
        if not isinstance(row, dict):
            continue
        cid, title, summary = row.get("id"), row.get("title"), row.get("summary")
        if cid in ids and _is_korean(summary):
            # 한국어가 아닌 제목은 버리고 대표 헤드라인으로 대체한다
            title = title.strip()[:80] if _is_korean(title) else ""
            out[cid] = {"title": title, "summary": summary.strip()}
    return out


def _validate_triage(parsed: dict, ids: set[str]) -> dict[str, dict]:
    out = {}
    for row in parsed.get("items", []) if isinstance(parsed, dict) else []:
        if not isinstance(row, dict) or row.get("id") not in ids:
            continue
        try:
            importance = max(1, min(5, int(row.get("importance", 3))))
        except (TypeError, ValueError):
            importance = 3
        same_as = row.get("same_as")
        out[row["id"]] = {
            "music": row.get("music") is not False,  # 애매하면 남긴다
            "importance": importance,
            "same_as": same_as if same_as in ids and same_as != row["id"] else None,
        }
    return out


def _is_korean(s) -> bool:
    return isinstance(s, str) and any("가" <= ch <= "힣" for ch in s)


def cluster_block(cid: str, c: Cluster) -> str:
    lines = [f"[id: {cid}] 보도 {len(c.items)}건, 매체 {len(c.sources)}곳"]
    for it in c.items[:HEADLINES_PER_CLUSTER]:
        line = f"- ({it.source}) {it.title}"
        if it.description:
            line += f" :: {it.description[:DESCRIPTION_CHARS]}"
        lines.append(line)
    return "\n".join(lines)


def _batches(clusters: list[Cluster]):
    """위에서부터 SUMMARY_BATCH 개(또는 글자 수 한도)씩 나눈다. id 는 c0, c1, ... (최종 순위)."""
    batch, size = [], 0
    for i, c in enumerate(clusters):
        block = cluster_block(f"c{i}", c)
        if batch and (len(batch) >= SUMMARY_BATCH or size + len(block) > MAX_INPUT_CHARS):
            yield batch
            batch, size = [], 0
        batch.append((f"c{i}", block[:MAX_INPUT_CHARS]))
        size += len(block)
    if batch:
        yield batch
