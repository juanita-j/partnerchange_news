# daily-exec-news

네이버 뉴스 API로 **임원인사·조직개편** 기사를 수집하고, OpenAI로 요약한 뒤 **일일 브리핑 메일** HTML을 만드는 스크립트 모음입니다. GitHub Actions(평일 다회 Gmail)와 로컬(Cursor + WORKS MCP 등)에서 함께 쓸 수 있습니다.

## 빠른 시작

```bash
pip install -r requirements.txt python-dotenv
cp .env.example .env
# Windows: copy .env.example .env
# .env 에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, OPENAI_API_KEY 필수 입력
python run_briefing_pipeline.py
```

생성물: `news_raw.json` → `news_summary.json` → `email_partners.json`

## 인수인계·운영

**[docs/HANDOFF.md](docs/HANDOFF.md)** 에 파이프라인 표, 환경 변수, Actions, Cursor 규칙, 체크리스트를 한 페이지로 정리해 두었습니다.

## 기타 문서

| 문서 | 내용 |
|------|------|
| [작업스케줄러_설정방법.md](작업스케줄러_설정방법.md) | Windows 작업 스케줄러 |
| [docs/뉴스메일_미수신_확인체크리스트.md](docs/뉴스메일_미수신_확인체크리스트.md) | 미수신 점검 |
| [GIT_적용방법.md](GIT_적용방법.md) | Git 반영 방법 |

## 요구 사항

- Python 3.12 권장
- 의존성: `requirements.txt`와 `python-dotenv`
