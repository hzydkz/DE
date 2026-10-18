# 데일리 이슈 브리핑

전날(KST 0~24시) 국내 종합·정치·경제·IT·해외·커뮤니티·음악 이슈를 묶어서 AI 요약과 원문 링크로 보여주는 정적 사이트입니다. 운영비는 0원입니다.

- 수집: RSS + 공식 무료 API (`sources.yaml`). 2시간마다 수집해 누적 (피드가 최근 몇 시간 분량만 보여 주므로)
- 묶기·순위: 제목 문자 bigram 유사도 (LLM 없음)
- 요약: Google Gemini API 무료 티어 (직접 발급한 키 필요). 키가 없거나 실패하면 제목+링크만
- 배포: 매일 KST 05:17 시작 → GitHub Pages

## 처음 설정 (한 번만)
1. **Settings → Pages → Build and deployment → Source: GitHub Actions** 로 바꾼다.
2. **Actions → daily-briefing → Run workflow** (mode: build) 로 수동 1회 실행한다.
   첫날은 버퍼가 비어 있어 기사가 적다. 2시간 간격 수집이 하루 쌓인 다음 날부터 정상이다.
3. AI 요약을 켜려면: Google AI Studio(aistudio.google.com)에서 무료 API 키를 발급받아
   **Settings → Secrets and variables → Actions → New repository secret** 에 `GEMINI_API_KEY` 로 넣는다.
   결제 수단을 등록하지 않은 프로젝트의 키를 써야 과금될 일이 없다. 무료 티어는 입력이 Google 학습에 쓰일 수 있다(공개 뉴스라 실질 문제는 적음).
   키가 없으면 요약 없이 제목+링크로만 생성된다.
4. (선택) 다른 OpenAI 호환 무료 API(Groq, OpenRouter 등)를 쓰려면 Variables 에 `BRIEFING_LLM_PROVIDER=custom`,
   `BRIEFING_LLM_URL`(…/chat/completions), `BRIEFING_LLM_MODEL` 을, Secret 에 `BRIEFING_LLM_API_KEY` 를 넣는다.
5. (선택) YouTube 인기 동영상을 쓰려면 무료 YouTube Data API 키를 `YOUTUBE_API_KEY` 시크릿으로 넣는다.

## 로컬 실행
```sh
pip install -r requirements.txt pytest
python -m pytest -q
python -m briefing verify          # 소스 점검
python -m briefing collect         # 수집
python -m briefing clusters        # 묶음 확인 (요약 없음)
BRIEFING_LLM_PROVIDER=none python -m briefing day && python -m briefing site
```
