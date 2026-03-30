# daily-exec-news (파트너 임원인사·조직개편 브리핑)

지정 파트너사·키워드 기준으로 네이버 뉴스에서 **임원인사·조직개편** 기사를 모으고, LLM으로 요약한 뒤 **일일 브리핑 HTML 메일**을 만듭니다. **GitHub Actions**에서는 Gmail로 발송하고, 로컬에서는 `email_partners.json` 생성 후 **WORKS(naver-works MCP)** 등으로 보낼 수 있습니다.

**인수인계·상세:** [docs/HANDOFF.md](docs/HANDOFF.md) (파이프라인, 트래킹·제외 기준, 체크리스트)

---

## 개요

- **입력:** 네이버 검색 API(뉴스), 제목·본문 필터(`send_exec_news_timed.py` 내 파트너사·키워드·노이즈 규칙)
- **처리:** OpenAI 요약(`summarize_exec_news_llm.py`) → 파트너 필터 메일 본문(`send_exec_news_partners.py`) 또는 Actions용 `send_email_from_json.py`가 `news_summary.json`에서 직접 HTML 발송
- **출력:** `news_raw.json` → `news_summary.json` → `email_partners.json`(로컬 WORKS용) / 수신자 메일함(Gmail Actions)

---

## 구조

| 구분 | 역할 |
|------|------|
| `send_exec_news_timed.py` | 키워드별 API 수집, 기간·URL·제목 필터, `news_raw.json` |
| `summarize_exec_news_llm.py` | LLM 구조화 요약, `news_summary.json` |
| `send_exec_news_partners.py` | 지정 회사만 골라 HTML + `email_partners.json` |
| `send_email_from_json.py` | `news_summary.json`(또는 레거시 JSON) 기준 **Gmail SMTP** 발송·중복 기록 |
| `run_briefing_pipeline.py` | 위 세 단계를 순서대로 실행 → `email_partners.json`까지 |
| `archive_monthly_items.py` / `.monthly_archives/` | 일일 요약 월간 누적(Actions 후반) |
| `.github/workflows/send-news-mail.yml` | 수집 → 요약 → Gmail → 아카이브·푸시 |
| `.github/workflows/send-monthly-briefing.yml` | 월간 다이제스트(별도 워크플로) |

설정은 주로 **`send_exec_news_timed.py`** 의 `PARTNER_KEYWORDS`, `EXEC_KEYWORDS`, `ORG_RESTRUCTURING_KEYWORDS` 등 코드 상수에 있습니다. 상세 목록은 HANDOFF §2 참고.

---

## 실행

```bash
pip install -r requirements.txt python-dotenv
cp .env.example .env
# Windows: copy .env.example .env
# .env 에 NAVER·OPENAI 필수 입력 (아래 표)
python run_briefing_pipeline.py
```

- **로컬 Gmail까지 보낼 때:** 환경 변수에 Gmail 항목 설정 후 `python send_email_from_json.py` (또는 Actions와 동일 파이프라인을 로컬에서 나눠 실행).
- **WORKS로 보낼 때:** 파이프라인 후 `email_partners.json`의 `to` / `subject` / `body`로 MCP `mail_send` (`contentType: html`). 시크릿은 Cursor·MCP 쪽 설정에 의존.
- 파이프라인 중간 실패 시, 이미 생성된 JSON이 있으면 그걸로 수동 발송 가능.

---

## 환경변수 / GitHub Secrets

| 이름 | 용도 |
|------|------|
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 [검색 API](https://developers.naver.com) — 뉴스 수집 |
| `OPENAI_API_KEY` | 기사 요약 (`summarize_exec_news_llm.py`) |
| `OPENAI_MODEL` | 선택 (미설정 시 스크립트 기본값) |
| **Gmail 발송** | `GMAIL_APP_PASSWORD` (앱 비밀번호, 공백 제거), `GMAIL_SENDER`, `GMAIL_TO` |

**등록 위치**

| 환경 | 방법 |
|------|------|
| **로컬** | 프로젝트 루트 `.env` (권장) 또는 PowerShell `$env:변수명=...` |
| **GitHub Actions** | 저장소 **Settings → Secrets and variables → Actions** 에 위 이름 그대로 Secret 생성 |

Gmail은 일반 비밀번호가 아니라 **앱 비밀번호**를 사용합니다. ([Google 계정 보안](https://myaccount.google.com/security) → 2단계 인증 후 앱 비밀번호)

**WORKS 메일:** 위 표와 별개로, naver-works MCP 인증·정책이 필요합니다.

---

## 스케줄

- **GitHub Actions:** 일일·월간 워크플로의 **cron 자동 실행은 꺼 둔 상태**입니다. 메일이 필요할 때만 저장소 **Actions**에서 해당 워크플로를 골라 **Run workflow** 로 수동 실행하세요.
- **수집·중복(수동 실행 시):** `sent_dedup_store` 캐시·요청 범위(`REQUEST_SCOPE` 등)는 기존과 동일하게 동작합니다.
- **로컬 Windows:** [작업스케줄러_설정방법.md](작업스케줄러_설정방법.md) 로 등록해 두었다면 **작업 스케줄러에서 작업 비활성화 또는 삭제**해야 로컬 자동 실행도 멈춥니다.

---

## 기타 문서

| 문서 | 내용 |
|------|------|
| [docs/뉴스메일_미수신_확인체크리스트.md](docs/뉴스메일_미수신_확인체크리스트.md) | 미수신 점검 |
| [GIT_적용방법.md](GIT_적용방법.md) | Git 반영 |

**요구 사항:** Python 3.12 권장, `requirements.txt` + `python-dotenv`
