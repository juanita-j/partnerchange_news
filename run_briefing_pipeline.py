# -*- coding: utf-8 -*-
"""
임원인사 브리핑 메일용 파이프라인 한 번에 실행.

순서: send_exec_news_timed.py → summarize_exec_news_llm.py → send_exec_news_partners.py
실행 후 email_partners.json 이 생성·갱신되므로, 이 파일을 읽어 mail_send 하면 됨.
"""
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent


def main() -> int:
    python = sys.executable
    steps = [
        ("뉴스 수집", [python, "send_exec_news_timed.py"]),
        ("LLM 요약", [python, "summarize_exec_news_llm.py"]),
        ("메일 본문 생성", [python, "send_exec_news_partners.py"]),
    ]
    for name, cmd in steps:
        print(f"[{name}] 실행 중: {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=DIR)
        if r.returncode != 0:
            print(f"[{name}] 실패 (exit {r.returncode}). 다음 단계는 스킵.")
            return r.returncode
    print("파이프라인 완료. email_partners.json 을 읽어 메일 발송하면 됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
