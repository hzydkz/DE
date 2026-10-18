"""중복 제거 → 이슈 묶기 → 순위. LLM 없이 코드로만 한다.

유사도는 제목 문자 bigram 의 IDF 가중 Dice 계수. 한국어 형태소 분석기 없이
"이재명·대통령·회담" 같은 고유명사 조각이 겹치는지를 본다. 흔한 조각
("대통령", "정부")은 IDF 로 깎아서 서로 다른 사건이 묶이는 걸 줄인다.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .common import Cluster, Item

SIM_THRESHOLD = 0.42  # 같은 사건으로 볼 최소 유사도 (3단계 확인에서 조정)
SEED_THRESHOLD = 0.25  # 체인처럼 번지는 걸 막기 위해 클러스터 첫 기사와도 이만큼은 닮아야 함
DUP_THRESHOLD = 0.85  # 같은 매체에서 이 이상 닮으면 중복(속보→본기사 등)으로 보고 하나만 남김

_BRACKET_RE = re.compile(r"[\[\(【<〈「『][^\]\)】>〉」』]{0,12}[\]\)】>〉」』]")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_title(title: str) -> str:
    t = _BRACKET_RE.sub(" ", title)  # [속보] (종합) 【단독】 등
    t = _NON_WORD_RE.sub(" ", t.lower())
    return " ".join(t.split())


def shingles(title: str) -> frozenset[str]:
    grams = set()
    for tok in normalize_title(title).split():
        if len(tok) == 1:
            continue
        if tok.isascii():
            grams.add(tok)  # 영문은 단어 단위
        else:
            grams.update(tok[i : i + 2] for i in range(len(tok) - 1))
    return frozenset(grams)


class Similarity:
    def __init__(self, sets: list[frozenset[str]]):
        df = Counter(g for s in sets for g in s)
        n = max(len(sets), 1)
        self.idf = {g: math.log(1 + n / c) for g, c in df.items()}

    def mass(self, s: frozenset[str]) -> float:
        return sum(self.idf.get(g, 0.0) for g in s)

    def __call__(self, a: frozenset[str], b: frozenset[str]) -> float:
        if not a or not b:
            return 0.0
        inter = sum(self.idf.get(g, 0.0) for g in a & b)
        denom = self.mass(a) + self.mass(b)
        return 2 * inter / denom if denom else 0.0


def dedupe(items: list[Item], sim: Similarity, sets: dict[int, frozenset[str]]) -> list[Item]:
    """같은 매체가 거의 같은 제목으로 여러 번 낸 기사는 가장 이른 것 하나만."""
    kept: list[Item] = []
    by_source: dict[str, list[Item]] = {}
    for it in sorted(items, key=lambda x: x.published):
        same = by_source.setdefault(it.source, [])
        if any(sim(sets[id(it)], sets[id(o)]) >= DUP_THRESHOLD for o in same):
            continue
        same.append(it)
        kept.append(it)
    return kept


def cluster_items(items: list[Item]) -> list[Cluster]:
    sets = {id(it): shingles(it.title) for it in items}
    sim = Similarity(list(sets.values()))
    items = dedupe(items, sim, sets)

    clusters: list[Cluster] = []
    for it in sorted(items, key=lambda x: x.published):
        s = sets[id(it)]
        best, best_sim = None, 0.0
        for c in clusters:
            if sim(s, sets[id(c.items[0])]) < SEED_THRESHOLD:
                continue
            m = max(sim(s, sets[id(o)]) for o in c.items)
            if m > best_sim:
                best, best_sim = c, m
        if best is not None and best_sim >= SIM_THRESHOLD:
            best.items.append(it)
        else:
            clusters.append(Cluster(items=[it]))

    for c in clusters:
        # 보도량(가중) × 출처 다양성
        c.score = sum(it.weight for it in c.items) * len(c.sources)
        c.items.sort(key=lambda o: _centrality(o, c, sim, sets), reverse=True)
    clusters.sort(key=lambda c: (c.score, max(i.published for i in c.items)), reverse=True)
    return clusters


def _centrality(it: Item, c: Cluster, sim: Similarity, sets) -> float:
    """클러스터 안에서 다른 기사들과 가장 닮은 기사를 대표 기사로."""
    if len(c.items) == 1:
        return 0.0
    return sum(sim(sets[id(it)], sets[id(o)]) for o in c.items if o is not it)


def pick_links(c: Cluster, limit: int) -> list[Item]:
    """매체가 겹치지 않게 먼저 하나씩, 남으면 나머지로 채운다."""
    seen, first, rest = set(), [], []
    for it in c.items:
        (rest if it.source in seen else first).append(it)
        seen.add(it.source)
    return (first + rest)[:limit]
