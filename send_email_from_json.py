# -*- coding: utf-8 -*-
"""
news_summary.json 을 읽어 HTML 메일로 Gmail 발송.

- 파이프라인: send_exec_news_timed.py → news_raw.json → summarize_exec_news_llm.py → news_summary.json → 본 스크립트
- sent_log.json 기반 재발송 방지: 동일 content_hash + 당일 이미 발송 시 스킵. FORCE_SEND=1 이면 무시.
- sent_dedup_store.json: 이전 메일로 이미 보낸 (회사, 인물, 인사유형) / (회사, 조직개편) 저장. 중복은 제외하고 새 소식만 발송.
- 환경 변수: GMAIL_APP_PASSWORD 필수. GMAIL_SENDER, GMAIL_TO 는 JSON 또는 env 로 덮어쓸 수 있음.
"""

import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime

OUTPUT_DIR = Path(__file__).resolve().parent
NEWS_SUMMARY_JSON = OUTPUT_DIR / "news_summary.json"
SENT_LOG_JSON = OUTPUT_DIR / "sent_log.json"
SENT_DEDUP_STORE_JSON = OUTPUT_DIR / "sent_dedup_store.json"
# 레거시: email_content.json (직접 HTML 있는 경우)
EMAIL_CONTENT_JSON = OUTPUT_DIR / "email_content.json"


def _is_valid_article_url(s: str) -> bool:
    """실제 기사 URL만 허용. placeholder·설명 문구 포함 시 False."""
    if not s or not (s.startswith("http://") or s.startswith("https://")):
        return False
    if "기사 URL" in s or "items 전체 공통" in s:
        return False
    return True


def _normalize_display(s: str) -> str:
    """본문 표기: (완료) → 공백+완료, (예정) → 공백+예정, '이름', → '이름', 연속 중복 직함 하나로, 문장 끝 (주총 승인 후) 제거."""
    if not s:
        return s
    s = (s or "").replace("(완료)", " 완료").replace("(예정)", " 예정")
    # '이름' 뒤 콤마 제거
    s = re.sub(r"',\s*", "' ", s)
    # 문장 끝 괄호 "(주총 승인 후)" 제거 (시기는 문장 앞에만 표시)
    s = re.sub(r"\s*\(\s*주총\s*승인\s*후\s*\)\s*$", "", s, flags=re.IGNORECASE).strip()
    # 연속으로 같은 단어가 두 번 나오면 하나만 (예: "사내이사 사내이사" → "사내이사")
    words = s.split()
    out = []
    for w in words:
        if out and out[-1] == w:
            continue
        out.append(w)
    return " ".join(out)


def _pubdate_to_mmdd(pub_date_str: str) -> str:
    """pubDate 문자열에서 mm/dd 추출. 실패 시 빈 문자열."""
    if not pub_date_str or not str(pub_date_str).strip():
        return ""
    try:
        dt = parsedate_to_datetime(str(pub_date_str).strip())
        return dt.strftime("%m/%d")
    except Exception:
        return ""


def _pubdate_to_utc(pub_date_str: str) -> datetime | None:
    """pubDate 문자열을 UTC datetime으로 변환. 실패 시 None."""
    if not pub_date_str or not str(pub_date_str).strip():
        return None
    try:
        dt = parsedate_to_datetime(str(pub_date_str).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _get_last_sent_at_utc() -> datetime | None:
    """sent_log.json의 last_sent_at을 UTC datetime으로 반환. 없으면 None."""
    if not SENT_LOG_JSON.exists():
        return None
    try:
        with open(SENT_LOG_JSON, "r", encoding="utf-8") as f:
            log = json.load(f)
        raw = log.get("last_sent_at")
        if not raw:
            return None
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _filter_items_since_last_send(items: list[dict]) -> list[dict]:
    """직전 발송 시각(last_sent_at) 이후 pubDate인 항목만 포함. 첫 발송이면 전부 포함."""
    last_sent = _get_last_sent_at_utc()
    if last_sent is None:
        return items
    out = []
    for it in items:
        pub_utc = _pubdate_to_utc(it.get("pubDate") or "")
        if pub_utc is not None and pub_utc > last_sent:
            out.append(it)
    return out


def _format_person_name(name: str) -> str:
    """대상 인물이 있으면 작은따옴표로 감쌈."""
    s = (name or "").strip()
    if not s:
        return s
    if s.startswith("'") and s.endswith("'"):
        return s
    return f"'{s}'"


def _normalize_person_for_dedup(name: str) -> str:
    """이전 발송 여부 비교용 인물명 정규화 (따옴표 제거, trim)."""
    s = (name or "").strip().strip("'\"").strip()
    return s


def _load_sent_dedup_store() -> dict:
    """이미 발송한 (회사, 인물) / (회사, 조직개편) 집합 반환.
    exec 키는 (company, person_norm) 2-tuple — 같은 사람은 인사유형 무관하게 재발송 안 함.
    """
    out = {"exec": set(), "org": set()}
    if not SENT_DEDUP_STORE_JSON.exists():
        return out
    try:
        with open(SENT_DEDUP_STORE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for t in data.get("exec") or []:
            if isinstance(t, list) and len(t) >= 2:
                # 구버전 3-tuple 도 2-tuple 로 읽어 호환
                out["exec"].add((str(t[0]).strip(), str(t[1]).strip()))
        for t in data.get("org") or []:
            if isinstance(t, list) and len(t) >= 2:
                out["org"].add((str(t[0]).strip(), str(t[1]).strip()))
    except Exception:
        pass
    return out


def _save_sent_dedup_store(exec_keys: list, org_keys: list) -> None:
    """새로 발송한 키들을 기존 저장소에 추가해 저장."""
    existing = _load_sent_dedup_store()
    for t in exec_keys:
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            existing["exec"].add((str(t[0]).strip(), str(t[1]).strip()))
    for t in org_keys:
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            existing["org"].add((str(t[0]).strip(), str(t[1]).strip()))
    data = {
        "exec": [list(t) for t in existing["exec"]],
        "org": [list(t) for t in existing["org"]],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(SENT_DEDUP_STORE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _title_from_key_points(key_points: list, max_len: int = 60) -> str:
    """중요 포인트에서 제목 문자열 생성. 60자 초과 시 ... 자름."""
    if not key_points:
        return ""
    first = (key_points[0] if key_points else "").strip()
    if not first:
        return ""
    if len(first) > max_len:
        return first[:max_len].rstrip() + "..."
    return first


def _to_briefing_style(s: str) -> str:
    """문장을 브리핑 스타일 명사형으로 간단 변환. (~했다→~함, ~중 등)"""
    if not s or not s.strip():
        return s
    s = s.strip()
    s = re.sub(r"했다\.?\s*$", "함", s)
    s = re.sub(r"했다\s*$", "함", s)
    s = re.sub(r"하고\s*있다\.?\s*$", "중", s)
    s = re.sub(r"되고\s*있다\.?\s*$", "중", s)
    s = re.sub(r"될\s*것으로\s*보인다\.?\s*$", "전망", s)
    return s


def _reason_to_noun_form(s: str) -> str:
    """진행 이유 문장을 명사형으로 끝내기. 서술형 어미(~된다·~한다) 제거, ~를/을 위해→위함, 조치다→조치."""
    if not s or not s.strip():
        return s
    s = _to_briefing_style(s.strip())
    s = re.sub(r"을 위해\b", "을 위함", s)
    s = re.sub(r"를 위해\b", "를 위함", s)
    # 서술형 어미 제거 → 명사형 (예: 평가된다→평가, 재편한다→재편)
    s = re.sub(r"된다\s*\.?\s*$", "", s)
    s = re.sub(r"한다\s*\.?\s*$", "", s)
    s = re.sub(r"됐다\s*\.?\s*$", "", s)
    s = re.sub(r"였다\s*\.?\s*$", "", s)
    s = re.sub(r"었다\s*\.?\s*$", "", s)
    # "~에 따라 재선임함/재선임됨" → "~에 따른 재선임"
    s = re.sub(r"에 따라\s+재선임(함|됨)\s*\.?\s*$", "에 따른 재선임", s)
    s = re.sub(r"한 데 기여함\s*\.?\s*$", "한 데 기여", s)
    s = re.sub(r"(을 위한 조치)다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"(를 위한 조치)다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"(을 위한 조치)이다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"(를 위한 조치)이다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"(조치)다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"(것)다\s*\.?\s*$", r"\1", s)
    s = re.sub(r"이다\s*\.?\s*$", "임", s)
    s = re.sub(r"하다\s*\.?\s*$", "함", s)
    s = re.sub(r"다\s*\.?\s*$", "음", s)
    return s.strip()


def _bullets_from_item(it: dict) -> list[str]:
    """bullet_points 있으면 사용(2~5개), 없으면 2문장 요약·중요 포인트로 브리핑 스타일 불렛 생성."""
    bullets = it.get("bullet_points")
    if isinstance(bullets, list) and bullets:
        return [str(b).strip() for b in bullets if str(b).strip()][:10]

    # fallback: 2문장 요약 + 중요 포인트, 브리핑 스타일로
    out = []
    summary = (it.get("2문장 요약") or "").strip()
    if summary:
        for s in re.split(r"[.;]\s+", summary):
            s = _to_briefing_style(s.strip())
            if s and len(s) > 5:
                out.append(s)
    key_points = it.get("중요 포인트") or []
    person = _format_person_name(it.get("대상 인물") or "")
    company = (it.get("회사명") or "").strip()
    ptype = (it.get("인사 유형") or "").strip()
    prev_role = (it.get("기존 직책") or "").strip()
    new_role = (it.get("신규 직책") or "").strip()

    for p in key_points:
        p = _to_briefing_style(str(p).strip())
        if p and p not in out:
            out.append(p)
    if not out and (company or person or ptype):
        if person and company:
            out.append(f"{person} {company} {prev_role or '이사'} {new_role or ptype}함")
        elif company and ptype:
            out.append(f"{company} {ptype} 관련")
    return out[:10] if out else ["요약 없음"]


def _is_unknown_person(name: str) -> bool:
    """인물명이 없거나 '없음'·'(없음)'·빈값이면 True."""
    s = (name or "").strip().strip("'\"()").strip()
    return not s or s in ("없음", "미상", "불명", "알 수 없음")


def _action_line(it: dict) -> str:
    """'이름' 변동 내용. 인물명이 없으면 빈 문자열 → 불렛에서 제외됨."""
    raw_person = (it.get("대상 인물") or "").strip()
    if _is_unknown_person(raw_person):
        return ""
    person = _format_person_name(raw_person)
    action_type = (it.get("인사 유형") or "").strip()
    prev = (it.get("기존 직책") or "").strip()
    if prev == "없음":
        prev = ""
    new = (it.get("신규 직책") or "").strip()
    if new == "없음":
        new = ""
    timing = (it.get("인사 시기") or "").strip()
    company = (it.get("회사명") or "").strip()
    origin_company = (it.get("출신 회사") or "").strip()

    # 타사 출신이 C회사에 선임된 경우: "A 출신 B 사장이 C 대표로 선임"
    if origin_company and company and person and ("선임" in action_type or "영입" in action_type or "임명" in action_type):
        prev_role_part = f" {prev}" if prev else ""
        subject_josa = "이" if prev_role_part else "가"  # B 사장이 / B가
        new_role_part = (new or action_type).replace("선임", "").replace("영입", "").strip() or "선임"
        line = f"{origin_company} 출신 {person}{prev_role_part}{subject_josa} {company} {new_role_part}로 선임"
        if timing:
            line = re.sub(r"\s*\(\s*" + re.escape(timing) + r"\s*\)\s*$", "", line).strip()
            line = f"{timing}, {line}"
            if "주총" in timing and "승인" in timing:
                line = line + " 예정"
        return line

    # 재선임/연임: 기존·신규 직함이 같을 수 있으므로 action_type 앞의 직함 중복 제거
    is_reappointment = "재선임" in action_type or "연임" in action_type
    if prev and is_reappointment and action_type.startswith(prev):
        action_type = action_type[len(prev):].strip()

    # 재선임/연임은 이전 직책만 표기 (신규 직책 제외)
    if is_reappointment:
        new = ""

    if prev and new:
        if new and (new in action_type or action_type.startswith(new)):
            part = f"{prev}의 {action_type}"
        else:
            part = f"{prev}의 {new} {action_type}" if action_type else f"{prev} → {new}"
    elif prev:
        if prev in action_type or action_type.startswith(prev):
            part = action_type
        else:
            part = f"{prev} {action_type}"
    elif new:
        if new in action_type or action_type.startswith(new):
            part = action_type
        else:
            part = f"{new} {action_type}" if action_type else new
    else:
        part = action_type

    if timing:
        part = re.sub(r"\s*\(\s*" + re.escape(timing) + r"\s*\)\s*$", "", part).strip()
    line = f"{person}의 {part}" if (person and not prev) else (f"{person} {part}" if person else part)
    if timing:
        line = f"{timing}, {line}"
        if "주총" in timing and "승인" in timing:
            line = line + " 예정"
    return line


def _action_part_for_grouping(line: str) -> str:
    """임원인사 한 줄에서 '이름'·시기 접두어를 제거한 표현(사장 선임 등) 추출. 같은 표현끼리 묶기 위함."""
    s = (line or "").strip()
    s = re.sub(r"^주총\s*승인\s*후\s*,\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^'[^']*'\s*", "", s)
    s = re.sub(r"^\"[^\"]*\"\s*", "", s)
    return s.strip() or line


def _merge_same_person_agenda_and_action(exec_pairs: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    """동일 인물에 대해 '안건' 한 줄과 '재선임/선임' 한 줄이 있으면 하나로 합친다. 합친 형식: 주주총회에서 '(이름)' (직함)의 (인사유형) 안건이 도출됨."""
    from collections import defaultdict
    by_person: dict[tuple, list[tuple[str, tuple]]] = defaultdict(list)
    for line, c in exec_pairs:
        company, person_norm, action_type = c
        by_person[(company, person_norm)].append((line, c))

    out = []
    for (company, person_norm), pairs in by_person.items():
        if len(pairs) != 2:
            out.extend(pairs)
            continue
        line1, c1 = pairs[0]
        line2, c2 = pairs[1]
        has_agenda_1 = "안건" in (line1 or "")
        has_agenda_2 = "안건" in (line2 or "")
        has_action_1 = "재선임" in (line1 or "") or "선임" in (line1 or "") or "연임" in (line1 or "")
        has_action_2 = "재선임" in (line2 or "") or "선임" in (line2 or "") or "연임" in (line2 or "")
        if not (has_agenda_1 != has_agenda_2 and has_action_1 != has_action_2):
            out.extend(pairs)
            continue
        agenda_line = line1 if has_agenda_1 else line2
        action_line = line2 if has_agenda_1 else line1
        # 직함: "'이름' 대표이사의" → 대표이사
        role_match = re.search(r"'[^']+'\s+([^의]+)의\s+.*안건", agenda_line or "")
        role = (role_match.group(1).strip() if role_match else "").strip()
        # 인사유형: "의 사내이사 재선임" 또는 "사내이사 재선임"
        action_match = re.search(r"(사내이사|사외이사|감사위원|이사)\s*(재선임|선임|연임)", action_line or "")
        action_part = (action_match.group(0).strip() if action_match else "").strip()
        if not role or not action_part:
            out.extend(pairs)
            continue
        person_quoted = f"'{person_norm}'"
        merged_line = f"주주총회에서 {person_quoted} {role}의 {action_part} 안건이 도출됨"
        merged_c = (company, person_norm, f"{action_part} 안건")
        out.append((merged_line, merged_c))
    return out


def _first_quoted_name_and_rest(s: str) -> tuple[str | None, str]:
    """첫 번째 '…' 안의 이름과, 그 닫는 따옴표 뒤 나머지 문장."""
    m = re.search(r"'([^']*)'", s or "")
    if not m:
        return None, (s or "").strip()
    name = (m.group(1) or "").strip()
    rest = (s[m.end() :] or "").strip()
    return name, rest


def _core_action_key(s: str) -> str:
    """불렛 문자열에서 핵심 행위 키(재선임/선임/연임/사임 등) 추출. 비교용."""
    for kw in ("재선임", "연임", "사임", "선임"):
        if kw in (s or ""):
            return kw
    return ""


def _try_merge_exec_pair_lines(
    pair_a: tuple[str, tuple],
    pair_b: tuple[str, tuple],
) -> tuple[str, tuple] | None:
    """같은 내용으로 보이는 두 불렛을 하나로 합칠 수 있으면 (합친 줄, c) 반환, 아니면 None.

    병합 기준:
    1) 한쪽 이름이 '없음', 따옴표 뒤 문장 동일 → 실명 줄 유지
    2) 동일 인물·동일 문장 → 중복 제거
    3) 동일 인물, 직함/문장 포함 관계 → 긴(구체적) 줄 유지
    4) 동일 인물·동일 핵심 행위(재선임/선임 등) → 주총 안건 형식 또는 더 긴(구체적) 줄 유지
    """
    line_a, c_a = pair_a
    line_b, c_b = pair_b
    na, ra = _first_quoted_name_and_rest(line_a)
    nb, rb = _first_quoted_name_and_rest(line_b)
    if na is None or nb is None:
        return None

    def norm_rest(r: str) -> str:
        return re.sub(r"\s+", " ", (r or "").strip())

    ra_n, rb_n = norm_rest(ra), norm_rest(rb)

    # 1) 한쪽 이름이 '없음', 따옴표 뒤 문장 동일 → 실명 줄 유지
    if na in ("없음",) and nb not in ("없음",) and ra_n == rb_n:
        return (line_b, c_b)
    if nb in ("없음",) and na not in ("없음",) and ra_n == rb_n:
        return (line_a, c_a)

    # 이름이 다르면 이후 규칙 적용 안 함
    if na != nb or not na or na == "없음":
        return None

    # 2) 동일 인물·동일 문장 → 중복 제거
    if ra_n == rb_n:
        return (line_a, c_a)

    # 3) 동일 인물, 직함/문장 포함 관계 → 긴(구체적) 줄 유지
    if ra_n.endswith(rb_n) or rb_n.endswith(ra_n):
        return (line_a, c_a) if len(ra_n) >= len(rb_n) else (line_b, c_b)
    if rb_n in ra_n and len(ra_n) > len(rb_n):
        return (line_a, c_a)
    if ra_n in rb_n and len(rb_n) > len(ra_n):
        return (line_b, c_b)

    # 4) 동일 인물·동일 핵심 행위(재선임/선임/연임 등) → 주총 안건 형식 우선, 없으면 더 긴 줄 유지
    core_a = _core_action_key(line_a)
    core_b = _core_action_key(line_b)
    if core_a and core_b and core_a == core_b:
        is_agenda_a = "주총" in (line_a or "") or "안건" in (line_a or "")
        is_agenda_b = "주총" in (line_b or "") or "안건" in (line_b or "")
        if is_agenda_a and not is_agenda_b:
            return (line_a, c_a)
        if is_agenda_b and not is_agenda_a:
            return (line_b, c_b)
        # 둘 다 주총 안건 형식이거나 둘 다 아닌 경우 → 더 긴(구체적) 줄 유지
        return (line_a, c_a) if len(line_a) >= len(line_b) else (line_b, c_b)

    return None


def _dedupe_similar_exec_pairs(pairs: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    """'없음' vs 실명 동일 문장, 또는 동일 인물의 짧은·긴 직함 표기 등을 한 줄로 합침."""
    if len(pairs) < 2:
        return pairs
    out = list(pairs)
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                merged = _try_merge_exec_pair_lines(out[i], out[j])
                if merged is not None:
                    out[i] = merged
                    out.pop(j)
                    changed = True
                    break
            if changed:
                break
    return out


def _build_html_from_summary(
    items: list[dict],
    subject: str,
    sent_dedup: dict | None = None,
) -> tuple[str, list[tuple], list[tuple]]:
    """회사별로 묶고 [임원인사]/[조직개편] 섹션으로 HTML 생성.
    sent_dedup 있으면 이전 메일과 중복된 (회사,인물,인사유형)/(회사,조직개편) 제외.
    반환: (html, 이번 메일에 포함한 exec 키 목록, org 키 목록)
    """
    from collections import defaultdict
    sent_exec = (sent_dedup or {}).get("exec") or set()
    sent_org = (sent_dedup or {}).get("org") or set()
    by_company: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        company = (it.get("회사명") or "").strip() or "(회사명 없음)"
        by_company[company].append(it)

    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        "<ul>",
    ]
    sent_exec_this = []
    sent_org_this = []

    for company in sorted(by_company.keys(), key=lambda x: (x.startswith("("), x)):
        group = by_company[company]
        rep_date = ""
        rep_url = ""
        rep_reason = ""
        for it in group:
            if not rep_date and it.get("pubDate"):
                rep_date = _pubdate_to_mmdd(it.get("pubDate") or "")
            raw_url = (it.get("기사 URL") or "").strip()
            if not rep_url and _is_valid_article_url(raw_url):
                rep_url = raw_url
            if not rep_reason and (it.get("진행 이유") or "").strip():
                rep_reason = (it.get("진행 이유") or "").strip()

        exec_items = []
        org_changes_list = []
        org_changes_seen = set()
        exec_lines_out = []
        for it in group:
            cf = it.get("category_flags") or {}
            is_exec = cf.get("exec_personnel", True)
            is_org = cf.get("org_restructuring", False)
            if is_exec and (it.get("대상 인물") or it.get("인사 유형")):
                exec_items.append(it)
            if is_org:
                for oc in it.get("org_changes") or []:
                    s = str(oc).strip() if oc else ""
                    if s and s not in org_changes_seen:
                        org_changes_seen.add(s)
                        org_changes_list.append(s)

        has_exec = bool(exec_items)
        has_org = bool(org_changes_list)
        if not has_exec and not has_org:
            has_exec = True
            exec_items = group

        # 이전 메일과 중복 제거: 임원인사. 같은 표현(사장 선임 등)끼리 묶어서 정렬
        seen_exec = set()
        exec_pairs = []
        for it in exec_items:
            line = _action_line(it)
            if not line:
                continue
            person_norm = _normalize_person_for_dedup(it.get("대상 인물") or "")
            action_type = (it.get("인사 유형") or "").strip()
            c = (company, person_norm)
            if sent_dedup and person_norm and c in sent_exec:
                continue
            if line in seen_exec:
                continue
            seen_exec.add(line)
            exec_pairs.append((line, c))
        exec_pairs = _merge_same_person_agenda_and_action(exec_pairs)
        exec_pairs = _dedupe_similar_exec_pairs(exec_pairs)
        exec_pairs.sort(key=lambda p: (_action_part_for_grouping(p[0]), p[0]))
        exec_lines_out = [p[0] for p in exec_pairs]
        for _, c in exec_pairs:
            sent_exec_this.append(c)

        # 이전 메일과 중복 제거: 조직개편
        org_filtered = []
        for oc in org_changes_list:
            c = (company, oc)
            if sent_dedup and c in sent_org:
                continue
            org_filtered.append(oc)
            sent_org_this.append(c)
        org_changes_list = org_filtered

        # 새 소식만 있던 항목이 하나도 없으면 이 회사 블록 생략
        if not exec_lines_out and not org_changes_list:
            continue

        if exec_lines_out and org_changes_list:
            section_label = f"{company}, 임원인사 및 조직개편 진행"
        elif org_changes_list:
            section_label = f"{company}, 조직개편 진행"
        else:
            section_label = f"{company}, 임원인사 진행"

        # 제목·날짜·링크: 스페이스 하나로 구분
        p_parts = [f"<strong>{section_label}</strong>"]
        if rep_date:
            p_parts.append(f"({rep_date})")
        if rep_url and _is_valid_article_url(rep_url):
            p_parts.append(f'<a href="{rep_url}">기사 보기</a>')
        lines.append("  <li>")
        lines.append("    <p>" + " ".join(p_parts) + "</p>")
        # 임원인사/조직개편: 한 가지만 있으면 라벨 없이 내용만. 둘 다 있으면 라벨을 두 번째 단계, 내용을 세 번째 단계로
        if exec_lines_out and org_changes_list:
            lines.append("    <ul>")
            lines.append("      <li>임원인사")
            lines.append("        <ul>")
            for line in exec_lines_out:
                lines.append(f"          <li>{_normalize_display(line)}</li>")
            lines.append("        </ul>")
            lines.append("      </li>")
            lines.append("      <li>조직개편")
            lines.append("        <ul>")
            for oc in org_changes_list:
                lines.append(f"          <li>{_normalize_display(oc)}</li>")
            lines.append("        </ul>")
            lines.append("      </li>")
            if rep_reason:
                lines.append(f"      <li>진행 이유: {_reason_to_noun_form(rep_reason)}</li>")
            lines.append("    </ul>")
        elif exec_lines_out:
            lines.append("    <ul>")
            for line in exec_lines_out:
                lines.append(f"      <li>{_normalize_display(line)}</li>")
            if rep_reason:
                lines.append(f"      <li>진행 이유: {_reason_to_noun_form(rep_reason)}</li>")
            lines.append("    </ul>")
        elif org_changes_list:
            lines.append("    <ul>")
            for oc in org_changes_list:
                lines.append(f"      <li>{_normalize_display(oc)}</li>")
            if rep_reason:
                lines.append(f"      <li>진행 이유: {_reason_to_noun_form(rep_reason)}</li>")
            lines.append("    </ul>")
        lines.append("  </li>")
    lines.append("</ul></body></html>")
    return "\n".join(lines), sent_exec_this, sent_org_this


def _content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _should_skip_send(body: str) -> bool:
    """sent_log 와 비교해 동일 내용·당일 이미 발송이면 True."""
    if os.environ.get("FORCE_SEND", "").strip() == "1":
        return False
    if not SENT_LOG_JSON.exists():
        return False
    try:
        with open(SENT_LOG_JSON, "r", encoding="utf-8") as f:
            log = json.load(f)
    except Exception:
        return False
    h = _content_hash(body)
    if log.get("content_hash") != h:
        return False
    last = log.get("last_sent_at")
    if not last:
        return False
    try:
        # ISO 형식 파싱 후 KST 당일 여부 확인 (간단히 날짜 문자열 비교)
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        from datetime import timedelta
        now_utc = datetime.now(timezone.utc)
        if (now_utc - dt).total_seconds() < 3600 * 24:  # 24시간 이내 동일 내용
            return True
    except Exception:
        pass
    return False


def send_gmail_from_json(
    json_path: Path | None = None,
    password: str | None = None,
    sender: str | None = None,
):
    if json_path is None:
        json_path = NEWS_SUMMARY_JSON if NEWS_SUMMARY_JSON.exists() else EMAIL_CONTENT_JSON
    if not json_path.exists():
        print(f"오류: {json_path} 파일이 없습니다. summarize_exec_news_llm.py 를 먼저 실행하세요.")
        return 1

    password = (password or os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    if not password:
        print("오류: GMAIL_APP_PASSWORD 환경 변수가 없습니다.")
        return 1

    # news_summary.json 우선
    items = []
    sent_exec_keys: list = []
    sent_org_keys: list = []
    if json_path == NEWS_SUMMARY_JSON and json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        items = payload.get("items") or []
        request_scope = (os.environ.get("REQUEST_SCOPE") or "").strip().lower()
        apply_dedupe = (os.environ.get("APPLY_RECENT_DEDUPE", "1") or "").strip() == "1"
        # workflow_dispatch(today): 직전 발송 시각 필터·recent dedupe 사용 안 함
        if request_scope != "today":
            items = _filter_items_since_last_send(items)
        if request_scope == "today" or not apply_dedupe:
            sent_dedup = {}
        else:
            sent_dedup = _load_sent_dedup_store()
        now = datetime.now()
        if request_scope == "scheduled":
            kst = timezone(timedelta(hours=9))
            now_kst = now.astimezone(kst)
            subject = f"[인사변동] Daily update ({now_kst.strftime('%y/%m/%d')}, {now_kst.hour}시)"
        else:
            subject = f"[인사변동] Daily update ({now.strftime('%y/%m/%d')})"
        if items:
            body, sent_exec_keys, sent_org_keys = _build_html_from_summary(items, subject, sent_dedup)
            if not sent_exec_keys and not sent_org_keys:
                body = (
                    "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
                    "<p>업데이트된 내용 없음</p>"
                    "</body></html>"
                )
        else:
            body = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
                "<p>업데이트된 내용 없음</p>"
                "</body></html>"
            )
            sent_exec_keys = []
            sent_org_keys = []
        to = os.environ.get("GMAIL_TO", "juan.jung@navercorp.com").strip()
    else:
        # 레거시: email_content.json (to, subject, body, contentType)
        items = []
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        to = payload.get("to", "").strip() or os.environ.get("GMAIL_TO", "juan.jung@navercorp.com")
        subject = payload.get("subject", "").strip()
        body = payload.get("body", "").strip()
        if payload.get("contentType", "html").lower() != "html":
            body = f"<pre>{body}</pre>"

    if not subject or not body:
        print("오류: subject 또는 body가 비어 있습니다.")
        return 1

    is_no_update_body = "업데이트된 내용 없음" in body and len(body) < 600
    if not is_no_update_body and _should_skip_send(body):
        print("동일 내용이 24시간 이내 이미 발송됨. 발송 스킵. (FORCE_SEND=1 로 재발송 가능)")
        return 0

    sender = (sender or os.environ.get("GMAIL_SENDER", "naverpartnership@gmail.com")).strip()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls(context=context)
            server.login(sender, password)
            server.sendmail(sender, to, msg.as_string())
    except Exception as e:
        print(f"Gmail 발송 실패: {e}")
        return 1

    # 발송 이력 저장
    try:
        log = {
            "last_sent_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": _content_hash(body),
            "item_count": len(items),
            "subject": subject,
        }
        with open(SENT_LOG_JSON, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"sent_log 저장 경고: {e}")

    # 이번 메일에 포함된 항목을 중복 제거 저장소에 추가 (다음 메일에서 제외용)
    if sent_exec_keys or sent_org_keys:
        try:
            _save_sent_dedup_store(sent_exec_keys, sent_org_keys)
        except Exception as e:
            print(f"sent_dedup_store 저장 경고: {e}")

    print(f"발송 완료: {to} / 제목: {subject}")
    return 0


def record_sent_from_json(json_path: Path) -> int:
    """JSON(예: email_samsung_hyundai.json)에 담긴 sent_exec_keys, sent_org_keys를 sent_dedup_store에 반영.
    WORKS 메일 발송 후 호출하면, 다음 자동 발송 시 해당 항목이 제외됨.
    """
    if not json_path.exists():
        print(f"파일 없음: {json_path}")
        return 1
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON 읽기 실패: {e}")
        return 1
    exec_keys = data.get("sent_exec_keys")
    org_keys = data.get("sent_org_keys")
    if isinstance(exec_keys, list):
        exec_keys = [tuple(x) for x in exec_keys if isinstance(x, (list, tuple)) and len(x) >= 2]
    else:
        exec_keys = []
    if isinstance(org_keys, list):
        org_keys = [tuple(x) for x in org_keys if isinstance(x, (list, tuple)) and len(x) >= 2]
    else:
        org_keys = []
    if not exec_keys and not org_keys:
        print("기록할 sent_exec_keys/sent_org_keys 없음.")
        return 0
    try:
        _save_sent_dedup_store(exec_keys, org_keys)
        print(f"sent_dedup_store 반영: 임원 {len(exec_keys)}건, 조직 {len(org_keys)}건")
    except Exception as e:
        print(f"저장 실패: {e}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--record-sent-from":
        path = Path(sys.argv[2])
        if not path.is_absolute():
            path = OUTPUT_DIR / path
        sys.exit(record_sent_from_json(path))
    sys.exit(send_gmail_from_json())
