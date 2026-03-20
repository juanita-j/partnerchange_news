# -*- coding: utf-8 -*-
"""
Gmail SMTP로 이메일 발송 스크립트.
앱 비밀번호는 환경 변수 GMAIL_APP_PASSWORD 또는 .env에 설정 (공백 없이).
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# .env 사용 시 (선택)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 기본 발송 정보 (필요 시 수정 또는 환경 변수로 덮어쓰기)
SENDER = os.environ.get("GMAIL_SENDER", "naverpartnership@gmail.com")
TO = os.environ.get("GMAIL_TO", "juan.jung@navercorp.com")
SUBJECT = os.environ.get("GMAIL_SUBJECT", "테스트")
BODY = os.environ.get("GMAIL_BODY", "테스트")

# Gmail 앱 비밀번호 (공백 제거한 값). 반드시 환경 변수 GMAIL_APP_PASSWORD 로 설정.
# 예: set GMAIL_APP_PASSWORD=ocevkjzioewtsrhh
APP_PASSWORD_ENV = "GMAIL_APP_PASSWORD"


def send_gmail(
    to: str = TO,
    subject: str = SUBJECT,
    body: str = BODY,
    sender: str = SENDER,
    password: str | None = None,
    html: bool = False,
):
    password = password or os.environ.get(APP_PASSWORD_ENV)
    if not password:
        print("오류: Gmail 앱 비밀번호가 없습니다.")
        print("  PowerShell: $env:GMAIL_APP_PASSWORD='ocevkjzioewtsrhh'")
        print("  또는 이 폴더의 .env 파일에 GMAIL_APP_PASSWORD=ocevkjzioewtsrhh 추가")
        return False
    # 공백 제거 (복붙 시 스페이스 포함될 수 있음)
    password = password.replace(" ", "").strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    subtype = "html" if html else "plain"
    msg.attach(MIMEText(body, subtype, "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=context)
        server.login(sender, password)
        server.sendmail(sender, to, msg.as_string())

    print(f"발송 완료: {to} / 제목: {subject}")
    return True


if __name__ == "__main__":
    send_gmail()
