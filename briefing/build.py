"""data/*.json → 정적 HTML (site/)."""

from __future__ import annotations

import shutil
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import DATA_DIR, KST, SITE_DIR, load_config, read_json

TEMPLATES = DATA_DIR.parent / "briefing" / "templates"
STATIC = DATA_DIR.parent / "briefing" / "static"


def _kst(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["kst"] = _kst
    return env


def build_site() -> None:
    days = sorted(p.stem for p in DATA_DIR.glob("????-??-??.json"))
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)
    shutil.copytree(STATIC, SITE_DIR, dirs_exist_ok=True)
    env = _env()
    cfg = load_config()

    def write(rel: str, template: str, **ctx) -> None:
        out = SITE_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        root = "../" * rel.count("/")
        out.write_text(env.get_template(template).render(root=root or "./", **ctx), encoding="utf-8")

    for i, day in enumerate(days):
        data = read_json(DATA_DIR / f"{day}.json", {})
        nav = {"prev": days[i - 1] if i > 0 else None, "next": days[i + 1] if i + 1 < len(days) else None}
        write(f"{day}/index.html", "day.html", d=data, nav=nav)
        if i == len(days) - 1:
            write("index.html", "day.html", d=data, nav=nav)
    if not days:
        write("index.html", "empty.html")
    write("archive/index.html", "archive.html", days=list(reversed(days)))
    write("sources/index.html", "sources.html", cfg=cfg)
    (SITE_DIR / ".nojekyll").touch()
    print(f"사이트 생성: {len(days)}일치 → {SITE_DIR}")
