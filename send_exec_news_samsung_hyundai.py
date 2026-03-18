# -*- coding: utf-8 -*-
"""
임원인사·조직개편 뉴스 중 지정 회사 포함 기사만 필터해
실행한 그날 발표분을 A(인사변동)/B(조직개편)/C(둘 다) 타입으로 정리해 메일 본문 생성.

[뉴스 정리 포맷] 설정한 기간 발표분만 요약, 블로그 절대 미활용, 동일 회사 여러 기사는 종합·중복 제거, 인물 여러 명이면 모두 포함.
"""
import os
import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

KST = timezone(timedelta(hours=9))

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

MAIL_TO = "juan.jung@navercorp.com"
KEYWORDS = [
    "임원인사", "선임", "내정", "영입", "임명", "연임", "역임", "복귀", "승진", "교체", "사임", "용퇴", "체제", "개편", "분사", "일원화"
]
COMPANY_FILTER = [
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
# 회사 표기 우선순위 (긴/구체적 이름 우선)
COMPANY_DISPLAY_ORDER = [
    "삼성전자", "삼성SDS", "신라면세점", "삼성", "SK하이닉스", "SK브로드밴드", "SK스퀘어", "SK플래닛", "SKT", "티맵모빌리티", "SK",
    "현대오토에버", "현대모비스", "HD현대중공업", "현대건설", "현대카드", "현대차", "현대", "기아", "42dot",
    "LG CNS", "LG유플러스", "LG생활건강", "LG전자", "LG", "GS리테일", "GS칼텍스", "GS건설", "GS", "요기요",
    "호텔신라", "신세계", "이마트", "SSG닷컴", "스타벅스", "이베이", "롯데쇼핑", "롯데렌탈", "롯데",
    "카카오엔터", "카카오모빌리티", "카카오페이", "카카오", "CJ ENM", "CJ", "올리브영", "대한통운", "CGV", "대한항공", "아시아나", "한진칼",
    "BGF리테일", "BGF네트웍스", "LS전기", "LS", "KT", "쿠팡플레이", "쿠팡", "당근", "크래프톤", "휴맥스", "농심그룹", "한화에어로스페이스", "한화생명", "한화",
    "두나무앤파트너스", "람다256", "두나무", "업비트", "증권플러스비상장", "우아한형제들", "쏘카",
    "Meta", "메타", "Airbnb", "에어비앤비", "비바리퍼블리카", "Bytedance", "틱톡", "바이트댄스", "Uber", "우버", "Xsolla", "엑솔라", "다음", "DAUM",
    "업스테이지", "Adobe", "어도비", "Figma", "피그마", "Appning", "애프닝", "Netflix", "넷플릭스", "하이브", "넥슨", "Spotify", "스포티파이", "Disney", "디즈니",
    "메가박스", "LVMH", "CHANEL", "샤넬", "L'Oreal", "로레알", "인스파이어리조트", "이디야", "Huawei", "화웨이", "Novo Nordisk", "노보노디스크", "Harman", "하만", "Visa", "비자",
    "빗썸", "코인원", "코빗", "Google", "구글", "Microsoft", "마이크로소프트", "Amazon", "아마존", "OpenAI", "오픈AI", "Perplexity", "퍼플렉시티", "Anthropic", "앤스로픽", "Deepseek", "딥시크",
    "Apple", "애플", "Tesla", "테슬라", "Alibaba", "알리바바", "Walmart", "월마트", "Oracle", "오라클", "Palantir", "팔란티어", "Tencent", "텐센트",
]
NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
OUTPUT_DIR = Path(__file__).resolve().parent
EMAIL_JSON = OUTPUT_DIR / "email_samsung_hyundai.json"

# 타입 분류용 키워드
ORG_KEYWORDS = ("조직개편", "조직 개편", "신설", "팀", "본부", "분사", "일원화", "통합", "개편")
PERSON_KEYWORDS = ("선임", "영입", "내정", "임명", "사임", "교체", "용퇴", "승진", "연임", "역임", "복귀", "대표", "CEO", "임원")


def strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _is_valid_article_url(s: str) -> bool:
    """실제 기사 URL만 허용. placeholder·설명 문구 포함 시 False."""
    if not s or not (str(s).strip().startswith("http://") or str(s).strip().startswith("https://")):
        return False
    s = str(s)
    if "기사 URL" in s or "items 전체 공통" in s:
        return False
    return True


def fetch_news(client_id: str, client_secret: str, query: str, display: int = 30, start: int = 1):
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": query, "display": min(display, 100), "start": start, "sort": "date"}
    r = requests.get(NEWS_API_URL, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def contains_company(text: str) -> bool:
    return bool(text and any(c in text for c in COMPANY_FILTER))


def get_company_name(title: str, desc: str) -> str:
    """기사에서 매칭된 회사명 중 표기 우선순위에 따라 하나 반환 (명사형 표기용)."""
    combined = (title or "") + " " + (desc or "")
    for name in COMPANY_DISPLAY_ORDER:
        if name in combined:
            return name
    for c in COMPANY_FILTER:
        if c in combined:
            return c
    return "해당 회사"


def classify_type(title: str, desc: str) -> str:
    """A=인사변동만, B=조직개편만, C=둘 다."""
    t = (title or "") + " " + (desc or "")
    has_org = any(k in t for k in ORG_KEYWORDS)
    has_person = any(k in t for k in PERSON_KEYWORDS)
    if has_org and has_person:
        return "C"
    if has_org:
        return "B"
    return "A"


def get_today_start_kst() -> datetime:
    now = datetime.now(KST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_pub_date(pub_str: str) -> Optional[datetime]:
    if not pub_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_str)
    except Exception:
        return None


def format_mmdd(pub_str: str) -> str:
    dt = parse_pub_date(pub_str)
    return dt.strftime("%m/%d") if dt else ""


def extract_lead_sentence(text: str, max_len: int = 80) -> str:
    """명사형으로 끝나도록 앞부분 추출 (요약·목적 등)."""
    if not text or not text.strip():
        return "기사 참조"
    s = text.strip()
    for sep in [". ", "。", "!", "?", "\n"]:
        s = s.split(sep)[0].strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0] if " " in s[:max_len] else s[:max_len]
    if s.endswith("다") or s.endswith("요"):
        s = s[:-1] + "한 내용"
    return s if s else "기사 참조"


def format_block_a(article: dict, company: str, mmdd: str) -> str:
    """A. 인사변동 전용 블록 (명사형)."""
    title = article.get("title", "")
    desc = article.get("description", "")
    raw_link = (article.get("link") or "").strip()
    link = raw_link if _is_valid_article_url(raw_link) else ""
    lines = [f"{company} 임원인사 내용 공유드립니다. ({mmdd} 발표)", ""]
    # 신규 [직함]에 '[이름]' 전 [이전 직함] [선임/영입/내정]
    name_match = re.search(r"[\'\"]([^\'\"]{2,10})[\'\"]\s*(?:전\s*)?([^선임영입내정임명]{2,20}?)\s*(선임|영입|내정|임명)", title + desc)
    if name_match:
        name, prev_title, action = name_match.group(1), name_match.group(2).strip(), name_match.group(3)
        lines.append(f"신규 직함에 '{name}' 전 {prev_title} {action}")
    else:
        lines.append(f"임원 선임·교체 등 인사변동 내용 (상세: 기사 참조)")
    lines.append("경력: 기사 참조")
    # 이전 임원 사임/교체/용퇴
    if any(k in title + desc for k in ["사임", "퇴임", "용퇴", "교체"]):
        lines.append("기존 임원 사임·교체·용퇴 등 포함")
    lines.append(f"이번 임원인사는 {extract_lead_sentence(desc, 60)} 목적으로 단행된 것으로 추정")
    lines.append(f"<a href=\"{link}\">기사 원문</a>")
    return "\n".join(lines)


def format_block_b(article: dict, company: str, mmdd: str) -> str:
    """B. 조직개편 전용 블록 (명사형)."""
    desc = article.get("description", "")
    raw_link = (article.get("link") or "").strip()
    link = raw_link if _is_valid_article_url(raw_link) else ""
    lines = [f"{company} 조직개편 내용 공유드립니다. ({mmdd} 발표)", ""]
    lines.append("신설·개편된 조직 및 담당 업무: 기사 참조")
    lines.append(f"이번 조직개편은 {extract_lead_sentence(desc, 60)} 목적으로 단행된 것으로 추정")
    lines.append(f"<a href=\"{link}\">기사 원문</a>")
    return "\n".join(lines)


def format_block_c(article: dict, company: str, mmdd: str) -> str:
    """C. 인사변동 + 조직개편 블록 (명사형)."""
    title = article.get("title", "")
    desc = article.get("description", "")
    raw_link = (article.get("link") or "").strip()
    link = raw_link if _is_valid_article_url(raw_link) else ""
    lines = [f"{company} 임원인사 및 조직개편 내용 공유드립니다. ({mmdd} 발표)", "", "1) 임원인사", ""]
    name_match = re.search(r"[\'\"]([^\'\"]{2,10})[\'\"]\s*(?:전\s*)?([^선임영입내정임명]{2,20}?)\s*(선임|영입|내정|임명)", title + desc)
    if name_match:
        name, prev_title, action = name_match.group(1), name_match.group(2).strip(), name_match.group(3)
        lines.append(f"신규 직함에 '{name}' 전 {prev_title} {action}")
    else:
        lines.append("임원 선임·교체 등 인사변동 내용 (상세: 기사 참조)")
    lines.append("경력: 기사 참조")
    lines.append("기존 임원 사임·교체·용퇴 등 포함")
    lines.append(f"이번 임원인사는 {extract_lead_sentence(desc, 50)} 목적으로 단행된 것으로 추정")
    lines.append("")
    lines.append("2) 조직개편")
    lines.append("")
    lines.append("신설·개편된 조직 및 담당 업무: 기사 참조")
    lines.append(f"이번 조직개편은 {extract_lead_sentence(desc, 50)} 목적으로 단행된 것으로 추정")
    lines.append(f"<a href=\"{link}\">기사 원문</a>")
    return "\n".join(lines)


def dedupe_and_pick_best(articles: list) -> list:
    """동일 뉴스 다출처 시 정보가 가장 많은(본문 길이 기준) 기사만 유지."""
    if len(articles) <= 1:
        return articles
    # 제목 유사도로 그룹 (같은 회사+비슷한 제목)
    def norm(s):
        return re.sub(r"\s+", "", s)[:40]
    seen = {}
    for a in articles:
        key = (get_company_name(a.get("title", ""), a.get("description", "")), norm(a.get("title", "")))
        if key not in seen or len((a.get("description") or "")) > len(seen[key].get("description") or ""):
            seen[key] = a
    return list(seen.values())


def collect_and_filter(client_id: str, client_secret: str, cutoff: datetime) -> list:
    seen_links = set()
    articles = []
    for keyword in KEYWORDS:
        try:
            data = fetch_news(client_id, client_secret, keyword, display=20)
            for item in data.get("items", []):
                link = item.get("link") or item.get("originallink") or ""
                if not link or link in seen_links:
                    continue
                link_lower = link.lower()
                if "blog." in link_lower or "cafe." in link_lower or "kin." in link_lower:
                    continue
                pub_dt = parse_pub_date(item.get("pubDate", ""))
                if pub_dt:
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=KST)
                    if pub_dt < cutoff:
                        continue
                title = strip_html(item.get("title", ""))
                desc = strip_html(item.get("description", ""))
                if not contains_company(title) and not contains_company(desc):
                    continue
                seen_links.add(link)
                articles.append({"title": title, "link": link, "description": desc, "pubDate": item.get("pubDate", "")})
        except Exception as e:
            print(f"키워드 '{keyword}' 검색 오류: {e}")
    articles.sort(key=lambda a: (parse_pub_date(a.get("pubDate")) or datetime.min), reverse=True)
    return articles


def build_blocks_by_company(articles: list) -> list:
    """회사별로 묶고, A/B/C 포맷 블록 생성. 동일 회사 여러 건은 하나의 문단으로."""
    articles = dedupe_and_pick_best(articles)
    by_company = defaultdict(list)
    for a in articles:
        company = get_company_name(a.get("title", ""), a.get("description", ""))
        by_company[company].append(a)
    blocks = []
    for company in sorted(by_company.keys()):
        group = by_company[company]
        # 같은 회사 내에서도 중복 제거 후 정보 많은 것 우선
        group = dedupe_and_pick_best(group)
        for a in group:
            mmdd = format_mmdd(a.get("pubDate", ""))
            t = classify_type(a.get("title", ""), a.get("description", ""))
            if t == "A":
                blocks.append(format_block_a(a, company, mmdd))
            elif t == "B":
                blocks.append(format_block_b(a, company, mmdd))
            else:
                blocks.append(format_block_c(a, company, mmdd))
    return blocks


def build_body_html(articles: list) -> str:
    blocks = build_blocks_by_company(articles)
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        "<h2>임원인사·조직개편 뉴스 요약 (오늘 발표분)</h2>",
        "<p>키워드: 임원인사, 선임, 내정, 영입, 임명, 연임, 역임, 복귀, 승진, 교체, 사임, 용퇴, 체제, 개편, 분사, 일원화 / 지정 회사 포함 기사만</p>",
        "<hr/>",
    ]
    for i, block in enumerate(blocks, 1):
        para = block.replace("\n", "<br/>")
        lines.append(f"<p>{para}</p>")
        lines.append("<hr/>")
    lines.append("</body></html>")
    return "\n".join(lines)


def build_subject() -> str:
    now = datetime.now()
    return f"{now.month}월 {now.day}일 임원인사·조직개편 뉴스 요약 (지정 회사)"


def _build_from_news_summary() -> bool:
    """news_summary.json 이 있으면 그 내용으로 email_samsung_hyundai.json 생성. 성공 시 True."""
    try:
        from send_email_from_json import (
            _build_html_from_summary,
            _filter_items_since_last_send,
            _load_sent_dedup_store,
        )
    except ImportError:
        return False
    news_summary_path = OUTPUT_DIR / "news_summary.json"
    if not news_summary_path.exists():
        return False
    with open(news_summary_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items") or []
    items = _filter_items_since_last_send(items)
    if not items:
        return False
    now = datetime.now(KST)
    subject = f"{now.month}월 {now.day}일 임원인사·조직개편 뉴스 요약 (지정 회사)"
    sent_dedup = _load_sent_dedup_store()
    body_html, sent_exec_keys, sent_org_keys = _build_html_from_summary(items, subject, sent_dedup)
    out = {"to": MAIL_TO, "subject": subject, "body": body_html, "contentType": "html"}
    # 발송 후 중복 제거 저장소에 반영할 수 있도록 포함된 키 저장 (WORKS 메일 발송 후 record-sent-from 시 사용)
    out["sent_exec_keys"] = [list(t) for t in sent_exec_keys]
    out["sent_org_keys"] = [list(t) for t in sent_org_keys]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(EMAIL_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[news_summary 기반] 제목: {subject}, 항목: {len(items)}건 → {EMAIL_JSON}")
    return True


def main():
    # 1) news_summary.json 이 있으면 요약 본문(진행 이유·인물별·직전 발송 이후 등)으로 생성
    if _build_from_news_summary():
        return 0

    # 2) 없으면 기존처럼 Naver API로 수집 후 단순 포맷으로 생성
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("환경 변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 을 설정해 주세요.")
        return 1

    cutoff = get_today_start_kst()
    print(f"검색 범위: 오늘({cutoff.strftime('%Y-%m-%d')}) 발표 기사")

    articles = collect_and_filter(client_id, client_secret, cutoff)
    subject = build_subject()
    body_html = build_body_html(articles)

    payload = {"to": MAIL_TO, "subject": subject, "body": body_html, "contentType": "html"}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(EMAIL_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"제목: {subject}")
    print(f"수신: {MAIL_TO}")
    print(f"기사 수: {len(articles)}건")
    print(f"저장: {EMAIL_JSON}")
    return 0


if __name__ == "__main__":
    exit(main())
