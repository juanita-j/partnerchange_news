# daily-exec-news 인수인계 (한 페이지)

**파트너 지정 회사·키워드**가 포함된 **임원인사·조직개편** 뉴스를 네이버 API로 모으고, LLM으로 요약한 뒤 메일 본문을 만드는 로컬/CI 도구 모음입니다.

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

## 2. 트래킹·제외 기준

아래 목록은 **`send_exec_news_timed.py`** 기준이다. 회사 목록은 **`send_exec_news_partners.py`** 의 `COMPANY_FILTER`와 같은 계열이며, 파트너 메일용 보조 검색 키워드(`KEYWORDS`)는 임원인사 위주로 더 짧게 정의되어 있을 수 있다. **목록을 바꾸면 반드시 코드와 이 문서를 함께 맞출 것.**

### 2.1 트래킹 중인 회사명 (`PARTNER_KEYWORDS`)

제목에 아래 문자열이 **단어 단위**로 들어가야 파트너사 매칭으로 인정된다(다른 단어 안에만 들어간 경우는 제외 — `_keyword_in_text_strict`).

```
삼성, 삼성전자, 신라면세점, 삼성SDS, SK하이닉스, SK, SKT, SK브로드밴드, 티맵모빌리티, SK스퀘어, SK플래닛,
현대, 현대차, 기아, 현대모비스, 현대카드, 42dot, 현대오토에버, LG, LG전자, LG유플러스, LG생활건강, LG CNS, HD현대중공업, 현대건설,
GS, GS리테일, GS칼텍스, 요기요, GS건설, 호텔신라, 신세계, 이마트, SSG닷컴, 스타벅스, 이베이,
롯데, 롯데쇼핑, 롯데렌탈, 카카오, 카카오모빌리티, 카카오페이, 카카오엔터, CJ, CJ ENM, 올리브영, 대한통운, CGV, 대한항공, 아시아나, 한진칼,
BGF리테일, BGF네트웍스, LS, LS전기, KT, 쿠팡, 쿠팡플레이, 당근, 크래프톤, 휴맥스, 농심그룹, 한화, 한화에어로스페이스, 한화생명,
두나무, 업비트, 증권플러스비상장, 람다256, 두나무앤파트너스, 우아한형제들, 쏘카, Meta, 메타, Airbnb, 에어비앤비, 비바리퍼블리카,
Bytedance, 틱톡, 바이트댄스, Uber, 우버, Xsolla, 엑솔라, 다음, DAUM, 업스테이지, Adobe, 어도비, Figma, 피그마, Appning, 애프닝,
Netflix, 넷플릭스, 하이브, 넥슨, Spotify, 스포티파이, Disney, 디즈니, 메가박스, LVMH, CHANEL, 샤넬, L'Oreal, 로레알,
인스파이어리조트, 이디야, Huawei, 화웨이, Novo Nordisk, 노보노디스크, Harman, 하만, Visa, 비자, 빗썸, 코인원, 코빗,
Google, 구글, Microsoft, 마이크로소프트, Amazon, 아마존, OpenAI, 오픈AI, Perplexity, 퍼플렉시티, Anthropic, 앤스로픽, Deepseek, 딥시크,
Apple, 애플, Tesla, 테슬라, Alibaba, 알리바바, Walmart, 월마트, Oracle, 오라클, Palantir, 팔란티어, Tencent, 텐센트
```

### 2.2 트래킹 중인 인사·조직 키워드

**임원·인사 계열 (`EXEC_KEYWORDS`)** — 제목에 단어 단위로 매칭. 아래 조직 키워드와 **OR** 조건(둘 중 하나만 있어도 됨).

`임원인사`, `선임`, `재선임`, `내정`, `영입`, `임명`, `연임`, `역임`, `복귀`, `승진`, `교체`, `사임`, `용퇴`, `체제`, `개편`, `분사`, `일원화`

**조직개편·구조 계열 (`ORG_RESTRUCTURING_KEYWORDS`)**

`신설`, `개편`, `재편`, `통합`, `통폐합`, `폐지`, `조직개편`, `본부 신설`, `센터 신설`, `조직 신설`, `조직 통합`, `조직 폐지`, `조직 슬림화`, `부문 재편`

- 네이버 뉴스 API 검색에는 위 두 목록을 합친 **`KEYWORDS`**(중복 제거)로 키워드별 검색을 돌린다.
- 제목에 **(임원·인사 키워드 1개 이상) 또는 (조직 키워드 1개 이상)** 이 있어야 하고, 동시에 **2.1 회사명** 조건을 만족해야 최종 후보에 남는다.

### 2.3 제외·필터 (수집 단계)

| 구분 | 내용 |
|------|------|
| **기간** | 직전 발송 슬롯 이후·**최근 30일 이내** pubDate만 (`collect_articles_since`). |
| **URL** | `blog.`, `cafe.`, `kin.` 이 들어간 링크는 사용하지 않음. |
| **제목 노이즈** | `TITLE_NOISE_PATTERNS`: 연예·영화·예능(`예능`, `영화`, `배우`, `감독`, `[영상]` 등), 정치(`국민의힘`, `공천`, `지방선거` 등), 스포츠 이적(`이적료`, `아스널`, `MLS` 등) 등 임원인사와 무관한 패턴이 제목에 있으면 제외. |
| **‘다음’ 오인** | `다음 시즌`, `다음 경기`, 이적·이별 맥락이면 회사명 `다음`/`DAUM`으로 치지 않음. 그 경우 제목에 **다른 파트너 키워드**가 단어 단위로 있어야 통과. |
| **단어 경계** | `현대`≠`현대적`, `메타`≠`메타버스`처럼 다른 단어 속 부분 문자열만 겹치면 매칭하지 않음. |
| **롯데케미칼·설비** | `롯데`가 나오고, (케미칼·NCC·여천·석유화학·설비) 중 하나와 (통합·해체·구조재편) 중 하나가 같이 나오면 파트너 관련 임원인사로 보지 않고 제외. |
| **블로그·요약** | 블로그는 수집·LLM 요약 모두 사용하지 않는다는 규칙이 docstring·프롬프트에 있음. |
| **LLM 단계** | `summarize_exec_news_llm.py`에서 기사가 임원인사·조직개편이 아니라고 판단하면 `news_summary.json`에서 빠짐(프롬프트의 제외 규칙·롯데케미칼 등). |

---

## 3. 환경 준비

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

## 4. 로컬에서 끝까지 돌리기

```bash
python run_briefing_pipeline.py
```

- 실패 시에도 `email_partners.json`이 남아 있으면 그걸로 수동 발송 가능.
- **WORKS(naver-works MCP)** 로 보낼 때: JSON의 `to`, `subject`, `body`, `contentType: html`로 `mail_send` 호출 후, 중복 방지를 위해  
  `python send_email_from_json.py --record-sent-from email_partners.json` 실행(키 저장).

**Gmail만** 쓸 때는 파이프라인 후 `send_email_from_json.py`를 환경 변수와 함께 실행하면 됩니다(내부적으로 `news_summary.json` 우선).

---

## 5. GitHub Actions

- **Secrets**: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `OPENAI_API_KEY`, `GMAIL_APP_PASSWORD`, `GMAIL_SENDER`, `GMAIL_TO`
- **스케줄**: 일일·월간 워크플로 **cron 자동 실행은 비활성화**됨. 필요 시 Actions에서 **Run workflow** 만 사용.
- **중복 저장소**: `sent_dedup_store.json`은 캐시로 복원·저장됩니다.
- 수동 실행: Actions에서 **Run workflow** → 당일 범위 등은 `REQUEST_SCOPE` 등 env로 분기(워크플로 주석 참고).

---

## 6. 자주 쓰는 파일

| 파일 | 설명 |
|------|------|
| `news_raw.json` | API 수집 원본 |
| `news_summary.json` | LLM 구조화 요약(메일·아카이브 입력) |
| `email_partners.json` | 지정 회사 필터 브리핑 HTML + 수신자 |
| `sent_log.json` / `sent_dedup_store.json` | 발송·중복 추적(로컬, 커밋 대상 아님) |
| `.monthly_archives/` | 월간 다이제스트용 누적(Actions가 커밋할 수 있음) |

---

## 7. Cursor / 규칙

에이전트가 “임원인사 메일 보내줘” 요청 시 **파이프라인 → `email_partners.json` → WORKS `mail_send` → record-sent** 순으로 쓰도록, 사용자 `.cursor/rules/`에 `daily-exec-news-mail.mdc` 등이 있을 수 있습니다. **인수인계 시 해당 규칙 파일을 함께 복사**하거나 이 문서에 “메일은 WORKS MCP로 보낸다”고 명시해 두면 됩니다.

---

## 8. 추가 문서

- `작업스케줄러_설정방법.md` — Windows 로컬 스케줄
- `docs/뉴스메일_미수신_확인체크리스트.md` — 트러블슈팅
- `GIT_적용방법.md` — 저장소 푸시 관습

---

## 9. 인수인계 체크리스트

- [ ] Git 저장소 권한
- [ ] 네이버 개발자센터 앱(Client ID/Secret)
- [ ] OpenAI API 키(요약 실패 시 본문 비어 있음)
- [ ] Gmail 앱 비밀번호 또는 WORKS 발송 경로(MCP/정책)
- [ ] 로컬 `.env` 또는 Actions Secrets 반영
- [ ] (선택) 작업 스케줄러 작업보내기·계정 안내
- [ ] (선택) Cursor 규칙·MCP 설정 공유
