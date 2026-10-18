# 데일리 음악 브리핑

매일 KST 05:17에 전날(KST 0~24시) 국내·해외 음악인 이슈만 묶어 중요도순 AI 요약 + 원문 링크로 보여주는 정적 사이트.
(2026-10-18 종합·정치·경제 등 다분야에서 음악 전용으로 방향 전환)
운영비 0원(GitHub Actions + GitHub Pages + Gemini API 무료 티어). GitHub Models 는 2026-07-30 종료됨.

## 규칙
- 기사 본문을 가져오거나 저장하지 않는다. RSS 제목·설명문만 요약 입력으로 쓰고, 설명문은 레포·사이트에 남기지 않는다(`data/*.json` 에는 제목·링크·매체명·자체 요약만).
- HTML 크롤링 금지. RSS와 공식 무료 API만 쓴다. 새 소스는 `sources.yaml` 에 추가하고 `python -m briefing verify` 로 확인.
- 비밀키는 커밋하지 않는다. GitHub Secrets/Variables 로만 넣는다.
- 유료 API를 추가하지 않는다. AI 요약이 실패해도 제목+링크로 페이지가 완성되어야 한다.
- 단계별로 작업하고, 단계가 끝나면 멈춰서 확인을 요청한다.

## 구조
- `briefing/collect.py` 수집 → `.cache/raw.json` 버퍼(Actions 캐시에 보관, 2시간마다 누적)
- `briefing/cluster.py` 중복 제거·클러스터링·코드 순위 (LLM 없음, 임계값은 파일 상단 상수)
- `briefing/pipeline.py` `rank_issues`: LLM 선별(음악인 이슈·중요도·같은 사건 병합) → 중요도순
- `briefing/summarize.py` LLM 요약 (제공자: `BRIEFING_LLM_PROVIDER` = gemini | custom | none, 키 없으면 호출 안 함)
- `briefing/pipeline.py` 전날 창 → `data/YYYY-MM-DD.json` (요약은 맨 위 이슈부터)
- `briefing/build.py` + `templates/` + `static/` → `site/`
- `.github/workflows/daily.yml` 스케줄 실행·커밋·Pages 배포, `verify.yml` 테스트·시험 실행

## 명령
- `python -m pytest -q`
- `python -m briefing verify | collect | clusters [날짜] | day [날짜] | site`
