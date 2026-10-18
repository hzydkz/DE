# 데일리 이슈 브리핑

전날(KST 0~24시) 국내 종합·정치·경제·IT·해외·커뮤니티·음악 이슈를 묶어서 AI 요약과 원문 링크로 보여주는 정적 사이트입니다. 운영비는 0원입니다.

- 수집: RSS + 공식 무료 API (`sources.yaml`). KST 11:17 / 17:17 / 23:17 / 05:17 하루 4회 수집해 누적
- 묶기·순위: 제목 문자 bigram 유사도 (LLM 없음)
- 요약: GitHub Models 무료 한도 (Actions 의 `GITHUB_TOKEN`, 키 불필요). 실패하면 제목+링크만
- 배포: 매일 KST 05:17 시작 → GitHub Pages

## 처음 설정 (한 번만)
1. **Settings → Pages → Build and deployment → Source: GitHub Actions** 로 바꾼다.
2. **Actions → daily-briefing → Run workflow** (mode: build) 로 수동 1회 실행한다.
   첫날은 버퍼가 비어 있어 기사가 적다. 하루 4회 수집이 쌓인 다음 날부터 정상이다.
3. (선택) YouTube 인기 동영상을 쓰려면 무료 YouTube Data API 키를 `YOUTUBE_API_KEY` 시크릿으로 넣는다.
4. (선택) 요약 제공자를 바꾸려면 Variables 에 `BRIEFING_LLM_PROVIDER`(github/gemini/none), `BRIEFING_LLM_MODEL` 을 넣는다. gemini 는 `GEMINI_API_KEY` 시크릿 필요.

## 로컬 실행
```sh
pip install -r requirements.txt pytest
python -m pytest -q
python -m briefing verify          # 소스 점검
python -m briefing collect         # 수집
python -m briefing clusters        # 묶음 확인 (요약 없음)
BRIEFING_LLM_PROVIDER=none python -m briefing day && python -m briefing site
```
