# -*- coding: utf-8 -*-
"""
월간 인사변동 브리핑 메일 생성·발송.

- .monthly_archives/monthly_archive_YYYY_MM.json 읽기
- 중복 제거(회사+인물+인사유형) 후 기업별 그룹핑
- 매월 마지막 주 금요일(Asia/Seoul)에만 발송하거나, 로컬/환경변수로 강제 실행
- 각 회사별 임원인사/조직개편 불렛, 내용 끝에 (mm/dd) 기사 링크. Daily 메일과 동일한 표기 로직 적용.

로컬 테스트: python send_monthly_digest.py
환경변수: TARGET_YEAR=2026 TARGET_MONTH=3 (선택), FORCE_SEND_MONTHLY=1 (마지막 금요일 무시하고 발송)
"""
import json
import os
import re
import smtplib
import ssl
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

KST = timezone(timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = OUTPUT_DIR / ".monthly_archives"

try:
    from send_email_from_json import (
        _action_line as _daily_action_line,
        _action_part_for_grouping,
        _normalize_display,
        _pubdate_to_mmdd,
        _is_valid_article_url,
    )
except ImportError:
    _daily_action_line = _action_part_for_grouping = _normalize_display = _pubdate_to_mmdd = _is_valid_article_url = None


def _now_kst() -> datetime:
    return datetime.now(KST)


def _is_last_friday_kst(now: datetime) -> bool:
    """오늘이 해당 월의 마지막 금요일인지. Asia/Seoul 기준."""
    if now.weekday() != 4:  # 4 = Friday
        return False
    seven_later = now + timedelta(days=7)
    return seven_later.month != now.month


def _parse_pub_for_sort(pub_date_str: str) -> datetime | None:
    """pub_date 문자열을 정렬용 datetime으로. 실패 시 None."""
    if not pub_date_str or not str(pub_date_str).strip():
        return None
    s = str(pub_date_str).strip()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.astimezone(KST)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST)
    except Exception:
        return None


def _dedupe_items(items: list[dict]) -> list[dict]:
    """임원인사: (회사, 인물, 인사유형) 1건. 조직만 있는 건 (회사, (), org_changes) 별도 유지. 조직개편 문구 dedupe는 본문 수집 시."""
    key_to_best: dict[tuple, dict] = {}
    for it in items:
        company = (it.get("company") or "").strip()
        person = (it.get("person") or "").strip()
        action_type = (it.get("action_type") or "").strip()
        org_changes = it.get("org_changes") or []
        org_key = tuple(sorted(str(x).strip() for x in org_changes if x))
        key = (company, person, action_type, org_key)
        pub = _parse_pub_for_sort(it.get("pub_date") or "")
        existing = key_to_best.get(key)
        if existing is None:
            key_to_best[key] = it
            continue
        existing_pub = _parse_pub_for_sort(existing.get("pub_date") or "")
        if pub is not None and existing_pub is not None and pub < existing_pub:
            key_to_best[key] = it
    return list(key_to_best.values())


def _format_person(s: str) -> str:
    """인물명이 있으면 작은따옴표로 감쌈."""
    s = (s or "").strip()
    if not s:
        return s
    if s.startswith("'") and s.endswith("'"):
        return s
    return f"'{s}'"


def _archive_entry_to_daily_item(entry: dict) -> dict:
    """월간 archive 항목을 daily 메일 _action_line 입력 형식으로 변환. 직함 '없음'은 빈 문자열로."""
    def _role(v):
        s = (entry.get(v) or "").strip()
        return "" if s == "없음" else s
    return {
        "회사명": (entry.get("company") or "").strip(),
        "대상 인물": (entry.get("person") or "").strip(),
        "인사 유형": (entry.get("action_type") or "").strip(),
        "기존 직책": _role("previous_role"),
        "신규 직책": _role("new_role"),
        "인사 시기": (entry.get("personnel_timing") or "").strip(),
        "pubDate": (entry.get("pub_date") or "").strip(),
        "기사 URL": (entry.get("article_url") or "").strip(),
        "category_flags": entry.get("category_flags") or {},
        "org_changes": entry.get("org_changes") or [],
    }


def _action_line_for_entry(entry: dict) -> str:
    """archive 항목 한 건에 대해 daily와 동일한 표기 라인 생성 (주총 승인 후 문두 등)."""
    if _daily_action_line is not None:
        daily_item = _archive_entry_to_daily_item(entry)
        return _daily_action_line(daily_item)
    person = _format_person(entry.get("person") or "")
    action_type = (entry.get("action_type") or "").strip()
    prev = (entry.get("previous_role") or "").strip()
    if prev == "없음":
        prev = ""
    new = (entry.get("new_role") or "").strip()
    if new == "없음":
        new = ""
    timing = (entry.get("personnel_timing") or "").strip()
    if prev and ("재선임" in action_type or "연임" in action_type) and action_type.startswith(prev):
        action_type = action_type[len(prev):].strip()
    if prev and new:
        part = f"{prev}의 {new} {action_type}" if action_type else f"{prev} → {new}"
        if new and (new in action_type or action_type.startswith(new)):
            part = f"{prev}의 {action_type}"
    elif prev:
        part = f"{prev} {action_type}" if not (prev in action_type or action_type.startswith(prev)) else action_type
    elif new:
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


def _normalize_display_fallback(s: str) -> str:
    if not s:
        return s
    s = (s or "").replace("(완료)", " 완료").replace("(예정)", " 예정")
    s = re.sub(r"',\s*", "' ", s)
    s = re.sub(r"\s*\(\s*주총\s*승인\s*후\s*\)\s*$", "", s, flags=re.IGNORECASE).strip()
    words = s.split()
    out = []
    for w in words:
        if out and out[-1] == w:
            continue
        out.append(w)
    return " ".join(out)


def _mmdd_fallback(pub_date_str: str) -> str:
    if not pub_date_str or not str(pub_date_str).strip():
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(str(pub_date_str).strip())
        return dt.strftime("%m/%d")
    except Exception:
        return ""


def _build_digest_html(entries: list[dict], month: int) -> str:
    """기업별 그룹핑 후 첫 줄은 번호+볼드 기업명, 이어서 불렛으로 임원인사/조직개편. 각 줄 끝 (mm/dd) 기사. 회사명에 쉼표(예: 네이버, 카카오) 있으면 기업별로 분리 표시."""
    by_company: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        c = (e.get("company") or "").strip() or "(회사명 없음)"
        by_company[c].append(e)

    company_blocks = []
    for company in sorted(by_company.keys(), key=lambda x: (x.startswith("("), x)):
        group = by_company[company]
        if "," in company:
            for part in [x.strip() for x in company.split(",") if x.strip()]:
                company_blocks.append((part, group))
        else:
            company_blocks.append((company, group))

    mm = f"{month:02d}"
    norm_display = _normalize_display if _normalize_display is not None else _normalize_display_fallback
    pub_to_mmdd = _pubdate_to_mmdd if _pubdate_to_mmdd is not None else _mmdd_fallback
    is_valid_url = _is_valid_article_url if _is_valid_article_url is not None else lambda u: u and (u.startswith("http://") or u.startswith("https://"))

    companies_display = sorted(set(c for c, _ in company_blocks), key=lambda x: (x.startswith("("), x))
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        f"<h2>{mm}월 인사변동 및 조직개편 브리핑</h2>",
        "<p>- 인사변동 및 조직개편 진행 기업: " + ", ".join(companies_display) + "</p>",
        "<ol>",
    ]
    for i, (company, group) in enumerate(company_blocks, 1):
        exec_seen = set()
        exec_rows = []
        for e in group:
            cf = e.get("category_flags") or {}
            if not cf.get("exec_personnel", True):
                continue
            line = _action_line_for_entry(e)
            if not line:
                continue
            normalized = norm_display(line)
            if normalized in exec_seen:
                continue
            exec_seen.add(normalized)
            mmdd = pub_to_mmdd(e.get("pub_date") or "")
            url = (e.get("article_url") or "").strip()
            exec_rows.append((normalized, mmdd, url))
        if _action_part_for_grouping is not None:
            exec_rows.sort(key=lambda r: (_action_part_for_grouping(r[0]), r[0]))

        org_seen = set()
        org_rows = []
        for e in group:
            cf = e.get("category_flags") or {}
            if not cf.get("org_restructuring", False):
                continue
            mmdd = pub_to_mmdd(e.get("pub_date") or "")
            url = (e.get("article_url") or "").strip()
            for oc in e.get("org_changes") or []:
                oc = (oc or "").strip()
                if not oc:
                    continue
                oc_norm = norm_display(oc)
                if oc_norm in org_seen:
                    continue
                org_seen.add(oc_norm)
                org_rows.append((oc_norm, mmdd, url))

        if not exec_rows and not org_rows:
            continue
        lines.append(f"  <li><strong>{company}</strong>")
        lines.append("    <ul>")
        if exec_rows:
            lines.append("    <li>임원인사")
            lines.append("      <ul>")
            for text, date_part, link in exec_rows:
                suffix = f" ({date_part})" if date_part else ""
                if link and is_valid_url(link):
                    suffix += f" <a href=\"{link}\">기사</a>"
                lines.append(f"        <li>{text}{suffix}</li>")
            lines.append("      </ul>")
            lines.append("    </li>")
        if org_rows:
            lines.append("    <li>조직개편")
            lines.append("      <ul>")
            for text, date_part, link in org_rows:
                suffix = f" ({date_part})" if date_part else ""
                if link and is_valid_url(link):
                    suffix += f" <a href=\"{link}\">기사</a>"
                lines.append(f"        <li>{text}{suffix}</li>")
            lines.append("      </ul>")
            lines.append("    </li>")
        lines.append("    </ul>")
        lines.append("  </li>")
    lines.append("</ol></body></html>")
    return "\n".join(lines)


def run() -> int:
    now = _now_kst()
    year, month = now.year, now.month
    if os.environ.get("TARGET_YEAR"):
        try:
            year = int(os.environ.get("TARGET_YEAR", year))
        except ValueError:
            pass
    if os.environ.get("TARGET_MONTH"):
        try:
            month = int(os.environ.get("TARGET_MONTH", month))
        except ValueError:
            pass

    is_last_fri = _is_last_friday_kst(now)
    force = os.environ.get("FORCE_SEND_MONTHLY", "").strip() == "1"

    archive_name = f"monthly_archive_{year}_{month:02d}.json"
    archive_path = ARCHIVE_DIR / archive_name

    print(f"대상 연월: {year}-{month:02d}")
    print(f"archive 파일: {archive_name}")
    print(f"마지막 금요일 여부: {is_last_fri}")
    print(f"FORCE_SEND_MONTHLY: {force}")

    if not force and not is_last_fri:
        print("해당 월 마지막 금요일이 아니므로 종료(발송 없음).")
        return 0

    if not archive_path.exists():
        print(f"archive 없음: {archive_path}. 0건 메일 발송.")
        subject = f"[인사변동] Monthly update ({year % 100}/{month:02d})"
        body_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><p>{subject}</p><p>{month:02d}월 인사변동 및 조직개편 없음</p></body></html>"
        _send_gmail(subject, body_html)
        print("메일 발송: 0건 브리핑 발송함.")
        return 0

    with open(archive_path, "r", encoding="utf-8") as f:
        archive = json.load(f)
    raw_items = archive.get("items") or []
    print(f"원본 건수: {len(raw_items)}")

    entries = _dedupe_items(raw_items)
    print(f"dedupe 후 건수: {len(entries)}")
    companies = set((e.get("company") or "").strip() for e in entries if (e.get("company") or "").strip())
    print(f"기업 수: {len(companies)}")

    if not entries:
        subject = f"[인사변동] Monthly update ({year % 100}/{month:02d})"
        body_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><p>{subject}</p><p>{month:02d}월 인사변동 및 조직개편 없음</p></body></html>"
        _send_gmail(subject, body_html)
        print("메일 발송: 0건 브리핑 발송함.")
        return 0

    subject = f"[인사변동] Monthly update ({year % 100}/{month:02d})"
    body_html = _build_digest_html(entries, month)
    _send_gmail(subject, body_html)
    print("메일 발송: 완료.")
    return 0


def _send_gmail(subject: str, body_html: str) -> None:
    password = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    if not password:
        print("오류: GMAIL_APP_PASSWORD 환경 변수가 없습니다.")
        raise SystemExit(1)
    sender = (os.environ.get("GMAIL_SENDER") or "wjdwndks99@gmail.com").strip()
    to = (os.environ.get("GMAIL_TO") or "juan.jung@navercorp.com").strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=context)
        server.login(sender, password)
        server.sendmail(sender, to, msg.as_string())
    print(f"발송 완료: {to} / 제목: {subject}")


if __name__ == "__main__":
    raise SystemExit(run())
