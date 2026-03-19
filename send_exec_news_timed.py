# -*- coding: utf-8 -*-
"""
1시간마다(9~19시 KST, 11회) 또는 수시 발송: 파트너사·임원인사·조직개편 뉴스 수집 후 메일 본문 생성.
- 정기(schedule): 직전 발송 슬롯 이후 기사만 수집. 수동(workflow_dispatch): REQUEST_SCOPE=today → 당일 00:00 KST~현재 전체 수집(sent_log/state 무시).
- 로컬 today 모드 테스트: PowerShell에서 `$env:REQUEST_SCOPE="today"; python send_exec_news_timed.py`
- 트래킹: 기사 제목에 임원인사 키워드 1개 이상 + 파트너사 키워드 1개 이상 포함된 기사만, 최근 한 달 이내 뉴스만(블로그·논문 제외)
※ 본문(전문) 분석은 원문 수집이 필요하며, 현재는 API 제목·요약만 사용합니다.

[출력 형식 - 일반 규칙]
- 첫 줄(제목)은 '-' 없이 출력. 그 외 요약 본문은 모두 '-' 하이픈으로 시작. 번호 묶음은 '1.', '2.' 형식.
- 사람 이름 앞뒤에는 작은따옴표(')를 붙인다. '님'은 붙이지 않는다.
- 인사 형태 용어는 기사 표현 그대로 사용 (영입, 승진, 선임, 이동 등).
- 문장은 한국어 조사(이/가 등)를 자연스럽게 맞춘다.
- 정보가 기사만으로 부족하면 최근 한 달 이내 추가 뉴스로 보완. 보완할 정보가 없거나 확인 불가하면 해당 bullet은 생략.

[출력 형식 - 정리 템플릿]
제목(첫 줄, '-' 없음): [회사이름1] [직무1] 임원인사 (mm/dd)
- [회사이름1] [직무1]에 [사람이름] [직무2] [인사형태]
- 경력: [회사이름2], [회사이름3]
- [임원인사 진행 이유]
- [전임자 교체/유지/타 직위 이동 여부]
(대괄호 안은 기사에서 분석해 채움. 확인 불가 시 해당 bullet 생략.)

[뉴스 정리 포맷 규칙]
- 인사변동 관련 뉴스 정리 시, 설정한 기간 동안 발표된 뉴스만 요약한다.
- 블로그는 절대 활용하지 않는다 (수집·요약 모두 제외).
- 특정 회사명이 들어간 기사가 여러 개 있으면 내용을 종합하고 중복은 제거한다.
- 기사에 인물이 여러 명이면 모두 포함한다 (한 명만 쓰지 않음).
"""
import os
import re
import json
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    import requests
except ImportError:
    print("pip install requests 후 다시 실행해 주세요.")
    raise

try:
    from article_body_fetcher import fetch_bodies_for_articles
except ImportError:
    def fetch_bodies_for_articles(articles, delay_sec=0.8):
        pass

KST = timezone(timedelta(hours=9))
MAIL_FROM = "wjdwndks99@gmail.com"
MAIL_TO = "juan.jung@navercorp.com"

# 검색·필터: (임원인사 키워드 1개 이상 OR 조직개편 키워드 1개 이상) + 파트너사 1개 이상
EXEC_KEYWORDS = [
    "임원인사", "선임", "재선임", "내정", "영입", "임명", "연임", "역임", "복귀", "승진", "교체", "사임", "용퇴", "체제", "개편", "분사", "일원화",
]
# 조직개편 전용 키워드 (설정 상수로 분리)
ORG_RESTRUCTURING_KEYWORDS = [
    "신설", "개편", "재편", "통합", "통폐합", "폐지", "조직개편",
    "본부 신설", "센터 신설", "조직 신설", "조직 통합", "조직 폐지", "조직 슬림화", "부문 재편",
]
PARTNER_KEYWORDS = [
    "삼성", "삼성전자", "신라면세점", "삼성SDS", "SK하이닉스", "SK", "SKT", "SK브로드밴드", "티맵모빌리티", "SK스퀘어", "SK플래닛",
    "현대", "현대차", "기아", "현대모비스", "현대카드", "42dot", "현대오토에버", "LG", "LG전자", "LG유플러스", "LG생활건강", "LG CNS", "HD현대중공업", "현대건설",
    "GS", "GS리테일", "GS칼텍스", "요기요", "GS건설", "호텔신라", "신세계", "이마트", "SSG닷컴", "스타벅스", "이베이",
    "롯데", "롯데쇼핑", "롯데렌탈", "카카오", "카카오모빌리티", "카카오페이", "카카오엔터", "CJ", "CJ ENM", "올리브영", "대한통운", "CGV", "대한항공", "아시아나", "한진칼",
    "BGF리테일", "BGF네트웍스", "LS", "LS전기", "KT", "쿠팡", "쿠팡플레이", "당근", "크래프톤", "휴맥스", "농심그룹", "한화", "한화에어로스페이스", "한화생명",
    "두나무", "업비트", "증권플러스비상장", "람다256", "두나무앤파트너스", "우아한형제들", "쏘카", "Meta", "메타", "Airbnb", "에어비앤비", "비바리퍼블리카",
    "Bytedance", "틱톡", "바이트댄스", "Uber", "우버", "Xsolla", "엑솔라", "다음", "DAUM", "업스테이지", "Adobe", "어도비", "Figma", "피그마", "Appning", "애프닝",
    "Netflix", "넷플릭스", "하이브", "넥슨", "Spotify", "스포티파이", "Disney", "디즈니", "메가박스", "LVMH", "CHANEL", "샤넬", "L'Oreal", "로레알",
    "인스파이어리조트", "이디야", "Huawei", "화웨이", "Novo Nordisk", "노보노디스크", "Harman", "하만", "Visa", "비자", "빗썸", "코인원", "코빗",
    "Google", "구글", "Microsoft", "마이크로소프트", "Amazon", "아마존", "OpenAI", "오픈AI", "Perplexity", "퍼플렉시티", "Anthropic", "앤스로픽", "Deepseek", "딥시크",
    "Apple", "애플", "Tesla", "테슬라", "Alibaba", "알리바바", "Walmart", "월마트", "Oracle", "오라클", "Palantir", "팔란티어", "Tencent", "텐센트",
]
# API 검색용: 임원인사 + 조직개편 키워드 (중복 제거)
KEYWORDS = list(dict.fromkeys(EXEC_KEYWORDS + ORG_RESTRUCTURING_KEYWORDS))
# 회사 추출용: 긴 이름 우선 매칭
COMPANY_PATTERNS = sorted(set(PARTNER_KEYWORDS), key=lambda x: -len(x))

# 단어 경계: 키워드가 다른 단어 한가운데 포함되지 않도록 (예: '현대' in '현대적', '메타' in '메타버스' 제외)
def _keyword_in_text_strict(text: str, keywords: list[str]) -> bool:
    """키워드 중 하나라도 텍스트에 '단어 단위'로 포함되면 True. 긴 키워드부터 검사."""
    if not text or not text.strip():
        return False
    text = " " + text.strip() + " "
    # 긴 키워드 우선 (예: '삼성전자' → '삼성' 보다 먼저 매칭)
    for k in sorted(set(k for k in keywords if k), key=lambda x: -len(x)):
        if k not in text:
            continue
        idx = 0
        while True:
            i = text.find(k, idx)
            if i < 0:
                break
            before = text[i - 1] if i > 0 else " "
            after = text[i + len(k)] if i + len(k) < len(text) else " "
            boundary = " \t\n\r,.\"\'()[];:·-"
            after_ok = after in boundary or after in "가이은를의에와과도만는"
            if before in boundary and after_ok:
                return True
            idx = i + 1
    return False


# 요청1: 임원인사가 아닌 기사(연예·정치·스포츠 이적 등) 제목 패턴 → 수집 제외
TITLE_NOISE_PATTERNS = [
    # 연예/영화/예능
    "[영상]", "[줌 인", "예능", "영화", "시사회", "개봉", "배우", "감독", "포토타임", "질의응답",
    "열여덟 청춘", "전소민", "스크린 복귀",
    # 정치
    "국민의힘", "공관위", "공천", "지방선거", "정치권", "여의도", "컷오프", "단체장", "의원",
    # 스포츠 이적(제목-내용 불일치: '다음'이 회사가 아닌 일반어·스포츠 맥락)
    "이적료", "아스널", "MLS", "사우디", "유리몸", "이별한다",
]


def _is_title_noise(title: str) -> bool:
    """연예·정치·스포츠 이적 등 임원인사가 아닌 기사 제목이면 True → 수집 제외."""
    if not title or not title.strip():
        return False
    t = title.strip()
    for pat in TITLE_NOISE_PATTERNS:
        if pat in t:
            return True
    return False


def _is_daum_common_word_context(title: str) -> bool:
    """'다음'이 회사(DAUM)가 아닌 '다음 시즌/경기' 등 일반어·스포츠 맥락이면 True → 파트너 매칭에서 제외."""
    if not title or "다음" not in title:
        return False
    daum_noise = (
        "다음 시즌", "다음 경기", "다음 달", "다음 주", "다음 번", "다음 단계",
        "이적료", "아스널", "MLS", "사우디", "유리몸", "이적", "이별",
    )
    return any(n in title for n in daum_noise)


def _partner_match_for_exec_news(title: str) -> bool:
    """제목에 파트너사 키워드가 '임원인사 맥락'으로 포함되면 True. '다음'은 일반어/스포츠 맥락 시 제외."""
    if not _keyword_in_text_strict(title, PARTNER_KEYWORDS):
        return False
    if _is_daum_common_word_context(title):
        others = [k for k in PARTNER_KEYWORDS if k not in ("다음", "DAUM")]
        if not _keyword_in_text_strict(title, others):
            return False
    return True


MAX_ARTICLES = 50
NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
OUTPUT_DIR = Path(__file__).resolve().parent
# 파이프라인: 이 스크립트는 news_raw.json 생성 전용. LLM 요약(summarize_exec_news_llm.py) → news_summary.json → send_email_from_json.py
NEWS_RAW_JSON = OUTPUT_DIR / "news_raw.json"

# 발송 시각 (KST): 9시~19시 1시간 단위 (11회)
RUN_HOURS_KST = (9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)


def now_kst() -> datetime:
    return datetime.now(KST)


def get_since_datetime(now: datetime, since_today_midnight: bool = False) -> datetime:
    """직전 발송 슬롯 시각 반환. KST 기준.
    since_today_midnight=True: 당일 00:00 KST
    False(정기): 9시→전날19시, 10시→당일9시, …, 19시→당일18시
    """
    if since_today_midnight:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    h = now.hour
    if h == 9:
        since = (now - timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
    elif 10 <= h <= 19:
        since = now.replace(hour=h - 1, minute=0, second=0, microsecond=0)
    else:
        if h < 9:
            since = (now - timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            since = now.replace(hour=18, minute=0, second=0, microsecond=0)
    return since


def get_today_start_kst(now: datetime) -> datetime:
    """당일 00:00:00 Asia/Seoul (KST). timezone 유지."""
    if getattr(now, "tzinfo", None) is None:
        now = now.replace(tzinfo=KST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_pubdate(s: str) -> datetime | None:
    """네이버 API pubDate 문자열을 KST datetime으로 변환."""
    if not s or not s.strip():
        return None
    try:
        dt = parsedate_to_datetime(s.strip())
        return dt.astimezone(KST)
    except Exception:
        return None


def strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def fetch_news(client_id: str, client_secret: str, query: str, display: int = 20, start: int = 1):
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": query, "display": min(display, 100), "start": start, "sort": "date"}
    r = requests.get(NEWS_API_URL, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


# 인사/조직 키워드로 기사 유형 분류용
PERSON_KEYWORDS = ("선임", "영입", "내정", "임명", "사임", "교체", "용퇴", "승진", "연임", "대표", "CEO", "임원")
ORG_KEYWORDS = ("조직개편", "조직 개편", "신설", "팀", "본부", "분사", "일원화", "통합", "개편")
# 직무 추출용 (긴 표현 우선)
RANK_KEYWORDS = ("대표이사", "부사장", "전무이사", "상무이사", "대표", "사장", "전무", "상무", "이사", "본부장", "팀장", "실장", "CEO", "CFO", "CTO", "COO")


def _extract_company(title: str, description: str) -> str:
    """제목·요약에서 회사명 추출 (매칭되는 첫 번째)."""
    text = (title + " " + description).strip()
    for c in COMPANY_PATTERNS:
        if c in text:
            return c
    return "기사 참조"


def _extract_position(text: str) -> str:
    """기사 텍스트에서 직무(직함) 추출. 매칭되는 첫 번째."""
    if not text or not text.strip():
        return "직무"
    for r in RANK_KEYWORDS:
        if r in text:
            return r
    return "직무"


def _extract_person_names(text: str) -> list[str]:
    """기사 텍스트에서 인물 이름 추출. '이름 직무' 또는 '직무 이름' 패턴. 인물 여러 명이면 모두 포함. '님' 제거."""
    if not text or not text.strip():
        return []
    names = []
    # '한글2~4자 + 직무' 패턴
    rank_pat = "|".join(re.escape(r) for r in RANK_KEYWORDS)
    for m in re.finditer(rf"([가-힣]{{2,4}})\s*(?:{rank_pat})\b", text):
        name = m.group(1).strip()
        if name and name not in ("그룹", "회사", "당시", "전임", "신규", "올해", "내년", "최근", "관련", "이번", "앞서"):
            names.append(name)
    for m in re.finditer(rf"(?:{rank_pat})\s*([가-힣]{{2,4}})\b", text):
        name = m.group(1).strip()
        if name and name not in names and name not in ("그룹", "회사", "당시", "전임", "신규"):
            names.append(name)
    seen = set()
    out = []
    for n in names:
        n_clean = n.replace("님", "").strip()
        if n_clean and n_clean not in seen:
            seen.add(n_clean)
            out.append(n_clean)
    return out[:5]


def _extract_career_companies(text: str, exclude_company: str) -> list[str]:
    """본문/요약에서 경력 회사명 추출 (주요 회사 제외)."""
    if not text:
        return []
    found = []
    for c in COMPANY_PATTERNS:
        if c != exclude_company and c in text:
            found.append(c)
    return found[:5]


def _extract_person_rank(text: str) -> str:
    """신규 임원의 직함(직무2). '이름 직무' 패턴에서 직무 추출. 없으면 _extract_position과 동일하게."""
    rank_pat = "|".join(re.escape(r) for r in RANK_KEYWORDS)
    m = re.search(rf"[가-힣]{{2,4}}\s*({rank_pat})\b", text)
    return m.group(1) if m else ""


def _format_names_for_display(names: list[str]) -> str:
    """이름 목록을 '이름1', '이름2' 형식으로. 이름 앞뒤 작은따옴표, '님' 없음."""
    if not names:
        return "[이름]"
    return ", ".join(f"'{n}'" for n in names)


def _extract_date_str(pub_date_str: str) -> str:
    """pubDate에서 yy/mm/dd 형식 문자열 반환."""
    dt = parse_pubdate(pub_date_str)
    if dt:
        return dt.strftime("%y/%m/%d")
    return "기사 참조"


def _extract_date_md(pub_date_str: str) -> str:
    """메신저용 날짜: M/D (예: 9/2)."""
    dt = parse_pubdate(pub_date_str)
    if dt:
        return f"{dt.month}/{dt.day}"
    return "기사 참조"


def _classify_article_type(title: str, description: str) -> str:
    """A=인사변동만, B=조직개편만, C=둘 다."""
    text = (title + " " + description).strip()
    has_person = any(k in text for k in PERSON_KEYWORDS)
    has_org = any(k in text for k in ORG_KEYWORDS)
    if has_person and has_org:
        return "C"
    if has_org:
        return "B"
    return "A"


def _pick_action_word(title: str, description: str, for_leave: bool = False) -> str:
    """기사 표현 그대로 인사 형태 용어 추출 (영입, 승진, 선임, 이동, 사임, 교체 등)."""
    text = (title + " " + description).strip()
    if for_leave:
        for w in ("사임", "교체", "용퇴"):
            if w in text:
                return w
        return ""
    for w in ("영입", "승진", "선임", "이동", "내정", "임명", "연임", "복귀"):
        if w in text:
            return w
    return ""


def _build_concise_single(company: str, date_md: str, article: dict) -> list[str]:
    """단일 인사변동: 템플릿 형식. 첫 줄은 '-' 없음, 이하 '-' bullet. 확인 불가 시 해당 bullet 생략."""
    text = _article_text(article)
    title = (article.get("title") or "").strip()
    position = _extract_position(text)
    action = _pick_action_word(title, text, for_leave=False)
    action_leave = _pick_action_word(title, text, for_leave=True)
    names = _extract_person_names(text)
    career = _extract_career_companies(text, company)

    # 첫 줄(제목): '-' 없음. [회사이름1] [직무1] 임원인사 (mm/dd)
    lines = [f"{company} {position} 임원인사 ({date_md})"]

    # - [회사] [직무1]에 [이름] [직무2] [인사형태]. 인물 여러 명이면 모두 나열.
    name_str = _format_names_for_display(names) if names else "[이름]"
    position2 = _extract_person_rank(text) or position
    action_str = action if action else "[인사형태]"
    mid = f" {position2}" if position2 else ""
    lines.append(f"- {company} {position}에 {name_str}{mid} {action_str}")

    # - 경력: (확인 가능할 때만)
    if career:
        lines.append("- 경력: " + ", ".join(career))

    # - [임원인사 진행 이유]: 기사에서 구체적 표현 있을 때만, 확인 불가 시 생략
    for kw in ("실적 악화", "경질성", "조직 개편", "인수·합병", "사업 강화"):
        if kw in text:
            lines.append(f"- {kw} 등 (기사 참조)")
            break

    # - [전임자 교체/유지/타 직위 이동 여부]: 인사형태(교체/사임 등) 있을 때만
    if action_leave:
        lines.append(f"- 전임자 {name_str} {action_leave}")

    return lines


def _build_concise_multi(company: str, date_md: str, clusters: list[list[dict]]) -> list[str]:
    """동일 회사 내 여러 건: 첫 줄 제목(no '-'), 이하 '1.', '2.' 번호 헤더 + 각 건당 템플릿 bullet."""
    position = "직무"
    for cl in clusters:
        rep = max(cl, key=lambda a: len(_article_text(a)))
        p = _extract_position(_article_text(rep))
        if p != "직무":
            position = p
            break
    # 첫 줄(제목): '-' 없음
    lines = [f"{company} {position} 임원인사 ({date_md})"]
    for i, cl in enumerate(clusters, 1):
        rep = max(cl, key=lambda a: len(_article_text(a)))
        text = _article_text(rep)
        title = (rep.get("title") or "").strip()
        pos = _extract_position(text)
        action = _pick_action_word(title, text, for_leave=False)
        action_leave = _pick_action_word(title, text, for_leave=True)
        names = _extract_person_names(text)
        career = _extract_career_companies(text, company)
        name_str = _format_names_for_display(names) if names else "[이름]"
        position2 = _extract_person_rank(text) or pos
        action_str = action if action else "[인사형태]"
        mid = f" {position2}" if position2 else ""
        lines.append(f"{i}. [계열사/사업부] (기사 참조)")
        lines.append(f"- {company} {pos}에 {name_str}{mid} {action_str}")
        if career:
            lines.append("- 경력: " + ", ".join(career))
        if action_leave:
            lines.append(f"- 전임자 {name_str} {action_leave}")
    return lines


def _article_text(a: dict) -> str:
    """본문이 있으면 본문, 없으면 요약. 요약·본문 기반 추출에 사용."""
    body = (a.get("body") or "").strip()
    if body:
        return body
    return (a.get("title") or "").strip() + " " + (a.get("description") or "").strip()


def _build_extra_block(articles: list[dict]) -> list[str]:
    """[추가 내용]: 보완 정보만 '-' bullet. 본문이 있으면 본문 일부 활용."""
    lines = []
    seen = set()
    for a in articles[:3]:
        text = _article_text(a)
        snippet = (text or "").strip()[:300].replace("\n", " ")
        if not snippet:
            continue
        if snippet in seen:
            continue
        seen.add(snippet)
        date_md = _extract_date_md(a.get("pubDate", ""))
        lines.append(f"- {snippet}… (기사 참조, {date_md})")
    if not lines:
        lines.append("- 추가로 확인된 내용 없음")
    return lines[:5]


def build_template_bullets(article: dict) -> list[str]:
    """(레거시) 형식 A/B/C 하위 bullet. 신규 출력은 _build_concise_* 사용."""
    title = (article.get("title") or "").strip()
    text = _article_text(article)
    pub = article.get("pubDate", "")
    company = _extract_company(title, text)
    date_str = _extract_date_str(pub)
    atype = _classify_article_type(title, text)
    action = _pick_action_word(title, text, for_leave=False)
    action_leave = _pick_action_word(title, text, for_leave=True)
    if atype == "A":
        return [
            f"{company} 임원인사 내용 공유 ({date_str} 발표)",
            f"- {company} [직무]에 '[이름]' {action} (기사 참조)",
            "- 경력: 기사 참조",
            f"- [전임자] {action_leave} (기사 참조)",
        ]
    if atype == "B":
        return [
            f"{company} 조직개편 내용 공유 ({date_str} 발표)",
            "- [신설/개편 내용] (기사 참조)",
        ]
    return [
        f"{company} 임원인사 및 조직개편 내용 공유 ({date_str} 발표)",
        "- (기사 참조)",
    ]


def _title_normalize(s: str) -> str:
    """동일 뉴스 판별용 제목 정규화."""
    s = re.sub(r"[^\w\s가-힣a-zA-Z0-9]", " ", s or "")
    return " ".join((s or "").split()).strip()


def _is_same_news(a1: dict, a2: dict) -> bool:
    """동일 회사·동일 이벤트로 보이는지 (제목 유사도)."""
    t1 = _title_normalize(a1.get("title", ""))
    t2 = _title_normalize(a2.get("title", ""))
    if not t1 or not t2:
        return False
    w1, w2 = set(t1.split()), set(t2.split())
    if not w1 or not w2:
        return False
    overlap = len(w1 & w2) / max(len(w1), len(w2))
    return overlap >= 0.5 or (t1 in t2 or t2 in t1)


def _group_by_company(articles: list[dict]) -> dict[str, list[dict]]:
    """회사별로 기사 묶음. 동일 회사 여러 기사는 이후 _merge_one_company에서 내용 종합·중복 제거.
    '기사 참조'는 회사 미상이므로 문단 합치지 않음."""
    groups: dict[str, list[dict]] = {}
    for a in articles:
        company = _extract_company(a.get("title", ""), a.get("description", ""))
        if company == "기사 참조":
            key = f"_unk_{len(groups)}"
        else:
            key = company
        if key not in groups:
            groups[key] = []
        groups[key].append(a)
    return groups


def _pick_article_url_from_item(item: dict) -> str:
    """API 응답에서 기사 URL 선택. 네이버 뉴스 URL(n.news.naver.com 등)이 있으면 우선 사용해 원본 사이트 삭제 시에도 접근 가능하게 함."""
    link = (item.get("link") or "").strip()
    originallink = (item.get("originallink") or "").strip()
    for u in (link, originallink):
        if u and ("n.news.naver.com" in u or "news.naver.com" in u):
            return u
    return link or originallink


def _pick_best_link(articles: list[dict]) -> tuple[str, list[dict]]:
    """동일 뉴스 복수 출처 시 정보가 가장 많은(description 가장 긴) 기사 링크 선택. 반환: (link, 동일 뉴스로 묶인 기사 목록)."""
    if not articles:
        return "", []
    if len(articles) == 1:
        return (articles[0].get("link") or "").strip(), articles
    best = max(articles, key=lambda a: len((a.get("description") or "")))
    return (best.get("link") or "").strip(), articles


def _cluster_same_news(company_articles: list[dict]) -> list[list[dict]]:
    """한 회사 내에서 동일 뉴스(여러 출처)끼리 묶음. 서로 다른 이벤트는 별도 클러스터."""
    if not company_articles:
        return []
    clusters: list[list[dict]] = []
    for a in company_articles:
        placed = False
        for cl in clusters:
            if _is_same_news(a, cl[0]):
                cl.append(a)
                placed = True
                break
        if not placed:
            clusters.append([a])
    return clusters


def _merge_one_company(company: str, company_articles: list[dict]) -> tuple[str, str, list[str], list[str]]:
    """한 회사 문단: 제목줄, 대표 링크, [간결한 버전] 라인 목록, [추가 내용] 라인 목록.
    동일 회사 기사 여러 건은 내용 종합·중복 제거 후 한 덩어리로 요약. 인물이 여러 명이면 모두 나열."""
    if company.startswith("_unk_"):
        a = company_articles[0]
        title = (a.get("title") or "").strip()
        link = (a.get("link") or "").strip()
        date_md = _extract_date_md(a.get("pubDate", ""))
        concise = [f"[회사 미상] 임원인사 ({date_md})"]
        concise.append(f"- {title} (기사 참조)")
        extra = _build_extra_block(company_articles)
        return title, link, concise, extra
    clusters = _cluster_same_news(company_articles)
    best_article = max(company_articles, key=lambda a: len((a.get("description") or "")))
    best_link = (best_article.get("link") or "").strip()
    date_md = _extract_date_md(best_article.get("pubDate", ""))
    if len(clusters) <= 1:
        rep = clusters[0][0] if clusters else best_article
        concise = _build_concise_single(company, date_md, rep)
    else:
        concise = _build_concise_multi(company, date_md, clusters)
    extra = _build_extra_block(company_articles)
    one_line = concise[0] if concise else f"{company} 인사·조직 관련"
    return one_line, best_link, concise, extra


def collect_articles_since(client_id: str, client_secret: str, since_dt: datetime) -> tuple[list[dict], dict]:
    """since_dt 이상(이후) pubDate 기사 수집. 페이징으로 100건 이상도 수집. 반환: (articles, stats)."""
    seen_links = set()
    articles = []
    display_per_page = 100
    stats = {"raw_count": 0, "after_date_filter": 0, "after_relevance_filter": 0}

    for keyword in KEYWORDS:
        if len(articles) >= MAX_ARTICLES:
            break
        start = 1
        while True:
            try:
                data = fetch_news(client_id, client_secret, keyword, display=display_per_page, start=start)
                items = data.get("items") or []
                if not items:
                    break
                stats["raw_count"] += len(items)
                for item in items:
                    link = _pick_article_url_from_item(item)
                    if not link or link in seen_links:
                        continue
                    pub_dt = parse_pubdate(item.get("pubDate", ""))
                    if pub_dt is None:
                        continue
                    # 당일 00:00 포함: pub_dt >= since_dt 포함 (즉 pub_dt < since_dt 이면 제외)
                    if pub_dt < since_dt:
                        continue
                    stats["after_date_filter"] += 1
                    now = now_kst()
                    if pub_dt < now - timedelta(days=30):
                        continue
                    link_lower = link.lower()
                    if "blog." in link_lower or "cafe." in link_lower or "kin." in link_lower:
                        continue
                    title_clean = strip_html(item.get("title", ""))
                    desc_clean = strip_html(item.get("description", ""))
                    if _is_title_noise(title_clean):
                        continue
                    has_exec = _keyword_in_text_strict(title_clean, EXEC_KEYWORDS)
                    has_org = _keyword_in_text_strict(title_clean, ORG_RESTRUCTURING_KEYWORDS)
                    if not has_exec and not has_org:
                        continue
                    if not _partner_match_for_exec_news(title_clean):
                        continue
                    stats["after_relevance_filter"] += 1
                    seen_links.add(link)
                    articles.append({
                        "title": title_clean,
                        "link": link,
                        "description": desc_clean,
                        "pubDate": item.get("pubDate", ""),
                    })
                    if len(articles) >= MAX_ARTICLES:
                        break
                if len(articles) >= MAX_ARTICLES:
                    break
                if len(items) < display_per_page:
                    break
                start += display_per_page
            except Exception as e:
                print(f"키워드 '{keyword}' start={start} 검색 오류: {e}")
                break

    stats["final_included_count"] = len(articles)
    return articles[:MAX_ARTICLES], stats


def build_subject(now: datetime) -> str:
    return f"인사변동 업데이트 ({now.strftime('%y/%m/%d')})"


def build_body_html(articles: list) -> str:
    """회사별 [간결한 버전] + [추가 내용], 메신저 공유 최적화. 첫 줄은 '-' 없음, 이하 '-' bullet, 번호는 1. 2. 만 사용."""
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        "<p>임원인사·파트너사 관련 뉴스 (최근 한 달 이내 뉴스 기사 기준)</p>",
        "<ul>",
    ]
    groups = _group_by_company(articles)
    for key, company_articles in sorted(groups.items(), key=lambda x: (x[0].startswith("_unk_"), x[0])):
        if not company_articles:
            continue
        title_line, link, concise, extra = _merge_one_company(key, company_articles)
        if not title_line:
            continue
        link_html = f' <a href="{link}">기사 보기</a>' if link else ""
        lines.append(f"  <li><strong>{title_line}</strong>{link_html}")
        lines.append("    <p><strong>[간결한 버전]</strong></p>")
        lines.append("    <ul>")
        for i, line in enumerate(concise):
            if not line or not line.strip():
                continue
            if i == 0:
                lines.append(f"      <li>{line.strip()}</li>")
            elif line.strip().startswith("-"):
                lines.append(f"      <li>{line.strip()}</li>")
            elif re.match(r"^\d+\.", line.strip()):
                lines.append(f"      <li><strong>{line.strip()}</strong></li>")
            else:
                lines.append(f"      <li>- {line.strip()}</li>")
        lines.append("    </ul>")
        lines.append("    <p><strong>[추가 내용]</strong></p>")
        lines.append("    <ul>")
        for line in extra:
            if line and line.strip():
                lines.append(f"      <li>{line.strip()}</li>")
        lines.append("    </ul>")
        lines.append("  </li>")
    lines.append("</ul></body></html>")
    return "\n".join(lines)


def main() -> int:
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("환경 변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 을 설정해 주세요.")
        return 1

    now = now_kst()
    request_scope_raw = os.environ.get("REQUEST_SCOPE", "").strip().lower()
    request_scope = "today" if request_scope_raw == "today" else "scheduled"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip() or "(로컬)"

    today_start = get_today_start_kst(now)
    if request_scope == "today":
        since = today_start
        last_sent_at_str = "(무시됨, today 모드)"
        mode_reason = "workflow_dispatch uses today's 00:00 to now in Asia/Seoul"
    else:
        since = get_since_datetime(now, since_today_midnight=False)
        last_sent_at_str = since.isoformat()
        mode_reason = "scheduled uses last run slot in Asia/Seoul"

    print(f"github.event_name={event_name}")
    print(f"REQUEST_SCOPE={request_scope}")
    print(f"now (Asia/Seoul)={now.isoformat()}")
    print(f"today_start={today_start.isoformat()}")
    print(f"last_sent_at={last_sent_at_str}")
    print(f"effective_since_dt={since.isoformat()}")
    print(f"mode_reason={mode_reason}")

    articles, collect_stats = collect_articles_since(client_id, client_secret, since)
    fetch_bodies_for_articles(articles)

    print(f"raw article count={collect_stats.get('raw_count', 0)}")
    print(f"after date filter count={collect_stats.get('after_date_filter', 0)}")
    print(f"after relevance filter count={collect_stats.get('after_relevance_filter', 0)}")
    print(f"final included count={collect_stats.get('final_included_count', len(articles))}")

    until_dt = now.isoformat()
    payload = {
        "request_scope": request_scope,
        "collected_at": now.isoformat(),
        "since_dt": since.isoformat(),
        "until_dt": until_dt,
        "mode_reason": mode_reason,
        "articles": [
            {
                "title": a.get("title", ""),
                "link": a.get("link", ""),
                "description": a.get("description", ""),
                "pubDate": a.get("pubDate", ""),
                "body": a.get("body", ""),
            }
            for a in articles
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(NEWS_RAW_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"기사 수: {len(articles)}건")
    print(f"저장: {NEWS_RAW_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
