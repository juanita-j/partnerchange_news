# 변경 사항을 Git에 적용하는 방법

## 1. 터미널에서 Git 저장소 루트로 이동

```powershell
cd C:\Users\USER
```

(저장소 루트가 다른 폴더라면 해당 경로로 이동)

## 2. 변경된 파일만 스테이징

**임원인사 뉴스 스크립트·규칙만 커밋할 때:**

```powershell
git add .cursor/daily-exec-news/send_exec_news_timed.py
git add .cursor/daily-exec-news/send_exec_news_partners.py
git add .cursor/rules/daily-exec-news-mail.mdc
```

**`.cursor` 전체를 한 번에 추적할 때:**

```powershell
git add .cursor/
```

## 3. 커밋

```powershell
git commit -m "인사변동 뉴스 출력 형식 적용: 템플릿·일반 규칙, 블로그 제외, 회사별 종합"
```

원하는 메시지로 바꿔도 됩니다.

## 4. 원격에 반영 (선택)

```powershell
git push origin main
```

`main` 대신 사용 중인 브랜치 이름을 넣으면 됩니다.

---

## 한 줄 요약

```powershell
cd C:\Users\USER
git add .cursor/daily-exec-news/send_exec_news_timed.py .cursor/daily-exec-news/send_exec_news_partners.py .cursor/rules/daily-exec-news-mail.mdc
git commit -m "인사변동 뉴스 출력 형식 및 정리 포맷 적용"
git push origin main
```
