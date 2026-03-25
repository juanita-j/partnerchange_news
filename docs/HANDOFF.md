# daily-exec-news 인수인계 (한 페이지)

삼성·현대 계열 등 **지정 키워드·회사**가 포함된 **임원인사·조직개편** 뉴스를 네이버 API로 모으고, LLM으로 요약한 뒤 메일 본문을 만드는 로컬/CI 도구 모음입니다.

---

## 1. 한 줄 구조

```
뉴스 수집 → LLM 요약(JSON) → HTML 메일 생성 → 발송(Gmail 또는 WORKS) → (선택) 중복 기록·월간 아카이브
```

| 단계 | 스크립트 | 산출물 |
|------|-----------|--------|
| 수집 | `send_exec_news_timed.py` | `news_raw.json` |
| 요약 | `summarize_exec_news_llm.py` | `news_summary.json` |
| 본문(파트너사 지정 목록 필터 메일용) | `send_exec_news_partners.py` | `email_partners.json` |
| 한 번에 | `run_briefing_pipeline.py` | 위 순서 전부 + `email_partners.json` |

**GitHub Actions** (`.github/workflows/send-news-mail.yml`)는 수집 → 요약 후 **`send_email_from_json.py`로 Gmail 발송**합니다. `news_summary.json`에서 직접 HTML을 만들며, `send_exec_news_partners.py`는 **로컬·Cursor 워크플로에서 WORKS용 JSON** 만들 때 주로 씁니다.

---

## 2. 환경 준비

### Python

- **Python 3.12** 권장 (GitHub Actions와 동일)
- 저장소 루트에서:

```bash
pip install -r requirements.txt python-dotenv
```

### API 키·비밀값 종류와 넣는 위치

| 이름 | 용도 | 로컬 (`.env`) | GitHub Actions |
|------|------|----------------|----------------|
| `NAVER_CLIENT_ID` | 네이버 검색 API — 뉴스 수집 (`send_exec_news_timed.py` 등) | ✅ 필수 — 프로젝트 루트 `.env` | ✅ 필수 — **Repository → Settings → Secrets and variables → Actions** 에 동일 이름으로 Secret 등록 |
| `NAVER_CLIENT_SECRET` | 위와 쌍 | ✅ 필수 | ✅ 필수 |
| `OPENAI_API_KEY` | OpenAI — 기사 요약 (`summarize_exec_news_llm.py`) | ✅ 필수 (로컬 파이프라인·요약 시) | ✅ 필수 (`Send News Mail` 워크플로) |
| `OPENAI_MODEL` | 사용 모델 (예: `gpt-4o-mini`) | 선택 — 미설정 시 스크립트 기본값 | 선택 — 워크플로 `env`에 넣거나 Secrets로 관리 가능 |
| `GMAIL_APP_PASSWORD` | Gmail SMTP 앱 비밀번호(공백 제거) — **Actions가 메일 보낼 때** | 로컬에서 `send_email_from_json.py`로 Gmail 쓸 때 필요 | ✅ 필수 |
| `GMAIL_SENDER` | 발신 Gmail 주소 | 위와 동일 | ✅ 필수 (워크플로에서 참조) |
| `GMAIL_TO` | 수신 메일 주소 | 위와 동일 | ✅ 필수 |

**로컬 `.env` 만드는 방법**

1. 저장소 루트(이 프로젝트 최상위)에 `.env.example`을 복사해 **`.env`** 로 저장한다.  
   - Windows: `copy .env.example .env`
2. 위 표의 변수 이름 그대로 한 줄씩 넣고 값을 채운다. (`.env`는 Git에 올리지 않음 — `.gitignore` 처리됨)
3. `summarize_exec_news_llm.py`는 실행 시 **같은 폴더의 `.env`를 자동 로드**한다. `send_exec_news_timed.py`, `send_exec_news_partners.py` 등도 `python-dotenv`로 같은 경로를 읽는다.

**GitHub Actions에 넣는 방법**

1. GitHub에서 해당 저장소 → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret** 으로 아래 이름을 각각 등록한다. (이름은 대소문자까지 위 표와 동일하게)
   - `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `OPENAI_API_KEY`, `GMAIL_APP_PASSWORD`, `GMAIL_SENDER`, `GMAIL_TO`
3. **Send News Mail** 워크플로(`.github/workflows/send-news-mail.yml`)가 이 Secrets를 `env`로 넘겨 수집·요약·Gmail 발송을 수행한다.

**참고 (WORKS / NAVER WORKS 메일)**

- Cursor의 **naver-works MCP**로 메일을 보내는 경로는 **로컬 Cursor·MCP 인증**에 의존하며, 위 GitHub Secrets와는 별개다. 자동 스케줄 발송은 현재 워크플로 기준 **Gmail** 경로다.

---

## 3. 로컬에서 끝까지 돌리기

```bash
python run_briefing_pipeline.py
```

- 실패 시에도 `email_partners.json`이 남아 있으면 그걸로 수동 발송 가능.
- **WORKS(naver-works MCP)** 로 보낼 때: JSON의 `to`, `subject`, `body`, `contentType: html`로 `mail_send` 호출 후, 중복 방지를 위해  
  `python send_email_from_json.py --record-sent-from email_partners.json` 실행(키 저장).

**Gmail만** 쓸 때는 파이프라인 후 `send_email_from_json.py`를 환경 변수와 함께 실행하면 됩니다(내부적으로 `news_summary.json` 우선).

---

## 4. GitHub Actions

- **Secrets**: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `OPENAI_API_KEY`, `GMAIL_APP_PASSWORD`, `GMAIL_SENDER`, `GMAIL_TO`
- **스케줄**: 워크플로 YAML의 cron(평일 KST 다회) 참고.
- **중복 저장소**: `sent_dedup_store.json`은 캐시로 복원·저장됩니다.
- 수동 실행: Actions에서 **Run workflow** → 당일 범위 등은 `REQUEST_SCOPE` 등 env로 분기(워크플로 주석 참고).

---

## 5. 자주 쓰는 파일

| 파일 | 설명 |
|------|------|
| `news_raw.json` | API 수집 원본 |
| `news_summary.json` | LLM 구조화 요약(메일·아카이브 입력) |
| `email_partners.json` | 지정 회사 필터 브리핑 HTML + 수신자 |
| `sent_log.json` / `sent_dedup_store.json` | 발송·중복 추적(로컬, 커밋 대상 아님) |
| `.monthly_archives/` | 월간 다이제스트용 누적(Actions가 커밋할 수 있음) |

---

## 6. Cursor / 규칙

에이전트가 “임원인사 메일 보내줘” 요청 시 **파이프라인 → `email_partners.json` → WORKS `mail_send` → record-sent** 순으로 쓰도록, 사용자 `.cursor/rules/`에 `daily-exec-news-mail.mdc` 등이 있을 수 있습니다. **인수인계 시 해당 규칙 파일을 함께 복사**하거나 이 문서에 “메일은 WORKS MCP로 보낸다”고 명시해 두면 됩니다.

---

## 7. 추가 문서

- `작업스케줄러_설정방법.md` — Windows 로컬 스케줄
- `docs/뉴스메일_미수신_확인체크리스트.md` — 트러블슈팅
- `GIT_적용방법.md` — 저장소 푸시 관습

---

## 8. 인수인계 체크리스트

- [ ] Git 저장소 권한
- [ ] 네이버 개발자센터 앱(Client ID/Secret)
- [ ] OpenAI API 키(요약 실패 시 본문 비어 있음)
- [ ] Gmail 앱 비밀번호 또는 WORKS 발송 경로(MCP/정책)
- [ ] 로컬 `.env` 또는 Actions Secrets 반영
- [ ] (선택) 작업 스케줄러 작업보내기·계정 안내
- [ ] (선택) Cursor 규칙·MCP 설정 공유
