# -*- coding: utf-8 -*-
"""
월간 인사변동 브리핑 메일 생성·발송.

- .monthly_archives/monthly_archive_YYYY_MM.json 읽기
- 중복 제거(회사+인물+인사유형) 후 기업별 그룹핑
- 매월 마지막 주 금요일(Asia/Seoul)에만 발송하거나, 로컬/환경변수로 강제 실행

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


def _action_line(entry: dict) -> str:
    """'이름', 변동 내용. 직위 중복 없이, 이전 직함이 있으면 '직함의 변동 내용' 형태로."""
    person = _format_person(entry.get("person") or "")
    action_type = (entry.get("action_type") or "").strip()
    prev = (entry.get("previous_role") or "").strip()
    new = (entry.get("new_role") or "").strip()
    timing = (entry.get("personnel_timing") or "").strip()

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
        part = f"{part} ({timing})"
    if person:
        return f"{person}, {part}"
    return part


def _build_digest_html(entries: list[dict], month: int) -> str:
    """기업별 그룹핑 후 [임원인사]/[조직개편] 섹션으로 HTML 본문 생성. 조직개편은 (회사, 문구) 기준 dedupe."""
    by_company: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        c = (e.get("company") or "").strip() or "(회사명 없음)"
        by_company[c].append(e)

    companies_sorted = sorted(by_company.keys(), key=lambda x: (x.startswith("("), x))
    mm = f"{month:02d}"

    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        f"<h2>{mm}월 인사변동 및 조직개편 브리핑</h2>",
        "<p>- 인사변동 및 조직개편 진행 기업: " + ", ".join(companies_sorted) + "</p>",
        "<ol>",
    ]
    for i, company in enumerate(companies_sorted, 1):
        group = by_company[company]
        rep_link = ""
        exec_lines_seen = set()
        org_changes_seen = set()
        exec_lines = []
        org_lines = []
        for e in group:
            url = (e.get("article_url") or "").strip()
            if url:
                rep_link = url
            cf = e.get("category_flags") or {}
            is_exec = cf.get("exec_personnel", True)
            is_org = cf.get("org_restructuring", False)
            if is_exec:
                line = _action_line(e)
                if line and line not in exec_lines_seen:
                    exec_lines_seen.add(line)
                    exec_lines.append(line)
            if is_org:
                for oc in e.get("org_changes") or []:
                    oc = (oc or "").strip()
                    if oc and oc not in org_changes_seen:
                        org_changes_seen.add(oc)
                        org_lines.append(oc)
        lines.append(f"  <li><strong>{company}</strong>")
        lines.append("    <ul>")
        if exec_lines and org_lines:
            lines.append("    <li>임원인사")
            lines.append("    <ul>")
            for line in exec_lines:
                lines.append(f"      <li>{line}</li>")
            lines.append("    </ul>")
            lines.append("    </li>")
            lines.append("    <li>조직개편")
            lines.append("    <ul>")
            for oc in sorted(org_lines):
                lines.append(f"      <li>{oc}</li>")
            lines.append("    </ul>")
            lines.append("    </li>")
        elif exec_lines:
            for line in exec_lines:
                lines.append(f"    <li>{line}</li>")
        elif org_lines:
            for oc in sorted(org_lines):
                lines.append(f"    <li>{oc}</li>")
        if rep_link:
            lines.append(f'    <li><a href="{rep_link}">기사 보기</a></li>')
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
        subject = f"{month:02d}월 인사변동 및 조직개편 브리핑"
        body_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><h2>{subject}</h2><p>{month:02d}월 인사변동 및 조직개편 없음</p></body></html>"
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
        subject = f"{month:02d}월 인사변동 및 조직개편 브리핑"
        body_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><h2>{subject}</h2><p>{month:02d}월 인사변동 및 조직개편 없음</p></body></html>"
        _send_gmail(subject, body_html)
        print("메일 발송: 0건 브리핑 발송함.")
        return 0

    subject = f"{month:02d}월 인사변동 및 조직개편 브리핑"
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
