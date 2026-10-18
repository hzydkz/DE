"""경로, 설정, KST 날짜 창 같은 공통 유틸."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
SITE_DIR = ROOT / "site"
SOURCES_FILE = ROOT / "sources.yaml"

KST = timezone(timedelta(hours=9))

# 분야당 남길 이슈 수, 이슈당 링크 수
TOP_ISSUES = int(os.environ.get("BRIEFING_TOP_ISSUES", "15"))
MAX_LINKS = 5


@dataclass
class Item:
    """수집된 기사 1건. description 은 요약 입력으로만 쓰고 저장·게시하지 않는다."""

    title: str
    url: str
    source: str  # 매체명 (표시용)
    source_id: str  # sources.yaml 의 id
    category: str
    published: str  # ISO8601 (UTC)
    description: str = ""
    weight: float = 1.0  # 트렌드 검색량, HN points 등 화제성 가중치

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Cluster:
    items: list[Item] = field(default_factory=list)
    score: float = 0.0

    @property
    def sources(self) -> set[str]:
        return {it.source for it in self.items}


def load_config() -> dict:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["sources"] = [s for s in cfg["sources"] if s.get("enabled", True)]
    return cfg


def kst_yesterday(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(KST) - timedelta(days=1)).date()


def day_window(d: date) -> tuple[datetime, datetime]:
    """d 의 KST 0시~24시를 UTC datetime 구간 [start, end) 으로."""
    start = datetime(d.year, d.month, d.day, tzinfo=KST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    tmp.replace(path)
