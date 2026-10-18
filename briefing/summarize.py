"""AI 요약. 제공자는 환경변수로 교체하고, 실패하면 None 을 돌려 제목+링크만 쓰게 한다.

BRIEFING_LLM_PROVIDER:
  github (기본) - GitHub Models. Actions 의 GITHUB_TOKEN(permissions: models: read)으로 무료 호출
  gemini        - Google Gemini API 무료 티어. GEMINI_API_KEY 필요
  none          - 요약 안 함
BRIEFING_LLM_MODEL: 모델 이름 (제공자 기본값을 덮어씀)

GitHub Models 무료 한도(문서 기준, 바뀔 수 있음): 저티어 모델 하루 150회,
요청당 입력 8,000 / 출력 4,000 토큰. 그래서 분야당 한 번 묶어 부르고,
입력이 크면 클러스터를 나눠 여러 번 부른다.
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

from .common import Cluster

PROVIDERS = {
    "github": {
        "url": "https://models.github.ai/inference/chat/completions",
        "key_env": "GITHUB_TOKEN",
        "model": "openai/gpt-4o-mini",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
    },
}

DAILY_CALL_LIMIT = int(os.environ.get("BRIEFING_LLM_CALL_LIMIT", "30"))
# 8,000 토큰 입력 한도 대비 여유. 한국어는 대략 1자 ≈ 1토큰 이하라 보수적으로 잡는다.
MAX_INPUT_CHARS = 5500
HEADLINES_PER_CLUSTER = 5

SYSTEM_PROMPT = """너는 뉴스 브리핑 편집자다. 각 이슈마다 여러 매체의 헤드라인과 짧은 설명이 주어진다.
규칙:
- 입력에 없는 사실을 추가하지 마라. 추측·배경지식 보충 금지.
- 수치, 인명, 기관명은 입력에 적힌 그대로 쓴다.
- 의견·평가·감정 표현 없이 사실만 쓴다.
- 영어 등 외국어 입력도 한국어로 쓴다.
- title: 사건을 가리키는 중립적인 한국어 제목 한 줄(40자 이내).
- summary: 3~5문장. 입력이 빈약하면 확인되는 내용만 짧게 써도 된다.
반드시 아래 JSON 형식으로만 답하라:
{"issues": [{"id": "<입력 id 그대로>", "title": "...", "summary": "..."}]}"""


class Summarizer:
    def __init__(self):
        self.provider = os.environ.get("BRIEFING_LLM_PROVIDER", "github").lower()
        self.calls = 0
        self.errors: list[str] = []
        conf = PROVIDERS.get(self.provider)
        self.key = os.environ.get(conf["key_env"]) if conf else None
        self.conf = conf
        self.model = os.environ.get("BRIEFING_LLM_MODEL") or (conf["model"] if conf else None)

    @property
    def enabled(self) -> bool:
        return bool(self.conf and self.key)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.enabled else "none"

    def summarize(self, category_name: str, clusters: list[Cluster]) -> dict[str, dict]:
        """{cluster_id: {"title", "summary"}}. 실패한 클러스터는 결과에 없다."""
        if not self.enabled or not clusters:
            return {}
        result: dict[str, dict] = {}
        for batch in _batches(clusters):
            result.update(self._summarize_batch(category_name, batch))
        return result

    def _summarize_batch(self, category_name: str, batch: list[tuple[str, str]]) -> dict[str, dict]:
        ids = {cid for cid, _ in batch}
        user = f"분야: {category_name}\n\n" + "\n\n".join(block for _, block in batch)
        for attempt in range(2):  # JSON 파싱·검증 실패 시 1회 재시도
            if self.calls >= DAILY_CALL_LIMIT:
                self.errors.append("일일 호출 상한 도달")
                return {}
            try:
                parsed = self._call(user)
                out = _validate(parsed, ids)
                if out:
                    return out
                raise ValueError("유효한 요약 없음")
            except Exception as e:  # noqa: BLE001
                msg = f"{category_name} 요약 실패({attempt + 1}회차): {type(e).__name__}: {e}"[:300]
                print(msg, file=sys.stderr)
                self.errors.append(msg)
                if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 429:
                    return {}  # 한도 초과는 재시도해도 소용없다
                time.sleep(3)
        return {}

    def _call(self, user: str) -> dict:
        self.calls += 1
        r = requests.post(
            self.conf["url"],
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                     "Accept": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": user}],
                "temperature": 0.2,
                "max_tokens": 3500,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
            allow_redirects=False,  # 리다이렉트를 따라가면 POST 가 GET 으로 바뀌어 엉뚱한 응답을 받는다
        )
        if r.is_redirect:
            raise ValueError(f"HTTP {r.status_code} 리다이렉트 → {r.headers.get('location')}")
        r.raise_for_status()
        try:
            content = r.json()["choices"][0]["message"]["content"]
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
        if cid in ids and isinstance(summary, str) and summary.strip():
            out[cid] = {"title": (title or "").strip()[:80], "summary": summary.strip()}
    return out


def cluster_block(cid: str, c: Cluster) -> str:
    lines = [f"[id: {cid}] 보도 {len(c.items)}건, 매체 {len(c.sources)}곳"]
    for it in c.items[:HEADLINES_PER_CLUSTER]:
        line = f"- ({it.source}) {it.title}"
        if it.description:
            line += f" :: {it.description[:160]}"
        lines.append(line)
    return "\n".join(lines)


def _batches(clusters: list[Cluster]):
    """입력 글자 수 한도에 맞춰 클러스터를 나눈다. id 는 c0, c1, ... (분야 내 순위)."""
    batch, size = [], 0
    for i, c in enumerate(clusters):
        block = cluster_block(f"c{i}", c)
        if batch and size + len(block) > MAX_INPUT_CHARS:
            yield batch
            batch, size = [], 0
        batch.append((f"c{i}", block[:MAX_INPUT_CHARS]))
        size += len(block)
    if batch:
        yield batch
