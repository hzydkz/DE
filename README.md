# 데일리 음악 브리핑

전날(KST 0~24시) 국내·해외 음악인(가수·아이돌·래퍼·밴드·프로듀서 등) 이슈를 묶어서 중요도순으로 AI 요약과 원문 링크를 보여주는 정적 사이트입니다. 운영비는 0원입니다.

- 수집: RSS + 공식 무료 API (`sources.yaml`). 2시간마다 수집해 누적 (피드가 최근 몇 시간 분량만 보여 주므로)
- 묶기: 제목 문자 bigram 유사도 (LLM 없음)
- 선별·순위: AI가 상위 후보 40개의 제목만 보고 음악인 이슈만 골라 같은 사건끼리 합치고 중요한 순서로 나열
- 요약: 맨 위 이슈부터 4개씩. 무료 한도에 걸리면 아래쪽 이슈만 제목+링크로 남음
- AI: Google Gemini API 무료 티어 (직접 발급한 키 필요). 키가 없거나 실패하면 제목+링크만
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
5. (선택, 권장) 국내 기사 요약을 더 구체적으로 하려면 네이버 개발자센터(developers.naver.com)에서 애플리케이션을 등록해 '검색' API를 켜고
   `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 시크릿을 넣는다. 무료(하루 25,000회)이고 기사 요약문을 줘서 요약 재료가 늘어난다.
6. (선택) YouTube 인기 동영상을 쓰려면 무료 YouTube Data API 키를 `YOUTUBE_API_KEY` 시크릿으로 넣는다.

## 로컬 실행
```sh
pip install -r requirements.txt pytest
python -m pytest -q
python -m briefing verify          # 소스 점검
python -m briefing collect         # 수집
python -m briefing clusters        # 묶음 확인 (요약 없음)
BRIEFING_LLM_PROVIDER=none python -m briefing day && python -m briefing site
```
