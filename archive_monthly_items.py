# -*- coding: utf-8 -*-
"""
daily 발송 후 news_summary.json의 items를 해당 월 archive에 누적 저장.

- 읽기: news_summary.json (기존 daily 메일 내용 기준)
- 저장: .monthly_archives/monthly_archive_YYYY_MM.json
- 뉴스 재검색 없음. GitHub Actions에서는 cache로 .monthly_archives 유지.

로컬 테스트: python archive_monthly_items.py
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

KST = timezone(__import__("datetime").timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent
NEWS_SUMMARY_JSON = OUTPUT_DIR / "news_summary.json"
ARCHIVE_DIR = OUTPUT_DIR / ".monthly_archives"


def _now_kst() -> datetime:
    return datetime.now(KST)


def _item_to_archive_entry(it: dict, date_iso: str) -> dict:
    """news_summary item → 월간 archive 항목 형식."""
    company = (it.get("회사명") or "").strip()
    person_raw = (it.get("대상 인물") or "").strip()
    person = re.sub(r"^['\"]|['\"]$", "", person_raw)
    action_type = (it.get("인사 유형") or "").strip()
    previous_role = (it.get("기존 직책") or "").strip()
    new_role = (it.get("신규 직책") or "").strip()
    key_points = it.get("중요 포인트") or []
    important_point = (key_points[0] if isinstance(key_points, list) and key_points else "") or ""
    if isinstance(important_point, dict):
        important_point = ""
    important_point = str(important_point).strip()
    bullet_points = it.get("bullet_points") or []
    if not isinstance(bullet_points, list):
        bullet_points = []
    article_url = (it.get("기사 URL") or "").strip()
    pub_date = (it.get("pubDate") or "").strip()
    personnel_timing = (it.get("인사 시기") or "").strip()
    category_flags = it.get("category_flags") or {}
    org_changes = it.get("org_changes") or []
    if not isinstance(org_changes, list):
        org_changes = []

    out = {
        "date": date_iso,
        "company": company,
        "person": person,
        "action_type": action_type,
        "previous_role": previous_role,
        "new_role": new_role,
        "important_point": important_point,
        "bullet_points": bullet_points,
        "article_url": article_url,
        "article_title": "",
        "pub_date": pub_date,
        "category_flags": {"exec_personnel": bool(category_flags.get("exec_personnel")), "org_restructuring": bool(category_flags.get("org_restructuring"))},
        "org_changes": [str(x).strip() for x in org_changes if x],
    }
    if personnel_timing:
        out["personnel_timing"] = personnel_timing
    return out


def run() -> int:
    if not NEWS_SUMMARY_JSON.exists():
        print(f"news_summary.json 없음. 건너뜀.")
        return 0

    with open(NEWS_SUMMARY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items") or []
    if not items:
        print("요약 items 0건. archive 적재 건너뜀.")
        return 0

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

    date_iso = now.strftime("%Y-%m-%d")
    archive_name = f"monthly_archive_{year}_{month:02d}.json"
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / archive_name

    if archive_path.exists():
        with open(archive_path, "r", encoding="utf-8") as f:
            archive = json.load(f)
    else:
        archive = {
            "year": year,
            "month": month,
            "updated_at": "",
            "items": [],
        }

    new_entries = [_item_to_archive_entry(it, date_iso) for it in items]
    archive["items"].extend(new_entries)
    archive["updated_at"] = now.isoformat()

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    total = len(archive["items"])
    print(f"archive 파일: {archive_path}")
    print(f"추가 건수: {len(new_entries)}")
    print(f"총 누적 건수: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
